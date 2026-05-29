#!/bin/bash
# Erika Kiosk Session — startet direkt nach Auto-Login
# Kein LXDE, kein Desktop, kein Flash

# Sofort schwarzen Hintergrund
xsetroot -solid black

# Mauszeiger verstecken
command -v unclutter &>/dev/null && unclutter -idle 2 -root &

# Minimaler Window-Manager
openbox --config-file "$HOME/.config/openbox/erika-rc.xml" &

# Splash-Bild anzeigen während Erika startet (selbes Bild wie beim Boot)
SPLASH_IMG="/usr/share/plymouth/themes/erika/logo.png"
if command -v feh &>/dev/null && [ -f "$SPLASH_IMG" ]; then
    feh --bg-fill "$SPLASH_IMG"
fi

# Chromium-Binary ermitteln
CHROMIUM=$(command -v chromium-browser 2>/dev/null || command -v chromium 2>/dev/null)
if [ -z "$CHROMIUM" ]; then
    xmessage "Chromium nicht gefunden" &
    exit 1
fi

# Warten bis Erika tatsächlich antwortet
until curl -sk --max-time 2 https://localhost:8000/health > /dev/null 2>&1; do
    sleep 1
done

# Chromium im Loop: wenn geschlossen (z.B. nach HA-Navigation), startet Erika neu
# Alt+Home navigiert innerhalb Chromium zurück zur Erika-Homepage
# Super+H (Windows-Taste+H) beendet Chromium → Loop startet Erika neu
while true; do
    "$CHROMIUM" \
        --kiosk \
        --noerrdialogs \
        --disable-infobars \
        --autoplay-policy=no-user-gesture-required \
        --ignore-certificate-errors \
        --disable-translate \
        --password-store=basic \
        --homepage=https://localhost:8000/display \
        https://localhost:8000/display
    sleep 2
done
