"""Exercise language subscriptions and routing without paid provider calls."""
import asyncio
import unittest
from unittest.mock import patch

import main


class Socket:
    async def close(self, **kwargs):pass


class FakeChannel:
    instances = []
    def __init__(self, language, url, key, publish, noise_reduction=None):
        self.language = language
        self.publish = publish
        self.noise_reduction = noise_reduction
        self.status = 'live'
        self.task = None
        self.closed = False
        self.instances.append(self)
    def start(self):
        self.task = asyncio.create_task(asyncio.Event().wait())
    async def close(self):
        self.closed = True
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


class Channels(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.room = main.Room(owner='owner', source='de', language='en', active=True)
        FakeChannel.instances = []
        self.patcher = patch.object(main, 'TranslationChannel', FakeChannel)
        self.patcher.start()
    async def asyncTearDown(self):
        for c in self.room.channels.values():await c.close()
        self.patcher.stop()
    async def join(self, language):
        peer = main.Peer(Socket())
        self.room.peers.add(peer)
        self.assertTrue(await main.subscribe(self.room, peer, language, 1))
        peer.queue.get_nowait()
        return peer

    async def test_same_language_shares_one_channel_and_events_are_scoped(self):
        a = await self.join('en');b = await self.join('en');c = await self.join('fr')
        self.assertEqual(len(self.room.channels), 2)
        await self.room.channels['en'].publish({'type':'audio','delta':'english'})
        for peer in [a,b]:
            e = peer.queue.get_nowait()
            self.assertEqual((e['language'],e['subscription'],e['delta']),('en',1,'english'))
        self.assertTrue(c.queue.empty())
        await self.room.channels['fr'].publish({'type':'error','message':'French unavailable'})
        self.assertTrue(a.queue.empty())
        self.assertEqual(c.queue.get_nowait()['type'],'error')

    async def test_four_languages_limit_preserves_existing_subscription(self):
        peers = [await self.join(l) for l in ['en','fr','es','it']]
        extra = await self.join('en')
        self.assertFalse(await main.subscribe(self.room, extra, 'pl', 2))
        self.assertEqual((extra.language,extra.subscription),('en',1))
        self.assertEqual(extra.queue.get_nowait()['type'],'subscription_rejected')
        self.assertEqual(len(self.room.channels),4)
        # The only French listener may replace that channel even at capacity.
        old = self.room.channels['fr']
        self.assertTrue(await main.subscribe(self.room, peers[1], 'pl', 2))
        self.assertTrue(old.closed)
        self.assertEqual(set(self.room.channels),{'en','es','it','pl'})

    async def test_switch_clears_old_language_queue_and_releases_last_slot(self):
        a = await self.join('en');old = self.room.channels['en']
        await old.publish({'type':'audio','delta':'stale'})
        await main.subscribe(self.room,a,'fr',2)
        self.assertTrue(old.closed)
        sent = []
        async def send(event):
            sent.append(event)
            raise RuntimeError('stop sender after first delivered event')
        a.ws.send_json = send
        with self.assertRaisesRegex(RuntimeError,'stop sender'):
            await main.send_peer(a)
        self.assertEqual(len(sent),1)
        self.assertEqual((sent[0]['type'],sent[0]['language']),('snapshot','fr'))
        self.room.peers.remove(a)
        await main.prune_channels(self.room)
        self.assertFalse(self.room.channels)

    async def test_speaker_choice_reaches_every_channel(self):
        self.room.noise_reduction = 'far_field'
        await self.join('en');await self.join('fr')
        self.assertEqual([c.noise_reduction for c in FakeChannel.instances], ['far_field', 'far_field'])
        self.assertIsNone(main.chosen_noise_reduction('loud'))
        self.assertIsNone(main.chosen_noise_reduction(None))
        self.assertEqual(main.chosen_noise_reduction('near_field'), 'near_field')
        self.room.noise_reduction = 'off'
        self.assertIsNone(main.room_noise_reduction(self.room))
        self.room.noise_reduction = None
        with patch.object(main, 'TRANSLATE_NOISE_REDUCTION', 'near_field'):
            self.assertEqual(main.room_noise_reduction(self.room), 'near_field')

    async def test_waiting_room_does_not_open_upstreams(self):
        self.room.active = False
        await self.join('fr')
        self.assertFalse(FakeChannel.instances)

    async def test_invalid_language_never_changes_subscription(self):
        peer = await self.join('en')
        with self.assertRaises(ValueError):await main.subscribe(self.room,peer,'xx',2)
        self.assertEqual(peer.language,'en')

    async def test_history_is_separate_per_language(self):
        await self.join('en');await self.join('fr')
        await self.room.channels['en'].publish({'type':'translation_delta','delta':'Hello'})
        await self.room.channels['fr'].publish({'type':'translation_delta','delta':'Bonjour'})
        self.assertEqual(self.room.translations,{'en':'Hello','fr':'Bonjour'})

class SessionUpdate(unittest.IsolatedAsyncioTestCase):
    async def open_channel(self, reply, **kwargs):
        import json
        from channels import TranslationChannel
        sent = []
        published = []
        class Socket:
            async def send(self, raw):sent.append(json.loads(raw))
            async def recv(self):return json.dumps(reply)
            def __aiter__(self):return self
            async def __anext__(self):raise StopAsyncIteration
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self, *args):pass
        async def publish(event):published.append(event)
        with patch('channels.websockets.connect', return_value=Connection()):
            channel = TranslationChannel('fr', 'wss://test', 'test', publish, **kwargs)
            channel.start()
            await asyncio.wait_for(channel.task, 2)
        self.assertEqual(sent[0]['type'], 'session.update')
        return sent[0]['session'], published

    async def test_noise_reduction_is_sent_only_when_configured(self):
        session, _ = await self.open_channel({'type': 'session.updated'})
        self.assertEqual(session, {'audio': {'output': {'language': 'fr'}}})
        session, _ = await self.open_channel({'type': 'session.updated'}, noise_reduction='far_field')
        self.assertEqual(session['audio'], {'input': {'noise_reduction': {'type': 'far_field'}}, 'output': {'language': 'fr'}})

    async def test_rejected_session_logs_upstream_detail_but_tells_listeners_nothing_private(self):
        rejection = {'type': 'error', 'error': {'type': 'translation_error', 'message': 'Additional input models are not allowed.'}}
        with self.assertLogs('channels', level='WARNING') as logs:
            _, published = await self.open_channel(rejection, noise_reduction='near_field')
        self.assertIn('Additional input models', logs.output[0])
        self.assertEqual([e['type'] for e in published], ['status', 'error'])
        self.assertNotIn('Additional', str(published))


class Backpressure(unittest.IsolatedAsyncioTestCase):
    async def test_slow_language_does_not_cancel_another_channel(self):
        from channels import TranslationChannel
        async def publish(event):pass
        slow = TranslationChannel('en','wss://test','test',publish)
        fast = TranslationChannel('fr','wss://test','test',publish)
        slow.task = asyncio.create_task(asyncio.Event().wait())
        fast.task = asyncio.create_task(asyncio.Event().wait())
        try:
            for _ in range(100):self.assertTrue(slow.feed(bytes(4800)))
            self.assertFalse(slow.feed(bytes(4800)))
            self.assertTrue(fast.feed(bytes(4800)))
            self.assertFalse(fast.task.done())
            self.assertEqual(slow.status,'error')
        finally:
            await slow.close();await fast.close()
