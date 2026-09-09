# SONA Live

One speaker, many listeners: live translated audio and text in the browser. React/Vite frontend, FastAPI backend and HAProxy for HTTPS, all in one Compose stack. No login, no database, no recording.

## Setup

```sh
git clone git@github.com:skiweg1985/realtime-translator.git
cd realtime-translator
cp .env.example .env               # enter TRANSLATE_KEY, see below
./setup-certs.sh YOUR_LAN_IP YOUR_MAC_HOSTNAME.local
docker compose up -d --build
```

Then open `https://YOUR_LAN_IP:8443` on any device in the same network.

## Configuration

Everything lives in `.env`. **Only `TRANSLATE_KEY` has to be filled in**, the rest has working defaults.

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `TRANSLATE_KEY` | **yes** | – | LiteLLM Virtual Key for the Translate route |
| `TRANSLATE_URL` | no | `wss://litellm-test.simplicity.ag/v1/realtime/translations?model=azure-live-translate` | Upstream WebSocket |
| `TRANSLATE_TRANSCRIPTION_MODEL` | no | `gpt-realtime-whisper` | Original-language captions; `off` disables them |
| `TRANSLATE_NOISE_REDUCTION` | no | `near_field` | `near_field`, `far_field` or `off`; the speaker can override it per session in the app |
| `HTTPS_PORT` / `HTTP_PORT` | no | `8443` / `8080` | Host ports published by HAProxy |

The key must be scoped to exactly `models: [azure-live-translate]` and `allowed_routes: [/v1/realtime/translations]`; the gateway rejects broader keys on that route. It must also allow four parallel connections, as must `LITELLM_TRANSLATE_MAX_PARALLEL` on the gateway. Browsers never see the key. After replacing it: `docker compose up -d --force-recreate app`.

## Trust the certificate on iPhone

1. Open `http://YOUR_LAN_IP:8080/local-ca.cer` in Safari.
2. Install the profile in Settings → General → VPN & Device Management.
3. Enable full trust for **Translate Local Development CA** in Settings → General → About → Certificate Trust Settings.

On desktop, import `certs/ca.crt` instead. The server certificate is valid 90 days and covers the IP and hostname you passed to `setup-certs.sh`; rerun it after an IP change, then rebuild. Never distribute `certs/ca.key`.

## Use

**Speaker:** tap **Sprechen**, allow the microphone, optionally tap a language in the `Deutsch → English` line, then **Sprechen starten**. Share the link or the four-digit code from the dock. **Mikro aus** pauses without ending; **Sitzung beenden** closes the session for everyone.

**Listener:** tap **Zuhören**, enter the code, scan the QR code or open the link, then **Zuhören starten**. The dock switches between **Audio + Text**, **Audio** and **Text**; text mode adds three sizes and a focus view. The language can be changed at any time.

## How it works

Microphone → AudioWorklet (24 kHz mono PCM16) → app WebSocket → one upstream translation connection per requested target language. Listeners on the same language share a connection. The channel for the room's default language additionally requests `audio.input.transcription` and delivers the original-language captions, so it stays open for the whole speaking time.

Target languages: the 13 official ones for `gpt-realtime-translate` (en, de, fr, es, it, pt, ja, zh, ru, ko, hi, id, vi) plus nl, pl, uk and ar. The list lives in `backend/main.py` and `frontend/src/main.tsx`; a test fails when the two differ.

## Limits

One active speaker globally, up to 31 listeners, at most four target languages (one of them carries the captions), ten minutes per session. Rooms and text live in memory only and disappear when the container restarts. A link grants access to a room, so share it only with intended listeners. This stack is unauthenticated and belongs on a trusted local network, not on the open Internet. The upstream service incurs usage charges.

## Develop

```sh
cd frontend && npm install && npm run dev
```

`http://localhost:5173` proxies `/api` and the WebSocket to the running stack on 8443, so the full flow works without installing the certificate.

## Test

```sh
mkdir -p backend/static && PYTHONPATH=backend python3 -m pytest tests/ -q
```

`tests/live_acceptance.py` and `tests/live_multilingual.py` run against the real endpoint, incur usage and need the speaker slot free. They want a PCM16 mono 24 kHz WAV, which macOS can produce with `say -v Anna -o clip.aiff -f text.txt` followed by `afconvert -f WAVE -d LEI16@24000 -c 1 clip.aiff clip.wav`.

## Operate

```sh
docker compose ps
docker compose logs --tail=30 app
docker compose up -d --force-recreate app   # apply .env changes
docker compose down
```

`GET /api/health` reports whether the key and captions are configured and which noise reduction is active. There is deliberately one Uvicorn worker: rooms and fan-out are in memory.
