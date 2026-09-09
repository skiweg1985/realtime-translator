"""Single-worker, ephemeral rooms bridging browsers to LiteLLM Translate."""
import array
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
from channels import TranslationChannel

log = logging.getLogger(__name__)

MAX_LANGUAGES = 4

# Keep identical to `languages` in frontend/src/main.tsx (tests/test_rooms.py checks this).
LANGUAGES = {'de', 'en', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'uk', 'ru', 'ar', 'hi', 'id', 'vi', 'ja', 'ko', 'zh'}
URL = os.getenv('TRANSLATE_URL', 'wss://litellm-test.simplicity.ag/v1/realtime/translations?model=azure-live-translate')
KEY = os.getenv('TRANSLATE_KEY', '')

def speaker_pin_setting():
    value = os.getenv('SPEAKER_PIN', '0000')
    if len(value) != 4 or not value.isascii() or not value.isdigit():
        raise ValueError('SPEAKER_PIN must contain exactly four digits.')
    return value

SPEAKER_PIN = speaker_pin_setting()
# Original-language captions come from audio.input.transcription on the room language's channel; 'off' disables them.
TRANSCRIPTION_MODEL = os.getenv('TRANSLATE_TRANSCRIPTION_MODEL', 'gpt-realtime-whisper').strip()
if TRANSCRIPTION_MODEL.lower() == 'off':
    TRANSCRIPTION_MODEL = ''

NOISE_REDUCTION_MODES = ('off', 'near_field', 'far_field')

def noise_reduction_setting(name, default):
    """near_field: phone held close (our main case). far_field: room microphone. off: field omitted."""
    value = os.getenv(name, '').strip().lower() or default
    if value not in NOISE_REDUCTION_MODES:
        raise ValueError(f'{name} must be one of {", ".join(NOISE_REDUCTION_MODES)}, not {value!r}')
    return None if value == 'off' else value

TRANSLATE_NOISE_REDUCTION = noise_reduction_setting('TRANSLATE_NOISE_REDUCTION', 'near_field')

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
    retiring: list = field(default_factory=list)

rooms: dict[str, Room] = {}

app = FastAPI()

@app.get('/api/health')
def health():
    return {'ok': True, 'translation_configured': bool(KEY), 'transcription': 'configured' if TRANSCRIPTION_MODEL else 'unavailable',
            'noise_reduction': {'translation': TRANSLATE_NOISE_REDUCTION or 'off'}}

class NewRoom(BaseModel):
    language: str = 'en'
    source: str = 'de'
    pin: str = ''

@app.post('/api/rooms')
def create_room(body: NewRoom, request: Request):
    origin = request.headers.get('origin')
    if origin and origin.split('://', 1)[-1] != request.headers.get('host'):
        raise HTTPException(403, 'Origin rejected')
    if not secrets.compare_digest(body.pin.encode('utf-8'), SPEAKER_PIN.encode('utf-8')):
        raise HTTPException(403, 'Invalid speaker PIN')
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

def channel_status(room, language):
    channel = room.channels.get(language)
    return channel.status if channel else ('ended' if room.draining else 'waiting')


def ensure_channel(room, language):
    if not room.active or room.draining or language in room.channels:
        return
    async def publish(event):
        if event['type'] == 'original_delta':
            # Deltas already carry their spacing; the text goes to the speaker and every listener.
            room.original = (room.original + event['delta'])[-20000:]
            await broadcast(room, {'type': 'original', 'text': room.original})
            return
        if event['type'] == 'translation_delta':
            text = room.translations.get(language, '')
            if not channel.spoke and text and not text[-1].isspace() and not event['delta'][:1].isspace():
                text += ' '  # a channel opened mid-session continues after the previous channel's text
            channel.spoke = True
            room.translations[language] = (text + event['delta'])[-20000:]
            event = {'type': 'translation', 'text': room.translations[language]}
        await broadcast(room, event, language)
    channel = TranslationChannel(language, URL, KEY, publish, noise_reduction=room_noise_reduction(room),
                                 transcribe=TRANSCRIPTION_MODEL if language == room.language else None)
    room.channels[language] = channel
    channel.start()


def is_quiet(pcm):
    """Below normal speech level; the frontend maps an RMS of 5000 to full scale."""
    samples = array.array('h', pcm)
    return sum(s * s for s in samples) / len(samples) < 400 * 400


