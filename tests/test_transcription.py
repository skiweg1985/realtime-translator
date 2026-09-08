"""Caption ordering, final correction, and independent failure regression checks."""
import asyncio
import unittest
from unittest.mock import patch
from transcription import Transcript
import main


class Captions(unittest.IsolatedAsyncioTestCase):
    def test_final_replaces_partial_and_preserves_turn_order(self):
        t = Transcript('Vorher.')
        for item in ('a', 'b'):
            t.update({'type': 'input_audio_buffer.committed', 'item_id': item})
        t.update({'type': 'conversation.item.input_audio_transcription.delta', 'item_id': 'a', 'delta': 'Guten'})
        t.update({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'b', 'transcript': 'Zweiter Satz.'})
        text = t.update({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'a', 'transcript': 'Guten Tag.'})
        self.assertEqual(text, 'Vorher. Guten Tag. Zweiter Satz.')
        self.assertEqual(t.update({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'a', 'transcript': 'Guten Tag.'}), text)

    async def test_provider_failure_is_notice_not_room_failure(self):
        room = main.Room(owner='test', language='en', source='de', active=True)
        events = []
        async def fail(*args):
            raise RuntimeError('private upstream detail')
        async def capture(room, event):
            events.append(event)
        with patch.object(main, 'stream_captions', fail), patch.object(main, 'broadcast', capture):
            await main.transcribe_audio(room, asyncio.Queue())
        self.assertTrue(room.active)
        self.assertEqual(events[0]['type'], 'notice')
        self.assertNotIn('private', str(events))

    def test_caption_history_is_bounded(self):
        t = Transcript('x' * 20000)
        text = t.update({'type': 'conversation.item.input_audio_transcription.delta', 'item_id': 'a', 'delta': 'y' * 22000})
        self.assertEqual(len(text), 20000)

class Streaming(unittest.IsolatedAsyncioTestCase):
    async def test_noise_reduction_is_sent_only_when_configured(self):
        import json
        from transcription import stream_captions
        for setting, expected in ((None, None), ('near_field', {'type': 'near_field'})):
            sent = []
            class Socket:
                async def send(self, raw):sent.append(json.loads(raw))
                async def recv(self):return json.dumps({'type': 'session.updated'})
                def __aiter__(self):return self
                async def __anext__(self):await asyncio.Event().wait()
            class Connection:
                async def __aenter__(self):return Socket()
                async def __aexit__(self, *args):pass
            q = asyncio.Queue()
            await q.put(None)
            with patch('transcription.websockets.connect', return_value=Connection()):
                await asyncio.wait_for(stream_captions(q, 'wss://test', 'test', 'alias', 'de', '', None, setting), 1)
            audio_input = sent[0]['session']['audio']['input']
            self.assertEqual(audio_input.get('noise_reduction'), expected)
            self.assertEqual(audio_input['transcription'], {'model': 'alias', 'languages': ['de']})

    async def test_stop_waits_for_final_caption_and_commits_short_tail(self):
        import json
        from transcription import stream_captions
        events = asyncio.Queue()
        await events.put({'type': 'session.updated'})
        sent = []
        class Socket:
            async def send(self, raw):
                event = json.loads(raw)
                sent.append(event)
                if event['type'] == 'session.update' and 'delay' in event['session']['audio']['input']['transcription']:
                    raise RuntimeError('Azure deployment rejects delay')
                if event['type'] == 'input_audio_buffer.commit':
                    await events.put({'type': 'input_audio_buffer.committed', 'item_id': 'one'})
                    await events.put({'type': 'conversation.item.input_audio_transcription.delta', 'item_id': 'one', 'delta': 'Hal'})
                    await events.put({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'one', 'transcript': 'Hallo.'})
            async def recv(self):
                return json.dumps(await events.get())
            def __aiter__(self):
                return self
            async def __anext__(self):
                return await self.recv()
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self, *args):pass
        q = asyncio.Queue()
        await q.put(bytes(4800))
        await q.put(None)
        output = []
        async def publish(text):output.append(text)
        with patch('transcription.websockets.connect', return_value=Connection()):
            await asyncio.wait_for(stream_captions(q, 'wss://test', 'test', 'alias', 'de', '', publish), 1)
        self.assertEqual(output, ['Hal', 'Hallo.'])
        self.assertEqual(sum(e['type'] == 'input_audio_buffer.append' for e in sent), 2)
        self.assertEqual(sum(e['type'] == 'input_audio_buffer.commit' for e in sent), 1)
