"""Room capability and input-policy regression checks; no provider calls."""
import unittest
from unittest.mock import patch
from starlette.requests import Request
from fastapi import HTTPException
import main
from fastapi.testclient import TestClient


def request(origin=b'https://local:8443'):
    return Request({'type':'http','headers':[(b'origin',origin),(b'host',b'local:8443')]})

class Rooms(unittest.TestCase):
    def setUp(self):
        main.rooms.clear()
        self.key = patch.object(main, 'KEY', 'test-only')
        self.key.start()
        self.pin = patch.object(main, 'SPEAKER_PIN', '0000')
        self.pin.start()
    def tearDown(self):
        self.key.stop()
        self.pin.stop()
        main.rooms.clear()
    def test_listener_metadata_never_exposes_speaker_capability(self):
        created = main.create_room(main.NewRoom(pin="0000"), request())
        info = main.room_info(created['id'])
        self.assertNotIn('owner', info)
        self.assertGreaterEqual(len(created['owner']), 32)
        self.assertNotEqual(created['id'], created['owner'])
        self.assertNotIn('pin', info)
        self.assertNotIn('pin', created)
    def test_pin_defaults_and_configuration_preserve_leading_zeros(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(main.speaker_pin_setting(), '0000')
        with patch.dict('os.environ', {'SPEAKER_PIN': '0123'}):
            self.assertEqual(main.speaker_pin_setting(), '0123')
        for invalid in ['', '123', '12345', 'abcd', '１２３４', ' 1234']:
            with self.subTest(value=invalid), patch.dict('os.environ', {'SPEAKER_PIN': invalid}):
                with self.assertRaisesRegex(ValueError, 'exactly four digits'):
                    main.speaker_pin_setting()
    def test_missing_wrong_and_unicode_pin_cannot_create_a_room(self):
        with TestClient(main.app) as client:
            for body in [{}, {'pin': ''}, {'pin': '9999'}, {'pin': '１２３４'}]:
                with self.subTest(body=body):
                    response = client.post('/api/rooms', json=body)
                    self.assertEqual(response.status_code, 403)
                    self.assertFalse(main.rooms)
    def test_configured_pin_replaces_default(self):
        with patch.object(main, 'SPEAKER_PIN', '0123'), TestClient(main.app) as client:
            self.assertEqual(client.post('/api/rooms', json={'pin': '0000'}).status_code, 403)
            response = client.post('/api/rooms', json={'pin': '0123'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(main.rooms), 1)
    def test_prepared_room_accepts_listeners_without_starting_translation(self):
        with patch.object(main, 'TranslationChannel') as channel, TestClient(main.app) as client:
            created = client.post('/api/rooms', json={'pin': '0000', 'source': 'fr', 'language': 'en'}).json()
            info = client.get('/api/rooms/' + created['id']).json()
            self.assertFalse(info['active'])
            self.assertEqual(info['source'], 'fr')
            self.assertEqual(client.get('/api/rooms/by-code/' + created['code']).json(), {'id': created['id']})
            with client.websocket_connect('/api/rooms/' + created['id'] + '/ws') as listener:
                listener.send_json({'role': 'listener', 'language': 'en'})
                self.assertEqual(listener.receive_json()['status'], 'waiting')
                self.assertFalse(main.rooms[created['id']].active)
                channel.assert_not_called()
    def test_start_uses_prepared_room_and_owner_without_another_pin(self):
        observed = []
        async def translate(room, ws, speaker):
            observed.append(room)
            await ws.send_json({'type': 'status', 'status': 'live'})
            await ws.receive_text()
        with patch.object(main, 'translation', translate), TestClient(main.app) as client:
            created = client.post('/api/rooms', json={'pin': '0000'}).json()
            room = main.rooms[created['id']]
            for _ in range(2):
                with client.websocket_connect('/api/rooms/' + created['id'] + '/ws') as speaker:
                    speaker.send_json({'role': 'speaker', 'owner': created['owner']})
                    while speaker.receive_json().get('status') != 'live':
                        pass
                    self.assertTrue(room.active)
                    speaker.send_text('stop')
                    while speaker.receive_json().get('status') != 'ended':
                        pass
                self.assertFalse(room.active)
            self.assertEqual(observed, [room, room])
            self.assertEqual(len(main.rooms), 1)
    def test_public_session_code_does_not_grant_speaker_access(self):
        with patch.object(main, 'translation') as translate, TestClient(main.app) as client:
            created = client.post('/api/rooms', json={'pin': '0000'}).json()
            with client.websocket_connect('/api/rooms/' + created['id'] + '/ws') as speaker:
                speaker.send_json({'role': 'speaker', 'owner': created['code']})
                self.assertEqual(speaker.receive_json()['type'], 'error')
            translate.assert_not_called()
            self.assertFalse(main.rooms[created['id']].active)
    def test_cross_origin_room_creation_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            main.create_room(main.NewRoom(pin="0000"), request(b'https://foreign.example'))
        self.assertEqual(raised.exception.status_code,403)
    def test_unknown_language_rejected(self):
        with self.assertRaises(HTTPException):
            main.create_room(main.NewRoom(language='untrusted', pin="0000"), request())
    def test_join_code_is_four_spoken_digits_and_resolves(self):
        a = main.create_room(main.NewRoom(pin="0000"), request())
        b = main.create_room(main.NewRoom(pin="0000"), request())
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
            main.create_room(main.NewRoom(pin="0000"),request())
        self.assertEqual(raised.exception.status_code,503)

class Ending(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        main.rooms.clear()
        self.key = patch.object(main, 'KEY', 'test-only')
        self.key.start()
        self.pin = patch.object(main, 'SPEAKER_PIN', '0000')
        self.pin.start()
    async def asyncTearDown(self):
        self.key.stop()
        self.pin.stop()
        main.rooms.clear()
    async def test_only_the_owner_ends_and_listeners_get_a_final_status(self):
        created = main.create_room(main.NewRoom(pin="0000"), request())
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
