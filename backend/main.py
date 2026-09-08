"""Single-worker, ephemeral rooms bridging browsers to LiteLLM Translate."""
import asyncio
import contextlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from transcription import stream_captions
from channels import TranslationChannel

log = logging.getLogger(__name__)

MAX_LANGUAGES = 4

# Keep identical to `languages` in frontend/src/main.tsx (tests/test_rooms.py checks this).
LANGUAGES = {'de', 'en', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'uk', 'ru', 'ar', 'hi', 'id', 'vi', 'ja', 'ko', 'zh'}
URL = os.getenv('TRANSLATE_URL', 'wss://litellm-test.simplicity.ag/v1/realtime/translations?model=azure-live-translate')
KEY = os.getenv('TRANSLATE_KEY', '')
TRANSCRIBE_URL = os.getenv('TRANSCRIBE_URL', 'wss://litellm-test.simplicity.ag/v1/realtime?model=azure-live-transcribe&intent=transcription')
TRANSCRIBE_MODEL = os.getenv('TRANSCRIBE_MODEL', 'azure-live-transcribe')
TRANSCRIBE_KEY = os.getenv('TRANSCRIBE_KEY', '')

NOISE_REDUCTION_MODES = ('off', 'near_field', 'far_field')

def noise_reduction_setting(name, default):
    """near_field: phone held close (our main case). far_field: room microphone. off: field omitted."""
    value = os.getenv(name, '').strip().lower() or default
    if value not in NOISE_REDUCTION_MODES:
        raise ValueError(f'{name} must be one of {", ".join(NOISE_REDUCTION_MODES)}, not {value!r}')
    return None if value == 'off' else value

# The LiteLLM translation route rejects any audio.input field, so translation defaults to off.
TRANSLATE_NOISE_REDUCTION = noise_reduction_setting('TRANSLATE_NOISE_REDUCTION', 'off')
TRANSCRIBE_NOISE_REDUCTION = noise_reduction_setting('TRANSCRIBE_NOISE_REDUCTION', 'near_field')

def chosen_noise_reduction(value):
    """The speaker's per-session choice; anything unknown means the configured default."""
    return value if value in NOISE_REDUCTION_MODES else None

def room_noise_reduction(room):
    mode = room.noise_reduction or TRANSLATE_NOISE_REDUCTION or 'off'
    return None if mode == 'off' else mode

@dataclass(eq=False)
class Peer:
    ws: WebSocket
    language: str | None = None
    subscription: int = 0
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=100))

@dataclass
class Room:
    owner: str
    language: str
    source: str
    created: float = field(default_factory=time.monotonic)
    active: bool = False
    peers: set = field(default_factory=set)
    translations: dict = field(default_factory=dict)
    channels: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    draining: bool = False
    original: str = ''
    code: str = ''
    noise_reduction: str | None = None

rooms: dict[str, Room] = {}

app = FastAPI()

@app.get('/api/health')
def health():
    return {'ok': True, 'translation_configured': bool(KEY), 'transcription': 'configured' if TRANSCRIBE_KEY else 'unavailable',
            'noise_reduction': {'translation': TRANSLATE_NOISE_REDUCTION or 'off', 'transcription': TRANSCRIBE_NOISE_REDUCTION or 'off'}}

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
    code = new_code()
    rooms[room_id] = Room(owner=owner, language=body.language, source=body.source, code=code)
    return {'id': room_id, 'owner': owner, 'code': code}

class EndRoom(BaseModel):
    owner: str = ''

@app.post('/api/rooms/{room_id}/end')
async def end_room(room_id: str, body: EndRoom, request: Request):
    """The speaker ends the session for everyone: listeners get a final status, the room disappears."""
    origin = request.headers.get('origin')
    if origin and origin.split('://', 1)[-1] != request.headers.get('host'):
        raise HTTPException(403, 'Origin rejected')
    room = rooms.get(room_id)
    if not room or not secrets.compare_digest(str(body.owner), room.owner):
        raise HTTPException(404, 'Diese Sitzung ist nicht mehr verfügbar.')
    if room.active:
        raise HTTPException(409, 'Bitte zuerst die Übertragung stoppen.')
    del rooms[room_id]
    await broadcast(room, {'type': 'status', 'status': 'closed'})
    await asyncio.sleep(.1)
    for peer in list(room.peers):
        with contextlib.suppress(Exception):
            await peer.ws.close(code=1000)
    return {'ok': True}

