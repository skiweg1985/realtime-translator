"""Exercise language subscriptions and routing without paid provider calls."""
import asyncio
import unittest
from unittest.mock import patch

import main


class Socket:
    async def close(self, **kwargs):pass


class FakeChannel:
    instances = []
    def __init__(self, language, url, key, publish):
        self.language = language
        self.publish = publish
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
