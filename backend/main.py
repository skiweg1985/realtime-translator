"""Single-worker, ephemeral rooms bridging browsers to LiteLLM Translate."""
import asyncio
import base64
import contextlib
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

LANGUAGES = {'de', 'en', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'uk', 'tr', 'ar', 'ja', 'zh'}
URL = os.getenv('TRANSLATE_URL', 'wss://litellm-test.simplicity.ag/v1/realtime/translations?model=azure-live-translate')
KEY = os.getenv('TRANSLATE_KEY', '')
model = None
model_status = 'loading'
transcribe_lock = asyncio.Lock()

@dataclass(eq=False)
class Peer:
    ws: WebSocket
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=100))

@dataclass
class Room:
    owner: str
    language: str
    source: str
    created: float = field(default_factory=time.monotonic)
    active: bool = False
    peers: set = field(default_factory=set)
    text: str = ''
    original: str = ''

rooms: dict[str, Room] = {}

def load_model():
    global model, model_status
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(os.getenv('WHISPER_MODEL', 'tiny'), device='cpu', compute_type='int8', cpu_threads=4)
        model_status = 'ready'
    except Exception:
        model_status = 'unavailable'

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(asyncio.to_thread(load_model))
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get('/api/health')
def health():
    return {'ok': True, 'translation_configured': bool(KEY), 'transcription': model_status}

class NewRoom(BaseModel):
    language: str = 'en'
    source: str = 'de'

@app.post('/api/rooms')
def create_room(body: NewRoom, request: Request):
    origin = request.headers.get('origin')
    if origin and origin.split('://', 1)[-1] != request.headers.get('host'):
        raise HTTPException(403, 'Origin rejected')
    for room_id, room in list(rooms.items()):
        if not room.active and time.monotonic() - room.created > 7200:
            del rooms[room_id]
    if body.language not in LANGUAGES or body.source not in LANGUAGES:
        raise HTTPException(400, 'Unsupported language')
    if len(rooms) >= 100:
        raise HTTPException(429, 'Zu viele Sitzungen. Bitte später erneut versuchen.')
    if not KEY:
        raise HTTPException(503, 'Der Übersetzungszugang ist noch nicht eingerichtet.')
    room_id = secrets.token_urlsafe(18)
    owner = secrets.token_urlsafe(24)
    rooms[room_id] = Room(owner=owner, language=body.language, source=body.source)
    return {'id': room_id, 'owner': owner}

@app.get('/api/rooms/{room_id}')
def room_info(room_id: str):
    room = rooms.get(room_id)
    if not room:
        raise HTTPException(404, 'Diese Sitzung ist nicht mehr verfügbar.')
    return {'language': room.language, 'source': room.source, 'active': room.active}

async def broadcast(room, event):
    for peer in list(room.peers):
        try:
            peer.queue.put_nowait(event)
        except asyncio.QueueFull:
            room.peers.discard(peer)
            await peer.ws.close(code=1013, reason='Verbindung zu langsam. Bitte erneut beitreten.')

async def send_peer(peer):
    while True:
        await peer.ws.send_json(await peer.queue.get())

async def counts(room):
    await broadcast(room, {'type': 'listeners', 'count': max(0, len(room.peers) - int(room.active))})

async def transcribe_audio(room, queue):
    while True:
        pcm = await queue.get()
        if model is None:
            continue
        def run():
            samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
            # Whisper consumes 16 kHz, input is 24 kHz PCM.
            samples = np.interp(np.arange(0, len(samples), 1.5), np.arange(len(samples)), samples).astype(np.float32)
            segments, _ = model.transcribe(samples, language=room.source, beam_size=1, vad_filter=True, condition_on_previous_text=False)
            return ' '.join(s.text.strip() for s in segments).strip()
        try:
            async with transcribe_lock:
                text = await asyncio.to_thread(run)
            if text:
                room.original = (room.original + ' ' + text).strip()[-20000:]
                await broadcast(room, {'type': 'original', 'text': room.original})
        except Exception:
            await broadcast(room, {'type': 'notice', 'message': 'Originaltext ist momentan nicht verfügbar. Die Übersetzung läuft weiter.'})

