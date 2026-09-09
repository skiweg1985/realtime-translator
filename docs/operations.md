# Betrieb

[Zur README](../README.md)

## Zertifikat vertrauen

Auf dem iPhone:

1. `http://YOUR_LAN_IP:8080/local-ca.cer` in Safari öffnen.
2. Das Profil unter Einstellungen → Allgemein → VPN und Geräteverwaltung installieren.
3. Unter Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen das volle Vertrauen
   für **Translate Local Development CA** aktivieren.

Auf Desktop-Geräten stattdessen `certs/ca.crt` importieren und als vertrauenswürdig einstufen.
Die URLs verwenden die Standardports; bei geänderten Ports die konfigurierten Werte einsetzen.
`certs/ca.key` niemals weitergeben.

Das Serverzertifikat gilt 90 Tage für die an `setup-certs.sh` übergebene IP und den Hostnamen.
Bei Ablauf oder einer geänderten IP erneut erzeugen und den HTTPS-Container neu erstellen:

```sh
./setup-certs.sh YOUR_LAN_IP YOUR_MAC_HOSTNAME.local
docker compose up -d --force-recreate https
```

## Zustand und Diagnose

```sh
docker compose ps
docker compose logs --tail=30 app
```

`GET /api/health` zeigt den Provider, das Vorhandensein seines Keys, die Konfiguration der
Transkription und die Rauschunterdrückung. Der Health Check prüft keine Verbindung zum Provider.
Wie sich Zugangsdaten und Modellzugriff prüfen lassen, steht unter
[Provider konfigurieren](configuration.md#übernehmen-und-prüfen).

## Sessions und Zugriff

Sessions, Texte und Sprecherzugang liegen nur im Arbeitsspeicher. Ein Neustart beendet alle
Sessions. Inaktive Räume, die älter als zwei Stunden sind, werden beim Erstellen einer weiteren
Session entfernt. Ein vorbereiteter Link ist deshalb keine dauerhafte Reservierung.

Ein Link oder Session-Code gewährt Zuhörerzugriff. Teile ihn nur mit den vorgesehenen Personen.
Die gemeinsame Sprecher-PIN schützt das Erstellen von Sessions und ist vom öffentlichen
Zuhörercode getrennt. Zuhörer benötigen keine PIN.

Der Server läuft mit genau einem Uvicorn-Worker, da Session-Zustand und Verteilung an Zuhörer
im Prozessspeicher liegen. Zusätzliche Worker würden diesen Zustand nicht teilen.

