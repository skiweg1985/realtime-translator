# Realtime Translator

SONA Live is a small mobile and desktop web app for the LiteLLM Translate endpoint. One speaker shares a room link or QR code; listeners receive translated PCM audio and text together. React/Vite, FastAPI and HAProxy run in a separate local Compose stack. No login is required.

## Run locally

```sh
git clone git@github.com:skiweg1985/realtime-translator.git
cd realtime-translator
cp .env.example .env
# Set TRANSLATE_KEY to the restricted Translate key.
./setup-certs.sh YOUR_LAN_IP YOUR_MAC_HOSTNAME.local
docker compose up -d --build
```

`HTTPS_PORT` and `HTTP_PORT` in `.env` set the host ports HAProxy publishes (defaults 8443 and 8080); a `compose.override.yaml` for local tweaks is ignored by git. Open `https://YOUR_LAN_IP:8443` on devices on the same network. The start screen offers **Sprechen** and **Zuhören**. Every session gets a four-digit code that the speaker sees next to the status and in the share sheet; listeners tap **Zuhören** and type the code, scan the QR code with the in-app camera, or paste the link. The HAProxy `Permissions-Policy` allows the camera for the scanner; the gear opens settings for the app language (German or English, following the device by default) and light, dark or system appearance. As speaker, allow microphone access, tap a language in the `Deutsch → English` line to change it, then tap **Sprechen starten**. Share the listener link with the share button in the bottom dock; while live, **Mikro aus** pauses the microphone without ending the session. Listeners pick **Ton + Text**, **Ton** or **Text** in their dock, tap **Zuhören starten** and change **Ich höre** by tapping the target language; text mode adds three text sizes and a focus view that hides everything except the live translation. They can change their language while listening; queued audio is stopped and the selected language's text replaces the previous transcript. While no speaker is connected, or while the speaker has stopped, listeners see a standby line instead of an empty caption area. After stopping, the speaker can resume or tap **Sitzung beenden**, which ends the session for everyone (`POST /api/rooms/{id}/end` with the owner secret), shows listeners "Sitzung beendet" with a button back to the start page, and removes the room. The SONA Live wordmark in the top left leads back to the start page whenever no transmission is running. Headphones and AirPods use the device's selected audio route; available microphone choices appear after microphone permission. Keep Safari open and the phone unlocked; background audio capture is not guaranteed.

## Develop the frontend

With the Compose stack running, start the Vite dev server for live reload:

```sh
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/api` and the WebSocket to the HTTPS stack on port 8443, so the full speaker and listener flow works on `localhost` without installing the certificate. Rebuild the container to ship the result.

## Trust HTTPS on iPhone

1. Open `http://YOUR_LAN_IP:8080/local-ca.cer` in Safari. Port 8080 serves the app over plain HTTP as well; the microphone and camera still need the HTTPS port because browsers only grant them in a secure context.
2. Install the downloaded profile in Settings → General → VPN & Device Management.
3. Enable full trust for **Translate Local Development CA** in Settings → General → About → Certificate Trust Settings.
4. Open the HTTPS app and allow microphone access.

On desktop, import `certs/ca.crt` into your trusted certificate store. The setup script creates a private development CA and a 90-day server certificate for the supplied IP and hostname. Regenerate the server certificate after an IP change, rebuild and restart the stack. Never distribute `certs/ca.key`. Remove the development CA from devices when finished testing.

## Audio path and limits

Browser microphone → AudioWorklet (24 kHz mono PCM16) → app WebSocket → existing LiteLLM test Translate WebSocket. The app sends the dedicated key in the upstream Authorization header. The backend opens one translation connection per language currently requested by listeners and sends its audio/text only to those listeners. Listeners choosing the same language share one connection. The last listener leaving a language closes its connection. Browsers never receive the key.

Original-language captions come from the translation session itself: the channel for the room's default language requests `audio.input.transcription` with `gpt-realtime-whisper` and receives `session.input_transcript.delta` events, one word per delta, which the backend appends and sends to the speaker and every listener. That channel stays open for the whole speaking time even when nobody listens to that language, so it counts as one of the four parallel connections. The speaker sees only original-language captions; listeners see translated text and hear translated audio. No local speech model is downloaded and no second cloud connection exists. The spoken language is fixed for each room. Listener languages can change at any time; new language channels start at the current audio position and do not replay earlier speech.

Target languages are the 13 that OpenAI lists for `gpt-realtime-translate` (en, de, fr, es, it, pt, ja, zh, ru, ko, hi, id, vi) plus nl, pl, uk and ar, which translated two synthetic German clips without content errors. Turkish was removed after it turned a greeting, a date and a time reference into something else in those same clips. The list lives in `backend/main.py` (`LANGUAGES`) and `frontend/src/main.tsx` (`languages`, native display names); `tests/test_rooms.py` fails when they differ. The transcription deployment accepted every listed code as its `languages` hint, so the same list serves the spoken language.

