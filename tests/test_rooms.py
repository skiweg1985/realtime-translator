"""Room capability and input-policy regression checks; no provider calls."""
import unittest
from unittest.mock import patch
from starlette.requests import Request
from fastapi import HTTPException
import main


def request(origin=b'https://local:8443'):
    return Request({'type':'http','headers':[(b'origin',origin),(b'host',b'local:8443')]})

class Rooms(unittest.TestCase):
    def setUp(self):
        main.rooms.clear()
        self.key = patch.object(main, 'KEY', 'test-only')
        self.key.start()
    def tearDown(self):
        self.key.stop()
        main.rooms.clear()
    def test_listener_metadata_never_exposes_speaker_capability(self):
        created = main.create_room(main.NewRoom(), request())
        info = main.room_info(created['id'])
        self.assertNotIn('owner', info)
        self.assertGreaterEqual(len(created['owner']), 32)
        self.assertNotEqual(created['id'], created['owner'])
    def test_cross_origin_room_creation_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            main.create_room(main.NewRoom(), request(b'https://foreign.example'))
        self.assertEqual(raised.exception.status_code,403)
    def test_unknown_language_rejected(self):
        with self.assertRaises(HTTPException):
            main.create_room(main.NewRoom(language='untrusted'), request())
    def test_join_code_is_four_spoken_digits_and_resolves(self):
        a = main.create_room(main.NewRoom(), request())
        b = main.create_room(main.NewRoom(), request())
        self.assertRegex(a['code'], r'^[1-9][0-9]{3}$')
        self.assertNotEqual(a['code'], b['code'])
        self.assertEqual(main.room_by_code(a['code'])['id'], a['id'])
        self.assertEqual(main.room_info(a['id'])['code'], a['code'])
    def test_unknown_join_code_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            main.room_by_code('0000')
        self.assertEqual(raised.exception.status_code, 404)
    def test_noise_reduction_setting_normalises_and_rejects_typos(self):
        with patch.dict('os.environ', {'NR_TEST': ''}):
            self.assertEqual(main.noise_reduction_setting('NR_TEST', 'near_field'), 'near_field')
        with patch.dict('os.environ', {'NR_TEST': ' Off '}):
            self.assertIsNone(main.noise_reduction_setting('NR_TEST', 'near_field'))
        with patch.dict('os.environ', {'NR_TEST': 'far_field'}):
            self.assertEqual(main.noise_reduction_setting('NR_TEST', 'off'), 'far_field')
        with patch.dict('os.environ', {'NR_TEST': 'loud'}), self.assertRaises(ValueError):
            main.noise_reduction_setting('NR_TEST', 'off')
    def test_frontend_offers_exactly_the_backend_languages(self):
        import re
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / 'frontend/src/main.tsx').read_text()
        block = re.search(r'const languages: Record<string, string> = \{(.*?)\};', source, re.S).group(1)
        self.assertEqual(set(re.findall(r'^\s*([a-z]{2}):', block, re.M)), main.LANGUAGES)
    def test_missing_key_is_not_a_fake_success(self):
        with patch.object(main,'KEY',''), self.assertRaises(HTTPException) as raised:
            main.create_room(main.NewRoom(),request())
        self.assertEqual(raised.exception.status_code,503)

class Ending(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        main.rooms.clear()
        self.key = patch.object(main, 'KEY', 'test-only')
        self.key.start()
    async def asyncTearDown(self):
        self.key.stop()
        main.rooms.clear()
    async def test_only_the_owner_ends_and_listeners_get_a_final_status(self):
        created = main.create_room(main.NewRoom(), request())
        room = main.rooms[created['id']]
        closed = []
        class Socket:
            async def close(self, **kwargs):closed.append(kwargs)
        peer = main.Peer(Socket())
        peer.language = 'en'
        room.peers.add(peer)
        with self.assertRaises(HTTPException) as raised:
            await main.end_room(created['id'], main.EndRoom(owner='wrong'), request())
        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn(created['id'], main.rooms)
        room.active = True
        with self.assertRaises(HTTPException) as raised:
            await main.end_room(created['id'], main.EndRoom(owner=created['owner']), request())
        self.assertEqual(raised.exception.status_code, 409)
        room.active = False
        await main.end_room(created['id'], main.EndRoom(owner=created['owner']), request())
        self.assertNotIn(created['id'], main.rooms)
        self.assertEqual(peer.queue.get_nowait(), {'type': 'status', 'status': 'closed'})
        self.assertEqual(closed, [{'code': 1000}])
        with self.assertRaises(HTTPException):
            main.room_info(created['id'])

if __name__=='__main__':unittest.main()
