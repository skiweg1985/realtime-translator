"""Provider configuration and credential isolation, without external calls."""
import unittest

from provider import provider_settings


class ProviderSettings(unittest.TestCase):
    def test_default_and_existing_compatible_configuration(self):
        default = provider_settings({})
        self.assertEqual(default.name, 'openai')
        self.assertEqual(default.url, 'wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate')
        self.assertFalse(default.key)
        custom = provider_settings({'TRANSLATE_URL': 'wss://provider.example/v1/realtime/translations?model=custom',
                                    'TRANSLATE_KEY': 'compatible-secret', 'AZURE_OPENAI_API_KEY': 'ignored'})
        self.assertEqual(custom.url, 'wss://provider.example/v1/realtime/translations?model=custom')
        self.assertEqual(custom.headers(), {'Authorization': 'Bearer compatible-secret'})
        self.assertNotIn('compatible-secret', repr(custom))

    def test_azure_endpoint_deployment_and_key_are_selected_together(self):
        settings = {'TRANSLATE_PROVIDER': 'azure',
                    'AZURE_OPENAI_ENDPOINT': 'https://example.openai.azure.com/',
                    'AZURE_OPENAI_DEPLOYMENT': 'translation & test',
                    'AZURE_OPENAI_API_KEY': 'azure-secret',
                    'TRANSLATE_URL': 'wss://ignored.example', 'TRANSLATE_KEY': 'ignored'}
        provider = provider_settings(settings)
        self.assertEqual(provider.url, 'wss://example.openai.azure.com/openai/v1/realtime/translations?model=translation%20%26%20test')
        self.assertEqual(provider.headers(), {'api-key': 'azure-secret'})
        self.assertNotIn('azure-secret', repr(provider))
        del settings['AZURE_OPENAI_API_KEY']
        self.assertFalse(provider_settings(settings).key)

    def test_invalid_provider_and_endpoints_fail_without_echoing_input(self):
        invalid = [
            {'TRANSLATE_PROVIDER': 'azuer'},
            {'TRANSLATE_URL': 'http://example.com'},
            {'TRANSLATE_URL': 'wss://user:secret@example.com'},
            {'TRANSLATE_PROVIDER': 'azure'},
            {'TRANSLATE_PROVIDER': 'azure', 'AZURE_OPENAI_ENDPOINT': 'https://example.com'},
        ]
        for endpoint in ['http://example.com', 'https://example.com/openai/v1',
                         'https://example.com?api-key=secret', 'https://user:secret@example.com']:
            invalid.append({'TRANSLATE_PROVIDER': 'azure', 'AZURE_OPENAI_ENDPOINT': endpoint,
                            'AZURE_OPENAI_DEPLOYMENT': 'translate'})
        for settings in invalid:
            with self.subTest(settings=settings), self.assertRaises(ValueError) as error:
                provider_settings(settings)
            self.assertNotIn('secret', str(error.exception))
