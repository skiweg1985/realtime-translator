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
Transkription und die Rauschunterdrückung. Wie sich Zugangsdaten und Modellzugriff von Hand prüfen
lassen, steht unter [Provider konfigurieren](configuration.md#übernehmen-und-prüfen).

Dazu kommt `translation_reachable` mit `unknown`, `ok`, `unreachable` oder `unconfigured`. Dahinter
steht ein echter Handshake zum Provider, der eine Übersetzungssitzung öffnet und sofort wieder
schließt; er prüft also Route, Key und Modell, sendet aber kein Audio. Das Ergebnis gilt dreißig
Sekunden und wird von allen Abrufen geteilt, egal wie viele Browser gerade pollen. Der Handshake
läuft im Hintergrund und hat fünf Sekunden Zeit, `/api/health` antwortet währenddessen sofort mit
dem letzten bekannten Wert. Der erste Abruf nach dem Start liefert deshalb `unknown`. Solange
jemand überträgt, wird nicht geprüft: die offenen Kanäle sagen mehr als ein Handshake, und der
Provider bekommt keine zusätzliche Sitzung.

Die Oberfläche zeigt `unreachable` im Dialog **Session vorbereiten** und in der Sprecheransicht vor
dem Start. Beides ist ein Hinweis, keine Sperre: eine Session lässt sich weiterhin anlegen und
starten, denn ein Fehlschlag der Prüfung darf die Nutzung nicht verhindern.

## Sessions und Zugriff

Sessions, Texte und Sprecherzugang liegen nur im Arbeitsspeicher. Ein Neustart beendet alle
Sessions. Inaktive Räume, die älter als zwei Stunden sind, werden beim Erstellen einer weiteren
Session entfernt. Ein vorbereiteter Link ist deshalb keine dauerhafte Reservierung.

Ein Link oder Session-Code gewährt Zuhörerzugriff. Teile ihn nur mit den vorgesehenen Personen.
Die gemeinsame Sprecher-PIN schützt das Erstellen von Sessions und ist vom öffentlichen
Zuhörercode getrennt. Zuhörer benötigen keine PIN.

Der Server läuft mit genau einem Uvicorn-Worker, da Session-Zustand und Verteilung an Zuhörer
im Prozessspeicher liegen. Zusätzliche Worker würden diesen Zustand nicht teilen.

## Wenn der Übersetzungsdienst ausfällt

Jede Zielsprache hat eine eigene Verbindung zum Provider. Bricht eine davon ab oder kommt sie
nicht zustande, versucht der Server es sofort noch zweimal, nach einer und nach drei Sekunden. Die
Zuhörer dieser Sprache sehen währenddessen **Verbindet**, der bisherige Text bleibt stehen. In den
Logs steht dazu `Translation channel <Sprache> retries in <n>s`.

Antwortet der Provider gar nicht, statt die Verbindung abzulehnen, läuft jeder Versuch in einen
Handshake-Timeout von acht Sekunden. Bis zur Meldung vergehen dann knapp dreißig Sekunden. Damit
der Sprecher nicht so lange im Unklaren bleibt, steht bei ihm schon nach drei Sekunden ohne
laufenden Kanal, dass die Verbindung noch nicht steht und gerade nichts übersetzt wird.

Scheitert auch der dritte Versuch, meldet der Server die Sprache als ausgefallen und protokolliert
`Translation channel <Sprache> failed`. Aufgegeben wird sie damit nicht: der Kanal versucht es
weiter, nach fünfzehn, nach dreißig und danach alle sechzig Sekunden, solange die Übertragung
läuft. Kommt der Provider zurück, geht die Sprache von selbst wieder live und alle Meldungen
verschwinden. Ein Ausfall von einigen Minuten kostet also nicht die restliche Session, und der
Provider bekommt dabei höchstens einen Versuch pro Minute und Sprache, unabhängig davon, wie viele
Zuhörer warten.

Wer nicht warten will, kann den nächsten Versuch vorziehen. Zuhörer haben dafür unter **Übersetzung
unterbrochen** die Schaltfläche **Erneut versuchen**, der Sprecher in seiner Meldung **Jetzt
versuchen**. Beide wecken denselben Kanal, ohne einen zweiten zu öffnen, und beide teilen sich eine
Sperre von zehn Sekunden je Sprache. Ein einzelner Zuhörer kann also durch wiederholtes Tippen
keine zusätzliche Last auf dem Provider erzeugen; nur der Start einer Übertragung setzt die Sperre
zurück, weil das der eigene Neuanlauf des Sprechers ist.

Ein Neuversuch ist keine Entwarnung: die Meldung beim Sprecher hängt daran, ob eine Sprache
tatsächlich übersetzt, nicht daran, ob gerade ein Versuch läuft. Sie verschwindet erst, wenn der
Kanal wieder Text liefert.