async def translation(room, ws):
    audio_queue = asyncio.Queue(maxsize=6)
    transcriber = asyncio.create_task(transcribe_audio(room, audio_queue))
    try:
        async with websockets.connect(URL, additional_headers={'Authorization': 'Bearer ' + KEY}, proxy=None, open_timeout=15, close_timeout=2, max_size=1048576) as upstream:
            await upstream.send(json.dumps({'type': 'session.update', 'session': {'audio': {'output': {'language': room.language}}}}))
            async with asyncio.timeout(20):
                while True:
                    event = json.loads(await upstream.recv())
                    if event.get('type') == 'error':
                        raise RuntimeError('Session rejected')
                    if event.get('type') == 'session.updated':
                        break
            await broadcast(room, {'type': 'status', 'status': 'live'})
            async def receive():
                async for raw in upstream:
                    event = json.loads(raw)
                    kind = event.get('type')
                    if kind == 'session.output_audio.delta':
                        await broadcast(room, {'type': 'audio', 'delta': event['delta']})
                    elif kind == 'session.output_transcript.delta':
                        room.text = (room.text + event['delta'])[-20000:]
                        await broadcast(room, {'type': 'translation', 'text': room.text})
                    elif kind == 'error':
                        raise RuntimeError('Upstream error')
            async def send():
                buffer = bytearray()
                silent = 0
                def enqueue():
                    if len(buffer) >= 24000:
                        try:
                            audio_queue.put_nowait(bytes(buffer))
                        except asyncio.QueueFull:
                            pass
                    buffer.clear()
                while True:
                    message = await ws.receive()
                    if message['type'] == 'websocket.disconnect':
                        raise WebSocketDisconnect()
                    pcm = message.get('bytes')
                    if pcm is not None:
                        if len(pcm) != 4800:
                            raise ValueError('Invalid audio frame')
                        buffer.extend(pcm)
                        rms = np.sqrt(np.mean((np.frombuffer(pcm, dtype='<i2').astype(float) / 32768)**2))
                        silent = silent + 1 if rms < .012 else 0
                        if (silent >= 7 and len(buffer) >= 48000) or len(buffer) >= 384000:
                            enqueue()
                        await upstream.send(json.dumps({'type': 'session.input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode()}))
                    elif message.get('text') == 'stop':
                        enqueue()
                        # Let final words complete using the same drain protocol as the acceptance client.
                        for _ in range(30):
                            await upstream.send(json.dumps({'type': 'session.input_audio_buffer.append', 'audio': base64.b64encode(bytes(4800)).decode()}))
                            await asyncio.sleep(.1)
                        await asyncio.sleep(5)
                        return
                    else:
                        raise ValueError('Invalid message')
            sender = asyncio.create_task(send())
            receiver = asyncio.create_task(receive())
            try:
                done, _ = await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED, timeout=600)
                for task in done:
                    task.result()
            finally:
                sender.cancel()
                receiver.cancel()
                await asyncio.gather(sender, receiver, return_exceptions=True)
    finally:
        transcriber.cancel()
        await asyncio.gather(transcriber, return_exceptions=True)

@app.websocket('/api/rooms/{room_id}/ws')
async def room_socket(ws: WebSocket, room_id: str):
    origin = ws.headers.get('origin', '')
    if origin and origin.split('://', 1)[-1] != ws.headers.get('host'):
        await ws.close(code=1008)
        return
    room = rooms.get(room_id)
    if not room or len(room.peers) >= 32:
        await ws.close(code=1008)
        return
    await ws.accept()
    peer = Peer(ws)
    owner = False
    sending = None
    try:
        async with asyncio.timeout(10):
            auth = await ws.receive_json()
        owner = auth.get('role') == 'speaker'
        if owner and (not secrets.compare_digest(str(auth.get('owner', '')), room.owner) or any(r.active for r in rooms.values())):
            await ws.send_json({'type': 'error', 'message': 'Es läuft bereits eine Sitzung oder der Sprecherzugang ist ungültig.'})
            return
        if owner:
            room.active = True
        room.peers.add(peer)
        sending = asyncio.create_task(send_peer(peer))
        await peer.queue.put({'type': 'snapshot', 'text': room.text, 'original': room.original, 'status': 'connecting' if owner else ('live' if room.active else 'waiting')})
        await counts(room)
        if owner:
            try:
                await translation(room, ws)
            except WebSocketDisconnect:
                pass
            except Exception:
                await broadcast(room, {'type': 'error', 'message': 'Die Übersetzungsverbindung wurde beendet. Bitte nach einigen Sekunden erneut starten.'})
            finally:
                room.active = False
                await broadcast(room, {'type': 'status', 'status': 'ended'})
                await asyncio.sleep(.1)
        else:
            while True:
                await ws.receive_text()
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError):
        pass
    finally:
        room.peers.discard(peer)
        if sending:
            sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
        with contextlib.suppress(Exception):
            await ws.close()
        await counts(room)

@app.get('/local-ca.cer')
def certificate():
    return FileResponse('/app/static/local-ca.cer', media_type='application/x-x509-ca-cert', filename='Translate-Local-CA.cer')

app.mount('/', StaticFiles(directory=Path(__file__).parent / 'static', html=True), name='frontend')
