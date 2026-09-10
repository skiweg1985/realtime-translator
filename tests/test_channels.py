"""Exercise language subscriptions and routing without paid provider calls."""
import asyncio
import unittest
from unittest.mock import patch

import channels
import main


async def until(done, timeout=5):
    """Wait for a condition instead of for a task: channels keep retrying and never finish."""
    async with asyncio.timeout(timeout):
        while not done():
            await asyncio.sleep(.01)


class Socket:
    async def close(self, **kwargs):pass


class FakeChannel:
    instances = []
    def __init__(self, language, url, key, publish, noise_reduction=None, transcribe=None, headers=None):
        self.language = language
        self.url = url
        self.headers = headers
        self.publish = publish
        self.noise_reduction = noise_reduction
        self.transcribe = transcribe
        self.status = 'live'
        self.failed = False
        self.spoke = False
        self.task = None
        self.closed = False
        self.woken = 0
        self.instances.append(self)
    def start(self):
        self.task = asyncio.create_task(asyncio.Event().wait())
    def feed(self, pcm):
        self.fed = getattr(self, 'fed', []) + [pcm]
        if pcm is None:
            self.task.cancel()
        return True
    def retry_now(self):
        self.woken += 1
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

    async def speaker(self):
        peer = main.Peer(Socket(), speaker=True)
        self.room.peers.add(peer)
        return peer

    async def set_channel(self, language, status):
        channel = self.room.channels[language]
        channel.status = status
        channel.failed = status == 'error'
        await channel.publish({'type': 'status', 'status': status})

    def last_report(self, speaker):
        report = None
        while not speaker.queue.empty():
            report = speaker.queue.get_nowait()
        return report

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

    async def test_speaker_sees_a_channel_that_has_not_come_up_yet(self):
        """A slow handshake looks exactly like a working session without this report."""
        speaker = await self.speaker()
        await self.join('fr')
        await self.set_channel('fr', 'connecting')
        self.assertEqual(self.last_report(speaker),
                         {'type': 'channels', 'failed': [], 'live': 0, 'total': 1})
        await self.set_channel('fr', 'live')
        self.assertEqual(self.last_report(speaker),
                         {'type': 'channels', 'failed': [], 'live': 1, 'total': 1})

    async def test_speaker_learns_which_languages_stopped_translating(self):
        speaker = await self.speaker()
        await self.join('fr')
        main.ensure_channel(self.room, 'en')  # carries the original captions while speaking
        self.last_report(speaker)
        await self.set_channel('fr', 'error')
        self.assertEqual(self.last_report(speaker),
                         {'type': 'channels', 'failed': ['fr'], 'live': 1, 'total': 2})
        await self.set_channel('fr', 'error')  # an unchanged state stays quiet
        self.assertTrue(speaker.queue.empty())
        await self.set_channel('en', 'error')
        self.assertEqual(self.last_report(speaker),
                         {'type': 'channels', 'failed': ['en', 'fr'], 'live': 0, 'total': 2})

    async def test_the_speakers_warning_ends_when_it_works_again_not_when_someone_retries(self):
        """A retry is not an all-clear: until a channel is live, nothing is being translated."""
        speaker = await self.speaker()
        listener = await self.join('fr')
        channel = await self.break_channel('fr')
        await channel.publish({'type': 'status', 'status': 'error'})
        self.assertEqual(self.last_report(speaker)['failed'], ['fr'])
        self.assertTrue(await main.subscribe(self.room, listener, 'fr', 2))
        self.assertEqual(channel.woken, 1)
        self.assertTrue(speaker.queue.empty())
        await self.set_channel('fr', 'live')
        self.assertEqual(self.last_report(speaker),
                         {'type': 'channels', 'failed': [], 'live': 1, 'total': 1})

    async def break_channel(self, language):
        """Leave the channel as a failing one does: reported as failed, still retrying."""
        channel = self.room.channels[language]
        channel.status = 'error'
        channel.failed = True
        return channel

    async def test_a_listener_cannot_retry_a_language_over_and_over(self):
        """One tap brings the next attempt forward for everyone; the next taps must not."""
        listener = await self.join('fr')
        channel = await self.break_channel('fr')
        self.assertTrue(await main.subscribe(self.room, listener, 'fr', 2))
        self.assertEqual(channel.woken, 1)
        self.assertTrue(await main.subscribe(self.room, listener, 'fr', 3))
        self.assertEqual(channel.woken, 1)  # still within the cooldown
        self.assertEqual(self.last_report(listener)['status'], 'error')
        self.room.retried['fr'] -= main.RETRY_COOLDOWN
        self.assertTrue(await main.subscribe(self.room, listener, 'fr', 4))
        self.assertEqual(channel.woken, 2)
        self.assertIs(self.room.channels['fr'], channel)  # the same channel throughout

    async def test_a_channel_that_stopped_retrying_is_rebuilt(self):
        """Only a channel whose task is gone needs a new slot."""
        listener = await self.join('fr')
        channel = await self.break_channel('fr')
        channel.task.cancel()
        await asyncio.gather(channel.task, return_exceptions=True)
        self.assertTrue(await main.subscribe(self.room, listener, 'fr', 2))
        self.assertIsNot(self.room.channels['fr'], channel)

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

    async def test_only_the_room_language_channel_carries_captions_for_everyone(self):
        speaker = main.Peer(Socket());self.room.peers.add(speaker)
        a = await self.join('en');b = await self.join('fr')
        self.assertEqual({l: c.transcribe for l, c in self.room.channels.items()}, {'en': main.TRANSCRIPTION_MODEL, 'fr': None})
        self.assertTrue(main.TRANSCRIPTION_MODEL)
        await self.room.channels['en'].publish({'type': 'original_delta', 'delta': ' Guten'})
        await self.room.channels['en'].publish({'type': 'original_delta', 'delta': ' Abend'})
        self.assertEqual(self.room.original, ' Guten Abend')
        for peer in (speaker, a, b):
            self.assertEqual([e['text'] for e in [peer.queue.get_nowait(), peer.queue.get_nowait()]], [' Guten', ' Guten Abend'])
        # The caption channel survives the last listener of that language switching away while speaking.
        await main.subscribe(self.room, a, 'es', 2)
        self.assertIn('en', self.room.channels)
        self.assertFalse(self.room.channels['en'].closed)
        self.room.active = False
        await main.prune_channels(self.room)
        self.assertNotIn('en', self.room.channels)

    async def test_switch_clears_old_language_queue_and_releases_last_slot(self):
        self.room.language = 'de'
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

    async def test_setting_change_swaps_channels_without_a_status_for_listeners(self):
        a = await self.join('en');await self.join('fr')
        old = dict(self.room.channels)
        self.room.noise_reduction = 'near_field'
        await main.swap_channels(self.room)
        # Before the old channel is done, its tail passes and the new channel's output waits.
        await old['en'].publish({'type': 'status', 'status': 'ended'})
        await old['en'].publish({'type': 'audio', 'delta': 'tail'})
        await self.room.channels['en'].publish({'type': 'audio', 'delta': 'fresh'})
        self.assertEqual(a.queue.get_nowait()['delta'], 'tail')
        self.assertTrue(a.queue.empty())
        await asyncio.gather(*self.room.retiring, return_exceptions=True)
        self.assertEqual(a.queue.get_nowait()['delta'], 'fresh')
        await self.room.channels['en'].publish({'type': 'audio', 'delta': 'later'})
        self.assertEqual(a.queue.get_nowait()['delta'], 'later')
        self.assertEqual({l: c.noise_reduction for l, c in self.room.channels.items()}, {'en': 'near_field', 'fr': 'near_field'})
        self.assertTrue(all(c.fed == [None] and c.closed for c in old.values()))
        self.assertTrue(main.is_quiet(bytes(4800)))
        loud = (b'\x10\x27' * 2400)
        self.assertFalse(main.is_quiet(loud))

    async def test_selected_azure_provider_reaches_room_channels_and_health(self):
        from provider import provider_settings
        provider = provider_settings({'TRANSLATE_PROVIDER': 'azure',
                                      'AZURE_OPENAI_ENDPOINT': 'https://example.openai.azure.com',
                                      'AZURE_OPENAI_DEPLOYMENT': 'translate',
                                      'AZURE_OPENAI_API_KEY': 'azure-test'})
        with patch.object(main, 'PROVIDER', provider), patch.object(main, 'URL', provider.url), patch.object(main, 'KEY', provider.key):
            await self.join('en')
            await self.join('fr')
            health = await main.health()
        for channel in self.room.channels.values():
            self.assertEqual(channel.url, provider.url)
            self.assertEqual(channel.headers, {'api-key': 'azure-test'})
        self.assertEqual(health['translation_provider'], 'azure')
        self.assertTrue(health['translation_configured'])
        self.assertNotIn('azure-test', str(health))

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
        await main.swap_channels(self.room)
        await asyncio.gather(*self.room.retiring, return_exceptions=True)
        await self.room.channels['en'].publish({'type':'translation_delta','delta':'again'})
        self.assertEqual(self.room.translations['en'],'Hello again')

