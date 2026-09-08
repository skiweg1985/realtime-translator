# Realtime Translator

A small mobile and desktop web app for the LiteLLM Translate endpoint. One speaker shares a room link or QR code; listeners receive translated PCM audio and text together. React/Vite, FastAPI and HAProxy run in a separate local Compose stack. No login is required.

## Run locally

```sh
git clone git@github.com:skiweg1985/realtime-translator.git
cd realtime-translator
cp .env.example .env
# Set TRANSLATE_KEY to a dedicated Translate-only Virtual Key.
./setup-certs.sh YOUR_LAN_IP YOUR_MAC_HOSTNAME.local
docker compose up -d --build
```

Open `https://YOUR_LAN_IP:8443` on devices on the same network. Allow microphone access, choose the source/target languages and tap **Sprechen starten**. Share the listener link using the link button. Listeners tap **Live zuhören** to enable audio playback. Headphones and AirPods use the device's selected audio route; available microphone choices appear after microphone permission. Keep Safari open and the phone unlocked; background audio capture is not guaranteed.

## Trust HTTPS on iPhone

1. Open `http://YOUR_LAN_IP:8080/local-ca.cer` in Safari. This HTTP port serves only the public certificate.
2. Install the downloaded profile in Settings → General → VPN & Device Management.
3. Enable full trust for **Translate Local Development CA** in Settings → General → About → Certificate Trust Settings.
4. Open the HTTPS app and allow microphone access.

On desktop, import `certs/ca.crt` into your trusted certificate store. The setup script creates a private development CA and a 90-day server certificate for the supplied IP and hostname. Regenerate the server certificate after an IP change, rebuild and restart the stack. Never distribute `certs/ca.key`. Remove the development CA from devices when finished testing.

## Audio path and limits

Browser microphone → AudioWorklet (24 kHz mono PCM16) → app WebSocket → existing LiteLLM test Translate WebSocket. The app sends the dedicated key in the upstream Authorization header. Translated audio and text are broadcast to listeners. Browsers never receive the key.

Original-language captions use local faster-whisper `tiny` on the Docker CPU, with several seconds of delay. Its model downloads once into the `models` volume. This is separate from translation: all translated audio/text comes from LiteLLM/Azure. Tiny-model original captions may contain errors. Language is fixed for each room; return to the home page to choose another language.

The MVP supports one active speaker globally (matching the shared Virtual Key limit), up to 31 listeners while speaking, and ten-minute upstream sessions. After stopping, allow the final audio to drain before restarting. Slow listeners are disconnected instead of accumulating unbounded audio. Rooms and recent text live in memory only and disappear on container restart; inactive rooms expire after two hours when new rooms are created. Links grant access to a room, so share them only with intended listeners. The speaker capability is kept in the creating browser's session storage. No database, login or persistent recording is used. This unauthenticated stack is for a trusted local network, not public Internet exposure.

The locally provisioned key expires after seven days. Replace `TRANSLATE_KEY` in `.env` and recreate the app when it expires. LiteLLM Translate accounting remains unknown; the upstream service incurs usage charges.

## Operate

```sh
docker compose ps
docker compose logs --tail=30 app
# Apply configuration changes:
docker compose up -d --force-recreate app
# Stop without deleting the downloaded model:
docker compose down
```

`GET /api/health` reports endpoint configuration and local caption-model readiness. There is deliberately one Uvicorn worker: rooms and fan-out are in memory. Production LiteLLM and its database are not modified by this stack.

## Validation

The initial local rollout passed a live synthetic German-to-English test through the real LiteLLM test endpoint: two listeners each received 66 audio chunks and identical translated text; local original-language captions were also returned. Desktop (1440 px) and mobile (390 px) layouts were visually inspected. The browser AudioWorklet was exercised with synthetic microphone input. The user confirmed speaking on an iPhone and listening on an iPad. Safari audio recovered after restarting the browser; the listener view includes an audio diagnostic and test tone.

`tests/test_rooms.py` covers room capability exposure, foreign-origin rejection, language validation and missing-key handling. `tests/live_acceptance.py` runs a bounded provider test with a synthetic PCM16 mono 24 kHz WAV and the local CA; it incurs translation usage and needs the shared speaker slot to be free.
