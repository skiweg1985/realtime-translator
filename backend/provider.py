"""Resolve server-side connection settings for the selected translation provider."""
import os
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit


@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    key: str = field(repr=False)

    def headers(self):
        if self.name == 'azure':
            return {'api-key': self.key}
        return {'Authorization': 'Bearer ' + self.key}


def provider_settings(env=None):
    env = os.environ if env is None else env
    name = env.get('TRANSLATE_PROVIDER', 'openai').strip().lower()
    if name == 'openai':
        url = env.get('TRANSLATE_URL', 'wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate').strip()
        parsed = urlsplit(url)
        if parsed.scheme != 'wss' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('TRANSLATE_URL must be a wss:// URL without credentials or fragment.')
        return Provider(name, url, env.get('TRANSLATE_KEY', '').strip())
    if name == 'azure':
        endpoint = env.get('AZURE_OPENAI_ENDPOINT', '').strip().rstrip('/')
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.path
                or parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise ValueError('AZURE_OPENAI_ENDPOINT must be an https:// resource endpoint without a path, query or credentials.')
        deployment = env.get('AZURE_OPENAI_DEPLOYMENT', '').strip()
        if not deployment:
            raise ValueError('AZURE_OPENAI_DEPLOYMENT is required for the azure provider.')
        url = f'wss://{parsed.netloc}/openai/v1/realtime/translations?model={quote(deployment, safe="")}'
        return Provider(name, url, env.get('AZURE_OPENAI_API_KEY', '').strip())
    raise ValueError('TRANSLATE_PROVIDER must be openai or azure.')