class Reachability(unittest.IsolatedAsyncioTestCase):
    """/api/health tells the speaker whether the provider answers, before anyone starts talking."""
    def setUp(self):
        main.rooms.clear()
        main.reachability.update({'state': 'unknown', 'checked': 0.0, 'task': None})
        self.key = patch.object(main, 'KEY', 'test-only')
        self.key.start()
    def tearDown(self):
        self.key.stop()
        main.rooms.clear()

    async def settle(self):
        task = main.reachability['task']
        if task:
            await asyncio.gather(task, return_exceptions=True)

    async def test_health_answers_at_once_and_reports_the_finished_check(self):
        slow = asyncio.Event()
        async def hanging(*args, **kwargs):
            await slow.wait()
        with patch.object(main, 'probe', hanging):
            self.assertEqual((await main.health())['translation_reachable'], 'unknown')
            # Still 'unknown' while the probe runs: a hanging provider must not hold up the endpoint.
            self.assertEqual((await main.health())['translation_reachable'], 'unknown')
            slow.set()
            await self.settle()
        self.assertEqual((await main.health())['translation_reachable'], 'ok')

    async def test_a_refused_provider_is_reported_without_leaking_its_detail(self):
        async def refused(*args, **kwargs):
            raise RuntimeError('Translation probe rejected: model gpt-secret-name not deployed')
        with patch.object(main, 'probe', refused), self.assertLogs('main', level='WARNING') as logs:
            await main.health()
            await self.settle()
            health = await main.health()
        self.assertEqual(health['translation_reachable'], 'unreachable')
        self.assertIn('gpt-secret-name', logs.output[0])
        self.assertNotIn('gpt-secret-name', str(health))

    async def test_repeated_calls_share_one_check_and_a_broadcast_suspends_it(self):
        calls = []
        async def counting(*args, **kwargs):
            calls.append(1)
        with patch.object(main, 'probe', counting):
            for _ in range(5):
                await main.health()
                await self.settle()
            self.assertEqual(len(calls), 1)  # the result stays current for PROBE_INTERVAL
            main.reachability['checked'] = 0.0
            main.rooms['r'] = main.Room(owner='o', language='en', source='de', active=True)
            await main.health()
            await self.settle()
            self.assertEqual(len(calls), 1)  # the open channels say more than a probe would

    async def test_a_missing_key_needs_no_check_at_all(self):
        async def unexpected(*args, **kwargs):
            raise AssertionError('probed without a key')
        with patch.object(main, 'KEY', ''), patch.object(main, 'probe', unexpected):
            self.assertEqual((await main.health())['translation_reachable'], 'unconfigured')
        self.assertIsNone(main.reachability['task'])