def new_code():
    """Four spoken digits, unique among current rooms, never starting with zero."""
    used = {room.code for room in rooms.values()}
    for _ in range(50):
        code = str(secrets.randbelow(9000) + 1000)
        if code not in used:
            return code
    raise HTTPException(429, 'Zu viele Sitzungen. Bitte später erneut versuchen.')

@app.get('/api/rooms/by-code/{code}')
def room_by_code(code: str):
    for room_id, room in rooms.items():
        if room.code == code.strip():
            return {'id': room_id}
    raise HTTPException(404, 'Keine Sitzung mit diesem Code.')

@app.get('/api/rooms/{room_id}')
def room_info(room_id: str):
    room = rooms.get(room_id)
    if not room:
        raise HTTPException(404, 'Diese Sitzung ist nicht mehr verfügbar.')
    return {'language': room.language, 'source': room.source, 'active': room.active, 'code': room.code,
            'languages': sorted(LANGUAGES), 'max_languages': MAX_LANGUAGES}

async def broadcast(room, event, language=None):
    for peer in list(room.peers):
        if language is not None and peer.language != language:
            continue
        try:
            peer.queue.put_nowait({**event, 'language': language, 'subscription': peer.subscription} if language else event)
        except asyncio.QueueFull:
            room.peers.discard(peer)
            await peer.ws.close(code=1013, reason='Verbindung zu langsam. Bitte erneut beitreten.')

async def send_peer(peer):
    while True:
        event = await peer.queue.get()
        if event.get('language') and event['type'] != 'subscription_rejected' and (event['language'] != peer.language or event.get('subscription') != peer.subscription):
            continue
        await peer.ws.send_json(event)

async def counts(room):
    await broadcast(room, {'type': 'listeners', 'count': max(0, len(room.peers) - int(room.active))})

async def transcribe_audio(room, queue):
    async def publish(text):
        room.original = text
        await broadcast(room, {'type': 'original', 'text': text})
    try:
        await stream_captions(queue, TRANSCRIBE_URL, TRANSCRIBE_KEY, TRANSCRIBE_MODEL,
                              room.source, room.original, publish, TRANSCRIBE_NOISE_REDUCTION)
    except Exception as exc:
        log.warning('Captions failed: %s', exc)
        await broadcast(room, {'type': 'notice', 'message': 'Cloud-Spracherkennung ist momentan nicht verfügbar. Die Übersetzung läuft weiter.'})

def channel_status(room, language):
    channel = room.channels.get(language)
    return channel.status if channel else ('ended' if room.draining else 'waiting')


def ensure_channel(room, language):
    if not room.active or room.draining or language in room.channels:
        return
    async def publish(event):
        if event['type'] == 'translation_delta':
            room.translations[language] = (room.translations.get(language, '') + event['delta'])[-20000:]
            event = {'type': 'translation', 'text': room.translations[language]}
        await broadcast(room, event, language)
    channel = TranslationChannel(language, URL, KEY, publish, noise_reduction=room_noise_reduction(room))
    room.channels[language] = channel
    channel.start()


async def prune_channels(room):
    # Caller holds room.lock. Keep the slot occupied until its upstream is closed.
    wanted = {p.language for p in room.peers if p.language}
    for language in list(room.channels):
        if language not in wanted:
            await room.channels[language].close()
            del room.channels[language]


