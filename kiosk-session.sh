#!/bin/bash
# Erika Kiosk Session — startet direkt nach Auto-Login
# Läuft anstelle von LXDE: kein Desktop, kein Panel, kein Flash

# Sofort schwarzen Hintergrund setzen
xsetroot -solid black

# Mauszeiger ausblenden wenn idle (2 Sekunden)
command -v unclutter &>/dev/null && unclutter -idle 2 -root &

# Minimaler Window-Manager (Chromium braucht einen)
openbox &

# Chromium-Binary ermitteln
CHROMIUM=$(command -v chromium-browser 2>/dev/null || command -v chromium 2>/dev/null)
if [ -z "$CHROMIUM" ]; then
    xmessage "Chromium nicht gefunden" &
    exit 1
fi

# Warten bis Erika tatsächlich antwortet (statt blindem sleep)
until curl -sk --max-time 2 https://localhost:8000/health > /dev/null 2>&1; do
    sleep 1
done

# Chromium im Kiosk-Modus starten
exec "$CHROMIUM" \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --autoplay-policy=no-user-gesture-required \
    --ignore-certificate-errors \
    --password-store=basic \
    https://localhost:8000/display