async def swap_channels(room):
    """Reopen every translation channel with the room's current noise setting.

    Listeners keep their connection: the new channel takes the microphone from now on, the
    old one drains its last sentence and may only pass audio and text, never a status."""
    async with room.lock:
        for language, old in list(room.channels.items()):
            del room.channels[language]
            ensure_channel(room, language)
            room.retiring.append(asyncio.create_task(Handover(old, room.channels[language]).run()))


class Handover:
    """Hold the new channel's output until the old channel has finished its last sentence."""
    def __init__(self, old, new):
        self.old = old
        self.buffer = []
        self.released = False
        self.last_tail = asyncio.get_running_loop().time()
        forward_old, self.forward_new = old.publish, new.publish
        async def tail(event):
            if event['type'] in ('audio', 'translation_delta', 'original_delta'):
                self.last_tail = asyncio.get_running_loop().time()
                await forward_old(event)
        async def gated(event):
            if self.released or event['type'] not in ('audio', 'translation_delta', 'original_delta'):
                await self.forward_new(event)
            else:
                self.buffer.append(event)
        old.publish, new.publish = tail, gated
        old.feed(None)

    async def run(self):
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            # The tail needs a moment to appear; then one quiet second means the sentence is over.
            while not self.old.task.done() and loop.time() - started < 10:
                if loop.time() - started >= 2 and loop.time() - self.last_tail >= 1:
                    break
                await asyncio.sleep(.1)
            while self.buffer:
                await self.forward_new(self.buffer.pop(0))
            self.released = True
            async with asyncio.timeout(12):
                await asyncio.gather(self.old.task, return_exceptions=True)
        finally:
            self.released = True
            await self.old.close()


async def prune_channels(room):
    # Caller holds room.lock. Keep the slot occupied until its upstream is closed.
    wanted = {p.language for p in room.peers if p.language}
    if room.active and not room.draining:
        wanted.add(room.language)  # carries the original-language captions while speaking
    for language in list(room.channels):
        if language not in wanted:
            await room.channels[language].close()
            del room.channels[language]


async def subscribe(room, peer, language, subscription):
    if language not in LANGUAGES or type(subscription) is not int or not 0 <= subscription <= 2147483647:
        raise ValueError('Invalid subscription')
    async with room.lock:
        wanted = {p.language for p in room.peers if p is not peer and p.language}
        if len(wanted | {language, room.language}) > MAX_LANGUAGES:
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
    async with room.lock:
        room.draining = False
        for language in {p.language for p in room.peers if p.language} | {room.language}:
            ensure_channel(room, language)
    await speaker.queue.put({'type': 'status', 'status': 'live'})
    swap = None  # frames waited for a pause since the speaker changed a setting
    quiet = 0
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
                    if swap is not None:
                        # Swap in a pause of half a second, or after five seconds at the latest.
                        swap += 1
                        quiet = quiet + 1 if is_quiet(pcm) else 0
                        if quiet >= 5 or swap >= 50:
                            swap = None
                            await swap_channels(room)
                    for language, channel in list(room.channels.items()):
                        if channel.feed(pcm) is False:
                            await broadcast(room, {'type': 'status', 'status': 'error'}, language)
                            await broadcast(room, {'type': 'error', 'message': 'Diese Übersetzung kommt nicht nach. Bitte erneut verbinden.'}, language)
                elif message.get('text') == 'stop':
                    break
                elif message.get('text'):
                    update = json.loads(message['text'])
                    if update.get('type') != 'settings':
                        raise ValueError('Invalid message')
                    room.noise_reduction = chosen_noise_reduction(update.get('noise_reduction'))
                    swap, quiet = 0, 0
                else:
                    raise ValueError('Invalid message')
    except TimeoutError:
        pass
    finally:
        async with room.lock:
            room.draining = True
        try:
            for channel in list(room.channels.values()):
                channel.feed(None)
            try:
                async with asyncio.timeout(22):
                    await asyncio.gather(*[c.task for c in room.channels.values()], return_exceptions=True)
            except TimeoutError:
                pass
        finally:
            async with room.lock:
                for channel in room.channels.values():
                    await channel.close()
                room.channels.clear()
            for task in room.retiring:
                task.cancel()
            await asyncio.gather(*room.retiring, return_exceptions=True)
            room.retiring.clear()

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
