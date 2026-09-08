"""Bounded cloud captions, independent of the translated audio connection."""
import asyncio
import base64
import json

import websockets

from channels import upstream_message


class Transcript:
    def __init__(self, previous=''):
        self.previous = previous
        self.items = {}

    def update(self, event):
        kind = event.get('type', '')
        item = event.get('item_id')
        if not item:
            return None
        if kind == 'input_audio_buffer.committed':
            self.items.setdefault(item, '')
            return None
        if kind.endswith('input_audio_transcription.delta'):
            self.items[item] = self.items.get(item, '') + event['delta']
        elif kind.endswith('input_audio_transcription.completed'):
            self.items[item] = event['transcript']
        else:
            return None
        # A ten-minute session commits at most 200 turns; bound individual text too.
        self.items[item] = self.items[item][-20000:]
        return ' '.join([self.previous] + list(self.items.values())).strip()[-20000:]


async def stream_captions(queue, url, key, model, source, previous, publish, noise_reduction=None):
    """Consume PCM frames and a final None marker; never hide a broken stream."""
    transcript = Transcript(previous)
    pending = 0
    drained = asyncio.Event()
    drained.set()
    async with websockets.connect(url, additional_headers={'Authorization': 'Bearer ' + key},
                                  proxy=None, open_timeout=15, close_timeout=2, max_size=1048576) as ws:
        audio_input = {
            'format': {'type': 'audio/pcm', 'rate': 24000},
            'transcription': {'model': model, 'languages': [source]},
            'turn_detection': None,
        }
        if noise_reduction:
            audio_input['noise_reduction'] = {'type': noise_reduction}
        await ws.send(json.dumps({'type': 'session.update', 'session': {
            'type': 'transcription', 'audio': {'input': audio_input}}}))
        async with asyncio.timeout(20):
            while True:
                event = json.loads(await ws.recv())
                if event.get('type') == 'error':
                    raise RuntimeError('Caption session rejected: ' + upstream_message(event))
                if event.get('type') == 'session.updated':
                    break

        async def receive():
            nonlocal pending
            async for raw in ws:
                event = json.loads(raw)
                kind = event.get('type', '')
                if kind == 'error' or kind.endswith('input_audio_transcription.failed'):
                    raise RuntimeError('Caption stream failed')
                text = transcript.update(event)
                if text is not None:
                    await publish(text)
                if kind.endswith('input_audio_transcription.completed'):
                    pending -= 1
                    if pending == 0:
                        drained.set()
            raise RuntimeError('Caption stream closed')

        async def send():
            nonlocal pending
            frames = 0
            async def commit():
                nonlocal pending
                pending += 1
                drained.clear()
                await ws.send(json.dumps({'type': 'input_audio_buffer.commit'}))
            while True:
                pcm = await queue.get()
                if pcm is None:
                    if frames:
                        # Pad very short final turns to exceed the minimum commit duration.
                        await ws.send(json.dumps({'type': 'input_audio_buffer.append',
                                                  'audio': base64.b64encode(bytes(4800)).decode()}))
                        await commit()
                    await asyncio.wait_for(drained.wait(), 10)
                    return
                await ws.send(json.dumps({'type': 'input_audio_buffer.append',
                                          'audio': base64.b64encode(pcm).decode()}))
                frames += 1
                if frames == 30:
                    await commit()
                    frames = 0

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
