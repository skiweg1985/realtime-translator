"""One bounded upstream translation connection per selected target language."""
import asyncio
import base64
import json

import websockets


class TranslationChannel:
    def __init__(self, language, url, key, publish):
        self.language = language
        self.url = url
        self.key = key
        self.publish = publish
        self.queue = asyncio.Queue(maxsize=100)
        self.status = 'connecting'
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.run())

    def feed(self, pcm):
        if self.task.done():
            return
        try:
            self.queue.put_nowait(pcm)
        except asyncio.QueueFull:
            # A slow language must not stall the microphone or other languages.
            self.task.cancel()
            self.status = 'error'
            return False
        return True

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def run(self):
        sender = receiver = None
        try:
            async with websockets.connect(self.url, additional_headers={'Authorization': 'Bearer ' + self.key},
                                          proxy=None, open_timeout=15, close_timeout=2, max_size=1048576) as ws:
                await ws.send(json.dumps({'type': 'session.update', 'session': {
                    'audio': {'output': {'language': self.language}}}}))
                async with asyncio.timeout(20):
                    while True:
                        event = json.loads(await ws.recv())
                        if event.get('type') == 'error':
                            raise RuntimeError('Translation session rejected')
                        if event.get('type') == 'session.updated':
                            break
                self.status = 'live'
                await self.publish({'type': 'status', 'status': 'live'})

                async def receive():
                    async for raw in ws:
                        event = json.loads(raw)
                        kind = event.get('type')
                        if kind == 'session.output_audio.delta':
                            await self.publish({'type': 'audio', 'delta': event['delta']})
                        elif kind == 'session.output_transcript.delta':
                            await self.publish({'type': 'translation_delta', 'delta': event['delta']})
                        elif kind == 'error':
                            raise RuntimeError('Translation stream failed')
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
                self.status = 'ended'
                await self.publish({'type': 'status', 'status': 'ended'})
        except Exception:
            self.status = 'error'
            await self.publish({'type': 'status', 'status': 'error'})
            await self.publish({'type': 'error', 'message': 'Diese Übersetzung ist momentan nicht verfügbar. Bitte erneut verbinden oder eine andere Sprache wählen.'})