async def subscribe(room, peer, language, subscription):
    if language not in LANGUAGES or type(subscription) is not int or not 0 <= subscription <= 2147483647:
        raise ValueError('Invalid subscription')
    async with room.lock:
        wanted = {p.language for p in room.peers if p is not peer and p.language}
        if len(wanted | {language}) > MAX_LANGUAGES:
            await peer.queue.put({'type': 'subscription_rejected', 'subscription': subscription,
                                  'language': peer.language, 'active_subscription': peer.subscription,
                                  'text': room.translations.get(peer.language, ''), 'status': channel_status(room, peer.language), 'message': 'Es sind bereits vier Sprachen belegt. Bitte eine bereits verwendete Sprache wählen.'})
            return False
        peer.language = language
        peer.subscription = subscription
        await prune_channels(room)
        # Explicit resubscription retries a failed channel for all its listeners.
        channel = room.channels.get(language)
        if channel and channel.task.done():
            await channel.close()
            del room.channels[language]
        ensure_channel(room, language)
        await peer.queue.put({'type': 'snapshot', 'language': language, 'subscription': subscription,
                              'text': room.translations.get(language, ''), 'original': room.original,
                              'status': channel_status(room, language)})
        return True


async def translation(room, ws, speaker):
    audio_queue = asyncio.Queue(maxsize=100)
    transcriber = asyncio.create_task(transcribe_audio(room, audio_queue))
    async with room.lock:
        room.draining = False
        for language in {p.language for p in room.peers if p.language}:
            ensure_channel(room, language)
    await speaker.queue.put({'type': 'status', 'status': 'live'})
    try:
        async with asyncio.timeout(600):
            while True:
                message = await ws.receive()
                if message['type'] == 'websocket.disconnect':
                    raise WebSocketDisconnect()
                pcm = message.get('bytes')
                if pcm is not None:
                    if len(pcm) != 4800:
                        raise ValueError('Invalid audio frame')
                    if not transcriber.done():
                        try:
                            audio_queue.put_nowait(pcm)
                        except asyncio.QueueFull:
                            transcriber.cancel()
                            await speaker.queue.put({'type': 'notice', 'message': 'Cloud-Spracherkennung kommt nicht nach. Bitte die Sitzung erneut starten.'})
                    for language, channel in list(room.channels.items()):
                        if channel.feed(pcm) is False:
                            await broadcast(room, {'type': 'status', 'status': 'error'}, language)
                            await broadcast(room, {'type': 'error', 'message': 'Diese Übersetzung kommt nicht nach. Bitte erneut verbinden.'}, language)
                elif message.get('text') == 'stop':
                    break
                else:
                    raise ValueError('Invalid message')
    except TimeoutError:
        pass
    finally:
        async with room.lock:
            room.draining = True
        try:
            if not transcriber.done():
                try:
                    audio_queue.put_nowait(None)
                except asyncio.QueueFull:
                    transcriber.cancel()
            for channel in list(room.channels.values()):
                channel.feed(None)
            tasks = [transcriber] + [c.task for c in room.channels.values()]
            try:
                async with asyncio.timeout(22):
                    await asyncio.gather(*tasks, return_exceptions=True)
            except TimeoutError:
                pass
        finally:
            transcriber.cancel()
            await asyncio.gather(transcriber, return_exceptions=True)
            async with room.lock:
                for channel in room.channels.values():
                    await channel.close()
                room.channels.clear()

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
            room.noise_reduction = chosen_noise_reduction(auth.get('noise_reduction'))
        room.peers.add(peer)
        sending = asyncio.create_task(send_peer(peer))
        if owner:
            await peer.queue.put({'type': 'snapshot', 'text': '', 'original': room.original, 'status': 'connecting'})
        elif not await subscribe(room, peer, auth.get('language', room.language), auth.get('subscription', 0)):
            await asyncio.sleep(.1)
            return
        await counts(room)
        if owner:
            try:
                await translation(room, ws, peer)
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
                message = await ws.receive_json()
                if message.get('type') != 'subscribe':
                    raise ValueError('Invalid listener message')
                await subscribe(room, peer, message.get('language'), message.get('subscription'))
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError):
        pass
    finally:
        room.peers.discard(peer)
        async with room.lock:
            await prune_channels(room)
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
