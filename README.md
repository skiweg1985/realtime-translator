# SONA Live

Live-Übersetzung für Gespräche direkt im Browser.

Eine Person spricht, mehrere Personen können gleichzeitig in ihrer Sprache zuhören oder mitlesen.
Keine Accounts, keine Datenbank und keine Aufzeichnung.

**Stack:** React/Vite · FastAPI · HAProxy · Docker Compose

## Features

- Live-Übersetzung von Audio und Text
- Ein Sprecher, bis zu 31 Zuhörer und 4 Zielsprachen gleichzeitig
- Beitritt per Code, Link oder QR-Code
- Audio, Text oder Audio + Text
- Sprecherzugang per PIN
- Keine Benutzerkonten und keine Aufzeichnung
- Sessions nur im Arbeitsspeicher
- OpenAI-kompatibler Anbieter oder Azure AI als Backend

## Screenshots

| Light | Dark |
| --- | --- |
| <a href="docs/images/home-light.png"><img src="docs/images/home-light.png" width="280" alt="SONA home screen in light mode with Speak and Listen choices"></a> | <a href="docs/images/home-dark.png"><img src="docs/images/home-dark.png" width="280" alt="SONA home screen in dark mode with Speak and Listen choices"></a> |

## Quick Start

Voraussetzungen: Docker Compose und API-Zugang zu einem Anbieter für Realtime-Übersetzung.

```sh
git clone git@github.com:skiweg1985/realtime-translator.git
cd realtime-translator
cp .env.example .env
```

Für den direkten OpenAI-Zugang den API-Key in `.env` eintragen:

```env
TRANSLATE_KEY=your-key
```

Der Standard verwendet `gpt-realtime-translate` bei OpenAI. Für Azure AI oder einen anderen
kompatiblen Anbieter zuerst die [Provider-Verbindung einrichten](docs/configuration.md).

Zertifikat erstellen und Stack starten:

```sh
./setup-certs.sh YOUR_LAN_IP YOUR_MAC_HOSTNAME.local
docker compose up -d --build
```

Anschließend `https://YOUR_LAN_IP:8443` öffnen und auf dem Gerät dem
[lokalen Zertifikat vertrauen](docs/operations.md#zertifikat-vertrauen).

## Configuration

Die Verbindung wird in der serverseitigen `.env` hinterlegt. Der Browser erhält keinen Provider-Key.

| Variable | Default | Beschreibung |
| --- | --- | --- |
| `TRANSLATE_PROVIDER` | `openai` | `openai` für kompatible Anbieter oder `azure` für Azure AI |
| `TRANSLATE_KEY` | – | API-Key für den OpenAI-kompatiblen Anbieter |
| `TRANSLATE_URL` | OpenAI Realtime Translation | Vollständige WebSocket-URL des kompatiblen Anbieters |
| `AZURE_OPENAI_ENDPOINT` | – | Azure-Ressourcen-Endpunkt; bei `azure` erforderlich |
| `AZURE_OPENAI_DEPLOYMENT` | – | Azure-Deployment-Name; bei `azure` erforderlich |
| `AZURE_OPENAI_API_KEY` | – | Azure-API-Key; bei `azure` erforderlich |
| `SPEAKER_PIN` | `0000` | Vierstellige PIN zum Erstellen einer Session |
| `TRANSLATE_TRANSCRIPTION_MODEL` | `gpt-realtime-whisper` | Transkription der Originalsprache; `off` zum Abschalten |
| `TRANSLATE_NOISE_REDUCTION` | `near_field` | Rauschunterdrückung: `near_field`, `far_field` oder `off` |
| `HTTPS_PORT` / `HTTP_PORT` | `8443` / `8080` | Veröffentlichte Ports |

Beispiele und Prüfung der Verbindung: [Provider konfigurieren](docs/configuration.md).
Nach Änderungen:

```sh
docker compose up -d --force-recreate app
```

## Verwendung

### Sprecher

**Sprechen** auswählen → Sprachen festlegen → PIN eingeben → Session vorbereiten →
Code oder Link teilen → **Sprechen starten**.

| Vorbereiten | Teilen | Starten |
| --- | --- | --- |
| <a href="docs/images/speaker-prepare.png"><img src="docs/images/speaker-prepare.png" width="240" alt="Session preparation dialog with language selection and a masked speaker PIN"></a> | <a href="docs/images/speaker-share.png"><img src="docs/images/speaker-share.png" width="240" alt="Share dialog with the listener code, QR code and session link"></a> | <a href="docs/images/speaker-ready.png"><img src="docs/images/speaker-ready.png" width="240" alt="Prepared speaker session with the Start speaking button at the bottom"></a> |

Der Sprecher kann die Übertragung pausieren, fortsetzen oder die Session für alle beenden.

### Zuhörer

**Zuhören** auswählen → Session-Code eingeben oder Link/QR-Code öffnen → Sprache auswählen →
Audio/Text-Modus wählen → **Zuhören starten**.

| Beitreten | Sprache und Modus wählen | Auf den Sprecher warten |
| --- | --- | --- |
| <a href="docs/images/listener-join.png"><img src="docs/images/listener-join.png" width="240" alt="Join dialog with a session code field, QR scanner and link entry"></a> | <a href="docs/images/listener-ready.png"><img src="docs/images/listener-ready.png" width="240" alt="Listener screen with target language, Audio and Text modes, and Start listening button"></a> | <a href="docs/images/listener-waiting.png"><img src="docs/images/listener-waiting.png" width="240" alt="Connected listener waiting for the speaker, with sound and leave controls"></a> |

Zuhörer können bereits vor Beginn der Übertragung beitreten.
Die abgebildeten Codes und Links sind inaktive Beispiele.
Weitere Hinweise stehen in der [Bedienungsanleitung](docs/usage.md).

<!-- Screenshots: German UI, 390 px wide; home in both themes, guide in light. Refresh affected images together and end the capture session afterward. -->

## Limits

- 1 aktiver Sprecher
- 31 Zuhörer
- 4 Zielsprachen gleichzeitig
- 10 Minuten pro Session
- Sessions nur im RAM; ein Neustart beendet alle Sessions

SONA ist für ein **vertrauenswürdiges lokales Netzwerk** vorgesehen.
Die Nutzung des gewählten Providers verursacht API-Kosten.

## Architecture

```text
Browser
  │ HTTPS / WebSocket
  ▼
HAProxy
  ▼
FastAPI
  ├── Sessions und Verteilung an Zuhörer
  └── Realtime Translation WebSockets
           ▼
      Gewählter Provider
      (OpenAI-kompatibel oder Azure AI)
```

Audio wird im Browser als **24 kHz Mono PCM16** erfasst.
Zuhörer mit derselben Zielsprache teilen sich eine Verbindung zum Provider.

Weitere Anleitungen: [Provider einrichten](docs/configuration.md) · [Bedienung](docs/usage.md) ·
[Betrieb und Zertifikate](docs/operations.md) · [Entwicklung und Tests](docs/development.md)
