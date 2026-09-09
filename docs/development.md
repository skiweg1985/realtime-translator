# Entwicklung und Tests

[Zur README](../README.md)

## Frontend starten

```sh
cd frontend
npm install
npm run dev
```

Das Frontend läuft unter `http://localhost:5173` und leitet API- und WebSocket-Anfragen an den
laufenden Compose-Stack auf Port 8443 weiter. Der Entwicklungsproxy darf den Host-Header nicht
umschreiben, da das Backend ihn mit dem Origin-Host vergleicht.

## Automatisierte Tests

Im Projektverzeichnis:

```sh
python3 -m pip install -r backend/requirements.txt pytest httpx
mkdir -p backend/static
PYTHONPATH=backend python3 -m pytest tests/ -q
```

Diese Tests benötigen keinen Provider-Zugang. Die Sprachlisten in `backend/main.py` und
`frontend/src/main.tsx` müssen übereinstimmen; ein Test prüft das.

## Live-Tests

`tests/live_acceptance.py` und `tests/live_multilingual.py` greifen über die App auf den
konfigurierten Provider zu. Sie verursachen API-Kosten und benötigen einen freien Sprecherplatz.
Die Skripte verwenden unterschiedliche Verbindungswege:

- [Einsprachiger Live-Test](../tests/live_acceptance.py): HTTPS-Basis-URL, WAV-Datei und CA-Datei als Argumente.
- [Mehrsprachiger Live-Test](../tests/live_multilingual.py): HTTP-Basis-URL des Backends und WAV-Datei als Argumente; benötigt direkten Backend-Zugriff.

Setze `SPEAKER_PIN` in der Umgebung des Testprozesses auf die Server-PIN; standardmäßig gilt `0000`.
Die Skripte benötigen eine WAV-Datei mit PCM16, Mono und 24 kHz. Auf macOS lässt sich aus einer
Textdatei eine Testaufnahme erzeugen:

```sh
say -v Anna -o clip.aiff -f text.txt
afconvert -f WAVE -d LEI16@24000 -c 1 clip.aiff clip.wav
```
