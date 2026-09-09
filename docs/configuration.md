# Provider konfigurieren

[Zur README](../README.md)

Wähle einen Provider in der `.env` im Projektverzeichnis. Docker Compose lädt diese Datei in den
App-Container. Zugangsdaten werden ausschließlich auf dem Server hinterlegt, nicht in der
Browseroberfläche. Alle verfügbaren Variablen stehen in der [Beispielkonfiguration](../.env.example).

## OpenAI oder kompatibler Anbieter

Erstelle beim Anbieter einen API-Key mit Zugriff auf das Übersetzungsmodell. Für OpenAI:

```env
TRANSLATE_PROVIDER=openai
TRANSLATE_URL=wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate
TRANSLATE_KEY=your-provider-api-key
```

Für einen anderen Anbieter ersetze die vollständige WebSocket-URL einschließlich Modellnamen und
trage dessen API-Key ein. Der Endpunkt muss das
[Realtime-Translation-Protokoll](https://developers.openai.com/api/docs/guides/realtime-translation)
und Bearer-Authentifizierung unterstützen. Chat-Completions-Kompatibilität allein reicht nicht aus.
Die URL muss mit `wss://` beginnen und darf keine eingebetteten Zugangsdaten oder Fragmente enthalten.

Ohne `TRANSLATE_PROVIDER` gilt `openai`; ohne `TRANSLATE_URL` gilt die oben gezeigte OpenAI-URL.
Bestehende Konfigurationen mit eigener `TRANSLATE_URL` und `TRANSLATE_KEY` bleiben gültig.

## Azure AI

Stelle `gpt-realtime-translate` in einer Azure-OpenAI- beziehungsweise Microsoft-Foundry-Ressource
bereit. Kopiere Endpunkt und API-Key aus **Keys and Endpoint** und den Deployment-Namen aus
**Model deployments**:

```env
TRANSLATE_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=YOUR-TRANSLATION-DEPLOYMENT
AZURE_OPENAI_API_KEY=your-azure-api-key
```

Der Endpunkt muss eine HTTPS-Adresse ohne Pfad, Query oder eingebettete Zugangsdaten sein.
Verwende den selbst vergebenen Deployment-Namen; dieser kann vom Modellnamen abweichen.
Die App ergänzt `/openai/v1/realtime/translations?model=<deployment>` und sendet den Key im
Header `api-key`. Microsoft-Entra-Authentifizierung ist nicht implementiert.
Die [Azure-Dokumentation](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio-websockets#translate-audio-in-real-time)
beschreibt Verfügbarkeit und Voraussetzungen des Deployments.

Bei `azure` werden `TRANSLATE_URL` und `TRANSLATE_KEY` ignoriert. Bei `openai` werden die
Azure-Variablen ignoriert. Ein fehlender Key des gewählten Providers wird nicht durch den Key
des anderen Providers ersetzt.

## Übernehmen und prüfen

```sh
docker compose up -d --force-recreate app
```

Öffne `https://YOUR_LAN_IP:8443/api/health`. `translation_provider` zeigt den gewählten Provider.
`translation_configured: true` bedeutet nur, dass dessen Key vorhanden ist. Die Angabe bestätigt
weder gültige Zugangsdaten noch Modellzugriff.

Bereite eine Session vor und starte die Übertragung, um Audio und Untertitel zu prüfen.
Dieser Test verursacht API-Nutzungskosten. Beide Provider-Modi sind automatisiert mit simulierten
Verbindungen geprüft; ein direkter Live-Test gegen Azure steht noch aus.

Ein unbekannter Provider oder ein ungültiger Endpunkt verhindert den App-Start. Ohne Key startet
die App, aber es lassen sich keine Sessions erstellen. Bei Verbindungsfehlern prüfe die
App-Logs, die URL, den Modell- beziehungsweise Deployment-Namen und die Berechtigungen des Keys.

## Untertitel und Rauschunterdrückung

Der Provider muss bis zu vier gleichzeitige Übersetzungsverbindungen zulassen.
Originalsprachliche Untertitel werden über `audio.input.transcription` auf dem Kanal der
Session-Zielsprache angefordert. Dieser Kanal bleibt während der Übertragung geöffnet und zählt
zum Limit von vier Zielsprachen.

`TRANSLATE_TRANSCRIPTION_MODEL` muss ein vom Provider unterstütztes Transkriptionsmodell benennen.
Unterstützt er diese Funktion nicht, setze `TRANSLATE_TRANSCRIPTION_MODEL=off`.
Mit `TRANSLATE_NOISE_REDUCTION=off` lässt sich auch die Rauschunterdrückung abschalten.
`near_field` ist für ein nah gehaltenes Mikrofon gedacht, `far_field` für ein Raummikrofon.
Der Sprecher kann diese Einstellung pro Session ändern.

## Sprecher-PIN

`SPEAKER_PIN` muss aus genau vier ASCII-Ziffern bestehen. Führende Nullen bleiben erhalten.
Ohne die Variable gilt `0000`; ein leerer oder ungültiger Wert verhindert den Start.
Die PIN wird serverseitig geprüft und nicht in geteilte Links aufgenommen.
Nach einer Änderung muss der App-Container neu erstellt werden.
