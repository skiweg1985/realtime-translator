"""One bounded upstream translation connection per selected target language."""
import asyncio
import base64
import contextlib
import json
import logging

import websockets

log = logging.getLogger(__name__)

# A dropped upstream is usually short-lived, so try twice more before the language counts as failed.
RETRY_DELAYS = (1, 3)
# After that the failure is reported, but the channel keeps trying at this pace and finally once a
# minute. An outage of a few minutes must not cost the rest of the session, and a provider that is
# down must not be hammered: this is one attempt per language, however many listeners are waiting.
RECOVERY_DELAYS = (15, 30, 60)
# A realtime service that needs longer than this for the handshake is unusable anyway, and every
# second here is spent three times over before the speaker learns that nothing is being translated.
OPEN_TIMEOUT = 8


def upstream_message(event):
    error = event.get('error') or {}
    return str(error.get('message') or error.get('type') or 'unknown error')[:200]


async def probe(url, headers, timeout, language='en'):
    """Open and close a translation session to see whether the provider answers at all.

    Nothing but the handshake happens, so this checks the route, the key and the model without
    sending any audio. Raises whatever went wrong; the caller decides what to tell the user."""
    async with asyncio.timeout(timeout):
        async with websockets.connect(url, additional_headers=headers, proxy=None,
                                      open_timeout=timeout, close_timeout=2, max_size=65536) as ws:
            await ws.send(json.dumps({'type': 'session.update',
                                      'session': {'audio': {'output': {'language': language}}}}))
            while True:
                event = json.loads(await ws.recv())
                if event.get('type') == 'error':
                    raise RuntimeError('Translation probe rejected: ' + upstream_message(event))
                if event.get('type') == 'session.updated':
                    return