class SessionUpdate(unittest.IsolatedAsyncioTestCase):
    async def open_channel(self, reply, retries=(), **kwargs):
        import json
        import channels as channels_module
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
        with patch('channels.websockets.connect', return_value=Connection()) as connect, \
             patch.object(channels_module, 'RETRY_DELAYS', retries), \
             patch.object(channels_module, 'RECOVERY_DELAYS', (0,)):
            channel = TranslationChannel('fr', 'wss://test', 'test', publish, **kwargs)
            channel.start()
            # The channel no longer ends by itself; it is done once it has reported the outage.
            await until(lambda: any(e['type'] == 'error' for e in published))
            await channel.close()
        self.assertEqual(connect.call_args.kwargs['additional_headers'],
                         kwargs.get('headers', {'Authorization': 'Bearer test'}))
        self.assertEqual(sent[0]['type'], 'session.update')
        return sent[0]['session'], published

    async def test_azure_handshake_uses_only_api_key_header(self):
        from provider import provider_settings
        provider = provider_settings({'TRANSLATE_PROVIDER': 'azure',
                                      'AZURE_OPENAI_ENDPOINT': 'https://example.openai.azure.com',
                                      'AZURE_OPENAI_DEPLOYMENT': 'translate',
                                      'AZURE_OPENAI_API_KEY': 'azure-test'})
        session, _ = await self.open_channel({'type': 'session.updated'}, headers=provider.headers())
        self.assertEqual(session, {'audio': {'output': {'language': 'fr'}}})

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
        self.assertEqual([e['type'] for e in published[:2]], ['status', 'error'])
        self.assertNotIn('Additional', str(published))

    async def test_lost_upstream_is_retried_before_the_language_is_given_up(self):
        """A short provider outage must not cost the listener their language."""
        rejection = {'type': 'error', 'error': {'type': 'server_error', 'message': 'upstream gone'}}
        with self.assertLogs('channels', level='WARNING'):
            _, published = await self.open_channel(rejection, retries=(0, 0))
        # Two quick retries stay a 'connecting' status; only the third failure is an outage.
        self.assertEqual([(e['type'], e.get('status')) for e in published[:4]],
                         [('status', 'connecting'), ('status', 'connecting'), ('status', 'error'), ('error', None)])
        self.assertEqual([e for e in published if e['type'] == 'error'][0]['code'], 'channel_unavailable')

    async def test_a_reported_outage_keeps_trying_and_recovers_on_its_own(self):
        """The provider comes back; nobody should have to press anything for translation to resume."""
        import json
        import channels as channels_module
        from channels import TranslationChannel
        published = []
        attempts = []
        class Socket:
            def __init__(self, ok):self.ok = ok
            async def send(self, raw):pass
            async def recv(self):
                return json.dumps({'type': 'session.updated'} if self.ok else
                                  {'type': 'error', 'error': {'message': 'down'}})
            def __aiter__(self):return self
            async def __anext__(self):
                await asyncio.sleep(.05)
                raise StopAsyncIteration
        class Connection:
            def __init__(self, *args, **kwargs):attempts.append(1)
            async def __aenter__(self):return Socket(len(attempts) > 3)
            async def __aexit__(self, *args):pass
        async def publish(event):published.append(event)
        with patch('channels.websockets.connect', Connection), \
             patch.object(channels_module, 'RETRY_DELAYS', (0, 0)), \
             patch.object(channels_module, 'RECOVERY_DELAYS', (0,)):
            channel = TranslationChannel('fr', 'wss://test', 'test', publish)
            channel.start()
            await until(lambda: any(e.get('status') == 'live' for e in published))
            await channel.close()
        # The outage was reported first, and the channel came back without anyone asking.
        self.assertTrue(any(e['type'] == 'error' for e in published))
        self.assertFalse(channel.failed)

    async def test_a_second_outage_is_reported_like_the_first(self):
        """After a recovery the quick retries start over, otherwise the next outage stays silent."""
        import json
        import channels as channels_module
        from channels import TranslationChannel
        published = []
        attempts = []
        class Socket:
            async def send(self, raw):pass
            async def recv(self):return json.dumps({'type': 'session.updated'})
            def __aiter__(self):return self
            async def __anext__(self):
                await asyncio.sleep(.01)
                raise StopAsyncIteration  # every session drops right after it came up
        # Up, down for three attempts, up again, down again: two outages around one recovery.
        script = ['ok', 'fail', 'fail', 'fail', 'ok', 'fail', 'fail', 'fail']
        class Connection:
            def __init__(self, *args, **kwargs):
                self.ok = script[len(attempts)] == 'ok' if len(attempts) < len(script) else False
                attempts.append(1)
            async def __aenter__(self):
                if not self.ok:
                    raise OSError('down')
                return Socket()
            async def __aexit__(self, *args):pass
        async def publish(event):published.append(event)
        with patch('channels.websockets.connect', Connection), \
             patch.object(channels_module, 'RETRY_DELAYS', (0, 0)), \
             patch.object(channels_module, 'RECOVERY_DELAYS', (0,)):
            channel = TranslationChannel('fr', 'wss://test', 'test', publish)
            channel.start()
            await until(lambda: sum(e['type'] == 'error' for e in published) >= 2)
            await channel.close()
        # Both outages were announced, and the recovery in between cleared the first one.
        self.assertGreaterEqual(sum(e.get('status') == 'live' for e in published), 2)

    async def test_listeners_read_the_outage_between_attempts_not_connecting(self):
        """The wait is part of the outage; only the attempt itself is a connection in progress."""
        from channels import TranslationChannel
        published = []
        async def publish(event):published.append(event)
        def refuse(*args, **kwargs):
            raise OSError('no route')
        with patch('channels.websockets.connect', refuse), \
             patch.object(channels, 'RETRY_DELAYS', (0, 0)), \
             patch.object(channels, 'RECOVERY_DELAYS', (.05,)):
            channel = TranslationChannel('fr', 'wss://test', 'test', publish)
            channel.start()
            await until(lambda: sum(e.get('status') == 'error' for e in published) >= 2)
            await channel.close()
        states = [e['status'] for e in published if e['type'] == 'status']
        self.assertEqual(states[2:5], ['error', 'connecting', 'error'])

    async def test_a_retry_cuts_the_wait_short(self):
        """Waiting out a recovery delay of up to a minute is what the retry button is for."""
        from channels import TranslationChannel
        attempts = []
        def refuse(*args, **kwargs):
            attempts.append(1)
            raise OSError('no route')
        async def publish(event):pass
        with patch('channels.websockets.connect', refuse):
            channel = TranslationChannel('fr', 'wss://test', 'test', publish)
            channel.start()
            await until(lambda: len(attempts) == 1)
            await asyncio.sleep(.05)
            self.assertEqual(len(attempts), 1)  # the next attempt is a second away
            channel.retry_now()
            await until(lambda: len(attempts) == 2)
            await channel.close()

    async def test_a_draining_channel_is_not_reconnected(self):
        import channels as channels_module
        from channels import TranslationChannel
        published = []
        async def publish(event):published.append(event)
        with patch('channels.websockets.connect', side_effect=OSError('no route')), \
             patch.object(channels_module, 'RETRY_DELAYS', (0, 0)):
            channel = TranslationChannel('fr', 'wss://test', 'test', publish)
            channel.start()
            channel.feed(None)
            await asyncio.wait_for(channel.task, 5)
        self.assertEqual([e['type'] for e in published], ['status', 'error'])
        self.assertTrue(channel.task.done())  # a drained channel stops for good


