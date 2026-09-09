"""Configurable limits: parsing, language admission and real timeout behavior."""
import asyncio
import unittest
from unittest.mock import patch

import main


class Settings(unittest.TestCase):
    def test_defaults_and_valid_overrides(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(main.integer_setting('MAX_LANGUAGES', 4, 1, 17), 4)
            self.assertEqual(main.integer_setting('MAX_BROADCAST_SECONDS', 3600, 0), 3600)
        for value in ['0', '3600']:
            with patch.dict('os.environ', {'MAX_BROADCAST_SECONDS': value}):
                self.assertEqual(main.integer_setting('MAX_BROADCAST_SECONDS', 3600, 0), int(value))
        with patch.dict('os.environ', {'MAX_LANGUAGES': '17'}):
            self.assertEqual(main.integer_setting('MAX_LANGUAGES', 4, 1, 17), 17)

    def test_invalid_values_fail(self):
        for value in ['', '-1', '1.5', 'abc', '１２']:
            with self.subTest(value=value), patch.dict('os.environ', {'LIMIT': value}):
                with self.assertRaises(ValueError):
                    main.integer_setting('LIMIT', 600, 0)
        for value in ['0', '18']:
            with patch.dict('os.environ', {'LIMIT': value}), self.assertRaises(ValueError):
                main.integer_setting('LIMIT', 4, 1, 17)


class Limits(unittest.IsolatedAsyncioTestCase):
    async def test_custom_language_limit_and_rejection_message(self):
        room = main.Room(owner='owner', language='en', source='de')
        with patch.object(main, 'MAX_LANGUAGES', 2):
            french = main.Peer(None)
            room.peers.add(french)
            self.assertTrue(await main.subscribe(room, french, 'fr', 1))
            german = main.Peer(None)
            room.peers.add(german)
            self.assertFalse(await main.subscribe(room, german, 'de', 1))
            self.assertIn('2 Sprachen', german.queue.get_nowait()['message'])
        with patch.object(main, 'MAX_LANGUAGES', 6):
            for language in ['de', 'es', 'it', 'pt']:
                peer = main.Peer(None)
                room.peers.add(peer)
                self.assertTrue(await main.subscribe(room, peer, language, 1))

    async def test_broadcast_expires_but_preserves_room(self):
        room = main.Room(owner='owner', language='en', source='de', active=True)
        class Socket:
            async def receive(self):
                await asyncio.Event().wait()
        speaker = main.Peer(Socket())
        with patch.object(main, 'MAX_BROADCAST_SECONDS', .01), patch.object(main, 'ensure_channel'):
            await asyncio.wait_for(main.translation(room, speaker.ws, speaker), 1)
        self.assertEqual(room.owner, 'owner')
        self.assertFalse(room.channels)
        self.assertTrue(room.draining)

    async def test_disabled_timer_waits_for_explicit_stop(self):
        messages = asyncio.Queue()
        class Socket:
            async def receive(self):
                return await messages.get()
        room = main.Room(owner='owner', language='en', source='de', active=True)
        speaker = main.Peer(Socket())
        with patch.object(main, 'MAX_BROADCAST_SECONDS', 0), patch.object(main, 'ensure_channel'):
            task = asyncio.create_task(main.translation(room, speaker.ws, speaker))
            try:
                await asyncio.wait_for(speaker.queue.get(), 1)
                await asyncio.sleep(.03)
                self.assertFalse(task.done())
                await messages.put({'type': 'websocket.receive', 'text': 'stop'})
                await asyncio.wait_for(task, 1)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
