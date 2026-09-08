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
    def test_missing_key_is_not_a_fake_success(self):
        with patch.object(main,'KEY',''), self.assertRaises(HTTPException) as raised:
            main.create_room(main.NewRoom(),request())
        self.assertEqual(raised.exception.status_code,503)

if __name__=='__main__':unittest.main()