class Probe(unittest.IsolatedAsyncioTestCase):
    async def run_probe(self, reply):
        import json
        from channels import probe
        sent = []
        class Socket:
            async def send(self, raw):sent.append(json.loads(raw))
            async def recv(self):return json.dumps(reply)
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self, *args):pass
        with patch('channels.websockets.connect', return_value=Connection()):
            await asyncio.wait_for(probe('wss://test', {'Authorization': 'Bearer test'}, 2), 5)
        return sent

    async def test_the_probe_completes_a_handshake_and_sends_no_audio(self):
        sent = await self.run_probe({'type': 'session.updated'})
        self.assertEqual(sent, [{'type': 'session.update', 'session': {'audio': {'output': {'language': 'en'}}}}])

    async def test_a_rejected_handshake_counts_as_unreachable(self):
        rejection = {'type': 'error', 'error': {'type': 'invalid_request', 'message': 'model not found'}}
        with self.assertRaisesRegex(RuntimeError, 'model not found'):
            await self.run_probe(rejection)


class Backpressure(unittest.IsolatedAsyncioTestCase):
    async def test_slow_language_does_not_cancel_another_channel(self):
        from channels import TranslationChannel
        async def publish(event):pass
        slow = TranslationChannel('en','wss://test','test',publish)
        fast = TranslationChannel('fr','wss://test','test',publish)
        slow.task = asyncio.create_task(asyncio.Event().wait())
        fast.task = asyncio.create_task(asyncio.Event().wait())
        slow.status = fast.status = 'live'
        try:
            for _ in range(100):self.assertTrue(slow.feed(bytes(4800)))
            self.assertFalse(slow.feed(bytes(4800)))
            self.assertTrue(fast.feed(bytes(4800)))
            self.assertFalse(fast.task.done())
            self.assertEqual(slow.status,'error')
        finally:
            await slow.close();await fast.close()

    async def test_a_reconnected_channel_starts_from_current_audio(self):
        """Playing the backlog would leave every listener seconds behind the speaker."""
        import json
        import channels as channels_module
        from channels import TranslationChannel
        sent = []
        class Socket:
            async def send(self, raw):sent.append(json.loads(raw))
            async def recv(self):return json.dumps({'type': 'session.updated'})
            def __aiter__(self):return self
            async def __anext__(self):
                await asyncio.sleep(.2)
                raise StopAsyncIteration
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self, *args):pass
        async def publish(event):pass
        with patch('channels.websockets.connect', return_value=Connection()):
            channel = TranslationChannel('fr', 'wss://test', 'test', publish)
            channel.task = asyncio.create_task(asyncio.Event().wait())
            for _ in range(20):channel.feed(bytes(4800))
            channel.task.cancel()
            await asyncio.gather(channel.task, return_exceptions=True)
            channel.start()
            await until(lambda: channel.status == 'live')
            await asyncio.sleep(.05)  # give the sender a chance to forward what it has
            await channel.close()
        self.assertEqual([e['type'] for e in sent], ['session.update'])

    async def test_a_reconnecting_channel_drops_stale_audio_instead_of_giving_up(self):
        from channels import TranslationChannel
        async def publish(event):pass
        channel = TranslationChannel('en','wss://test','test',publish)
        channel.task = asyncio.create_task(asyncio.Event().wait())
        try:
            for _ in range(140):self.assertTrue(channel.feed(bytes(4800)))
            self.assertEqual(channel.status,'connecting')
            self.assertEqual(channel.queue.qsize(),100)
            self.assertFalse(channel.task.done())
        finally:
            await channel.close()
