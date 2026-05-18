#!/bin/bash
# Überwacht reboot.flag und führt sofortigen Systemneustart aus.
# Wird beim Boot automatisch gestartet (@reboot cron).
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
while true; do
    if grep -q requested_at "$INSTALL_DIR/reboot.flag" 2>/dev/null; then
        echo '{}' > "$INSTALL_DIR/reboot.flag"
        sudo /sbin/reboot -i 2>/dev/null || sudo systemctl reboot -i
    fi
    sleep 3
done
