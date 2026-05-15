# Backend-Grenze: Device vs. Cloud

## Ziel

Dieses Projekt bleibt vorerst das lokale `device backend` für `Erika`.

Es soll später zusammen mit einem separaten `cloud backend` arbeiten, aber nicht mit diesem verschmelzen.

## Aktuelle Entscheidung

Das bestehende Backend ist zuständig für:

- lokalen Robot-Core
- lokale Gerätekonsole
- lokale Datenhaltung
- Hardware-nahe Zustände
- Offline-Fähigkeit
- lokale Audit- und Betriebsdaten

Das spätere `cloud backend` soll separat betrieben werden und zuständig sein für:

- Tenant-Verwaltung
- Benutzer und Rollen
- Geräte-Registry
- Flottensteuerung
- Updates
- Abrechnung
- Service und Diagnose
- zentrale LLM-Konfiguration

## Bereits vorbereitete Andockstellen

Im lokalen Backend gibt es jetzt zwei explizite Endpunkte:

- `GET /device/identity`
- `GET /sync/contract`

Diese Endpunkte dokumentieren die Grenze zwischen lokalem Gerät und späterer Plattform.

## Device Identity

Das lokale Backend hält eine erste Geräteidentität in `system_state`:

- `device_id`
- `device_secret`
- `tenant_id`
- `tenant_binding`
- `cloud_endpoint`
- `sync_enabled`
- `sync_mode`
- `sync_cursor`

Aktuell sind das noch lokale Platzhalter für die spätere Werks- und Cloud-Anbindung.

## Sync-Vertrag

Der lokale Sync-Vertrag geht aktuell von diesem Modell aus:

### Lokal als Source of Truth

- Robot-Zustand
- Personenprofile
- Memories
- Gesprächskontext
- Hardware-Ereignisse
- Audit-Ereignisse

### Zentral als Source of Truth

- Tenant-Verwaltung
- Benutzerkonten
- Geräte-Registry
- Abrechnung
- Flotten-Updates
- zentrale LLM-Konfiguration

## Grundregeln

- Der lokale Robot-Core bleibt offline arbeitsfähig.
- Direkte Hardware-Steuerung bleibt lokal auf dem Gerät.
- Das Cloud-Backend ist organisatorisch und betrieblich getrennt.
- Private Personendaten werden nicht automatisch für Service-Rollen freigeschaltet.

## Nächste sinnvolle Folgearbeiten

1. lokales Rollenmodell vorbereiten
2. `device_id` und `tenant_id` schrittweise in Kernobjekte einziehen
3. echte Provisioning-Payload definieren
4. erstes separates `cloud backend` scaffolden, wenn die lokale Seite stabil genug ist