`TRANSLATE_NOISE_REDUCTION` adds `audio.input.noise_reduction` to the translation session and defaults to `near_field` (phone held close to the mouth); `far_field` suits a room microphone. The LiteLLM test gateway passes the field through since 2026-09-09; before that it rejected every `audio.input` field with `translation_error: Additional input models are not allowed.`, which is what a listener error plus that line in the app log means if an older gateway is used. The speaker can override that default per session in the microphone sheet (`Aus`, `Nah am Mund`, `Raum`); the choice is sent with the speaker handshake, applies to every translation channel of that session and is remembered in the browser. Changing it while live sends a `settings` message; the backend reopens every translation channel with the new value at the next half-second pause (after five seconds at the latest), the old channel drains its last sentence without reporting a status, the new channel's output is held back until that sentence is over, and listeners stay connected. `off` omits the field, any other value stops the app at startup, and `/api/health` shows the active values. `TRANSLATE_TRANSCRIPTION_MODEL` names the model for `audio.input.transcription` (default `gpt-realtime-whisper`, `off` disables captions). Compared with the previous separate `azure-live-transcribe` connection on two synthetic German clips, the inline transcript had no word errors instead of 8 to 11 %, a mean lag of 0.6 s behind the audio, and its last word arrived 1.0 s after the audio ended instead of 1.9 s.

The test gateway requires `TRANSLATE_KEY` to have exactly `models: [azure-live-translate]` and `allowed_routes: [/v1/realtime/translations]`; it rejects broader keys on that route. The translation key and the test adapter setting `LITELLM_TRANSLATE_MAX_PARALLEL` must both permit four parallel translation connections, one of which carries the captions. Recreate the test gateway container after changing its environment. Health reports whether the key is configured, not upstream reachability.

The MVP supports one active speaker globally, up to 31 listeners while speaking, at most four selected target languages, and ten-minute speaker sessions. A fifth distinct language is rejected without changing an existing listener's selection; another listener can still join any of the four languages. Channel failures are reported only to that language's listeners. Reconnect or select the language again to retry. After stopping, allow the final audio to drain before restarting. Slow listeners are disconnected instead of accumulating unbounded audio. Rooms and recent text live in memory only and disappear on container restart; inactive rooms expire after two hours when new rooms are created. Links grant access to a room, so share them only with intended listeners. The speaker capability is kept in the creating browser's session storage. No database, login or persistent recording is used. This unauthenticated stack is for a trusted local network, not public Internet exposure.

Replace an expired or rotated `TRANSLATE_KEY` in `.env` and recreate the app to load it. Key expiry follows the configured LiteLLM policy. LiteLLM Translate accounting remains unknown; the upstream service incurs usage charges.

## Operate

```sh
docker compose ps
docker compose logs --tail=30 app
# Apply configuration changes:
docker compose up -d --force-recreate app
# Stop the stack:
docker compose down
```

`GET /api/health` reports endpoint configuration, cloud caption configuration and the active noise-reduction settings. There is deliberately one Uvicorn worker: rooms and fan-out are in memory. Production LiteLLM and its database are not modified by this stack.

## Validation

The initial local rollout passed a live synthetic German-to-English test through the real LiteLLM test endpoint: two listeners each received 66 audio chunks and identical translated text; local original-language captions were also returned in that initial rollout. Desktop (1440 px) and mobile (390 px) layouts were visually inspected. The browser AudioWorklet was exercised with synthetic microphone input. The user confirmed speaking on an iPhone and listening on an iPad. Safari audio recovered after restarting the browser; the listener view includes an audio diagnostic and test tone.

`tests/test_rooms.py` covers room capability exposure, foreign-origin rejection, language validation and missing-key handling. `tests/live_acceptance.py` runs a bounded provider test with a synthetic PCM16 mono 24 kHz WAV and the local CA; it incurs translation usage and needs the shared speaker slot to be free.

The cloud-caption and multilingual updates build on PR #1. Fifteen regression checks cover room policy, caption ordering/final correction, stream drain, Azure-compatible configuration, failure isolation, channel sharing, language switching, stale-message filtering, and the four-language cap. The frontend build and a mobile speaker-view inspection passed. A live synthetic German test delivered audio/text in English, French, Spanish and Italian to five listeners (77 audio chunks each), while the speaker received only original-language captions. The test also verified rejection of a fifth target language and an English-to-French switch without stale messages. These checks verify transport and delivery, not transcription accuracy; test with your own microphone and vocabulary. The two keys must retain the route/model scopes described above.

The model-configuration update adds checks for the noise-reduction setting, both `session.update` payloads, the generic listener error on a rejected session and the frontend/backend language parity (22 checks in total). A synthetic fixture can be made on macOS with `say -v Anna -o clip.aiff -f text.txt` and `afconvert -f WAVE -d LEI16@24000 -c 1 clip.aiff clip.wav`; the novelty voices produced audio that the model mistranslated in every language, so use Anna.

`python tests/live_multilingual.py http://localhost:8000 /path/to/test.wav` exercises four simultaneous target languages with five listeners, rejects a fifth language and switches one listener from English to French. It incurs model usage and requires the speaker slot to be free. Use a PCM16 mono 24 kHz WAV.
