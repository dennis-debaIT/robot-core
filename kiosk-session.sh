#!/bin/bash
# Erika Kiosk Session — startet direkt nach Auto-Login
# Kein LXDE, kein Desktop, kein Flash

# Display und PATH explizit setzen — im LightDM-Autologin-Kontext
# sind diese Variablen nicht immer korrekt gesetzt
export DISPLAY="${DISPLAY:-:0}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Warten bis X-Display bereit ist (max 10s)
for _i in $(seq 1 10); do
    xset -display "$DISPLAY" q &>/dev/null && break
    sleep 1
done

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

# Touchegg für Wisch-Gesten (3-Finger-Wisch rechts → zu Erika)
command -v touchegg &>/dev/null && touchegg &

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
        --touch-events=enabled \
        --enable-smooth-scrolling \
        --homepage=https://localhost:8000/display \
        https://localhost:8000/display
    sleep 2
done