class TranslationChannel:
    def __init__(self, language, url, key, publish, noise_reduction=None, transcribe=None, headers=None):
        self.language = language
        self.url = url
        self.headers = headers if headers is not None else {'Authorization': 'Bearer ' + key}
        self.publish = publish
        # None omits the noise reduction setting from session.update.
        self.noise_reduction = noise_reduction
        # Model name for audio.input.transcription; only one channel per room carries the original text.
        self.transcribe = transcribe
        self.queue = asyncio.Queue(maxsize=100)
        self.status = 'connecting'
        self.spoke = False
        self.task = None
        # Set as soon as the drain frame is queued; from then on a broken upstream is not retried.
        self.finishing = False
        # A reported outage. Unlike status it stays true across further attempts until one succeeds,
        # so the speaker keeps the warning while a retry is still connecting.
        self.failed = False
        # Cuts the wait between attempts short when a listener or the speaker asks for a retry.
        self.wake = asyncio.Event()

    def start(self):
        self.task = asyncio.create_task(self.run())

    def feed(self, pcm):
        if self.task.done():
            return
        if pcm is None:
            self.finishing = True
        try:
            self.queue.put_nowait(pcm)
        except asyncio.QueueFull:
            if self.status != 'live':
                # Nothing is reading while we connect, and stale audio is worthless anyway.
                with contextlib.suppress(asyncio.QueueEmpty):
                    self.queue.get_nowait()
                self.queue.put_nowait(pcm)
                return True
            # A slow language must not stall the microphone or other languages.
            self.task.cancel()
            self.status = 'error'
            return False
        return True

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    def retry_now(self):
        """Ask for the next attempt right away instead of waiting out the current delay."""
        self.wake.set()

    async def wait(self, delay):
        self.wake.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.wake.wait(), delay)

    def delays(self):
        """One wait per further attempt; the channel never stops trying while the room wants it."""
        yield from RETRY_DELAYS
        yield from RECOVERY_DELAYS
        while True:
            yield RECOVERY_DELAYS[-1]

    async def run(self):
        """Keep the language usable: quick retries first, then a reported outage that heals itself."""
        attempt, schedule = 0, self.delays()
        while True:
            try:
                await self.session()
                self.status = 'ended'
                await self.publish({'type': 'status', 'status': 'ended'})
                return
            except Exception as exc:
                failure = exc
            if self.finishing:
                break
            if self.status == 'live':
                # The upstream worked and then dropped, so this is a fresh outage: start over with
                # the quick retries, and let a lasting one be reported again.
                attempt, schedule = 0, self.delays()
            delay = next(schedule)
            if attempt == len(RETRY_DELAYS):
                await self.report_failure(failure)
            else:
                log.warning('Translation channel %s retries in %ss: %s', self.language, delay, failure)
                if self.failed:
                    # Back from the attempt to the outage: listeners must not read 'connecting'
                    # through minutes of waiting.
                    self.status = 'error'
                    await self.publish({'type': 'status', 'status': 'error'})
            attempt += 1
            await self.wait(delay)
            # Listeners see 'connecting' for the attempt itself, not for the wait before it.
            self.status = 'connecting'
            # The next upstream starts a new sentence after the text so far.
            self.spoke = False
            await self.publish({'type': 'status', 'status': 'connecting'})
        if not self.failed:
            await self.report_failure(failure)

    async def report_failure(self, failure):
        """Say once that the language is down. Further attempts keep running in the background."""
        log.warning('Translation channel %s failed: %s', self.language, failure)
        self.failed = True
        self.status = 'error'
        await self.publish({'type': 'status', 'status': 'error'})
        await self.publish({'type': 'error', 'code': 'channel_unavailable',
                            'message': 'Diese Übersetzung ist momentan nicht verfügbar. Es wird weiter versucht.'})

    async def session(self):
        async with websockets.connect(self.url, additional_headers=self.headers,
                                      proxy=None, open_timeout=OPEN_TIMEOUT, close_timeout=2, max_size=1048576) as ws:
            session = {'audio': {'output': {'language': self.language}}}
            audio_input = {}
            if self.noise_reduction:
                audio_input['noise_reduction'] = {'type': self.noise_reduction}
            if self.transcribe:
                audio_input['transcription'] = {'model': self.transcribe}
            if audio_input:
                session['audio']['input'] = audio_input
            await ws.send(json.dumps({'type': 'session.update', 'session': session}))
            async with asyncio.timeout(20):
                while True:
                    event = json.loads(await ws.recv())
                    if event.get('type') == 'error':
                        raise RuntimeError('Translation session rejected: ' + upstream_message(event))
                    if event.get('type') == 'session.updated':
                        break
            # Audio that piled up while connecting is stale; only the drain signal must survive.
            while not self.queue.empty():
                self.queue.get_nowait()
            if self.finishing:
                self.queue.put_nowait(None)
            self.status = 'live'
            self.failed = False
            await self.publish({'type': 'status', 'status': 'live'})

            async def receive():
                async for raw in ws:
                    event = json.loads(raw)
                    kind = event.get('type')
                    if kind == 'session.output_audio.delta':
                        await self.publish({'type': 'audio', 'delta': event['delta']})
                    elif kind == 'session.output_transcript.delta':
                        await self.publish({'type': 'translation_delta', 'delta': event['delta']})
                    elif kind == 'session.input_transcript.delta':
                        await self.publish({'type': 'original_delta', 'delta': event['delta']})
                    elif kind == 'error':
                        raise RuntimeError('Translation stream failed: ' + upstream_message(event))
                raise RuntimeError('Translation stream closed')

            async def send():
                while True:
                    pcm = await self.queue.get()
                    if pcm is None:
                        # Preserve the established final-audio drain protocol.
                        for _ in range(30):
                            await ws.send(json.dumps({'type': 'session.input_audio_buffer.append',
                                                      'audio': base64.b64encode(bytes(4800)).decode()}))
                            await asyncio.sleep(.1)
                        await asyncio.sleep(5)
                        return
                    await ws.send(json.dumps({'type': 'session.input_audio_buffer.append',
                                              'audio': base64.b64encode(pcm).decode()}))
            sender = asyncio.create_task(send())
            receiver = asyncio.create_task(receive())
            try:
                done, _ = await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                sender.cancel()
                receiver.cancel()
                await asyncio.gather(sender, receiver, return_exceptions=True)
