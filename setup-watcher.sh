#!/bin/bash
# Überwacht Setup-Flags und führt Host-Aktionen aus.
# Wird beim Boot automatisch gestartet (@reboot cron).
set -e
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

log() { echo "[setup-watcher] $1" >> "$INSTALL_DIR/setup-watcher.log" 2>&1; }

# WiFi-Scan alle 15 Sekunden erneuern
_wifi_scan() {
    local result
    result=$(nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list 2>/dev/null | sort -t: -k2 -rn | head -30)
    local json='{"networks":['
    local first=1
    while IFS=: read -r ssid signal security; do
        [ -z "$ssid" ] && continue
        [ "$first" -eq 0 ] && json+=","
        json+="{\"ssid\":\"$(echo "$ssid" | sed 's/"/\\"/g')\",\"signal\":$signal,\"security\":\"$security\"}"
        first=0
    done <<< "$result"
    json+=']}'
    echo "$json" > "$INSTALL_DIR/wifi-scan.json" 2>/dev/null || true
}

_last_wifi_scan=0

while true; do
    now=$(date +%s)

    # Host-IP für den Container bereitstellen
    _host_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -n "$_host_ip" ] && echo "$_host_ip" > "$INSTALL_DIR/host-ip.txt" 2>/dev/null || true

    # WiFi-Scan alle 15s
    if [ $((now - _last_wifi_scan)) -ge 15 ]; then
        _wifi_scan
        _last_wifi_scan=$now
    fi

    # Zeitzone setzen
    if grep -q '"timezone"' "$INSTALL_DIR/timezone.flag" 2>/dev/null; then
        tz=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('timezone',''))" < "$INSTALL_DIR/timezone.flag" 2>/dev/null || true)
        echo '{}' > "$INSTALL_DIR/timezone.flag"
        if [ -n "$tz" ]; then
            timedatectl set-timezone "$tz" 2>/dev/null && log "Zeitzone gesetzt: $tz" || log "Zeitzone fehlgeschlagen: $tz"
            # Auch in .env aktualisieren für Docker-Container
            sed -i "s|^TZ=.*|TZ=$tz|" "$INSTALL_DIR/.env" 2>/dev/null || echo "TZ=$tz" >> "$INSTALL_DIR/.env"
        fi
    fi

    # Hostname setzen
    if grep -q '"hostname"' "$INSTALL_DIR/hostname.flag" 2>/dev/null; then
        hn=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('hostname',''))" < "$INSTALL_DIR/hostname.flag" 2>/dev/null || true)
        echo '{}' > "$INSTALL_DIR/hostname.flag"
        if [ -n "$hn" ]; then
            hostnamectl set-hostname "$hn" 2>/dev/null && log "Hostname gesetzt: $hn" || log "Hostname fehlgeschlagen: $hn"
        fi
    fi

    # WLAN konfigurieren
    if grep -q '"ssid"' "$INSTALL_DIR/wlan.flag" 2>/dev/null; then
        ssid=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ssid',''))" < "$INSTALL_DIR/wlan.flag" 2>/dev/null || true)
        pass=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('password',''))" < "$INSTALL_DIR/wlan.flag" 2>/dev/null || true)
        echo '{}' > "$INSTALL_DIR/wlan.flag"
        if [ -n "$ssid" ]; then
            log "Verbinde mit WLAN: $ssid"
            if [ -n "$pass" ]; then
                nmcli dev wifi connect "$ssid" password "$pass" 2>/dev/null && log "WLAN verbunden: $ssid" || log "WLAN fehlgeschlagen: $ssid"
            else
                nmcli dev wifi connect "$ssid" 2>/dev/null && log "WLAN verbunden: $ssid" || log "WLAN fehlgeschlagen: $ssid"
            fi
        fi
    fi

    # HA installieren
    if grep -q '"requested_at"' "$INSTALL_DIR/ha-install.flag" 2>/dev/null; then
        echo '{}' > "$INSTALL_DIR/ha-install.flag"
        log "Starte Home Assistant Installation…"
        cd "$INSTALL_DIR"
        docker compose --profile ha up -d homeassistant >> "$INSTALL_DIR/setup-watcher.log" 2>&1 || log "HA-Start fehlgeschlagen"
        # HACS installieren sobald HA bereit
        sleep 30
        for i in $(seq 1 30); do
            if curl -sk "http://localhost:8123/api/" &>/dev/null; then
                log "HA bereit — installiere HACS"
                docker exec homeassistant bash -c "wget -q -O - https://get.hacs.xyz | bash -" \
                    >> "$INSTALL_DIR/setup-watcher.log" 2>&1 \
                    && docker restart homeassistant \
                    && log "HACS installiert" || log "HACS fehlgeschlagen"
                break
            fi
            sleep 10
        done
    fi

    # Komponenten installieren (custom_components Download)
    if grep -q '"components"' "$INSTALL_DIR/components.flag" 2>/dev/null; then
        components=$(python3 -c "import sys,json; print(' '.join(json.load(sys.stdin).get('components',[])))" < "$INSTALL_DIR/components.flag" 2>/dev/null || true)
        echo '{}' > "$INSTALL_DIR/components.flag"
        log "Installiere Komponenten: $components"
        mkdir -p "$INSTALL_DIR/ha_config/custom_components"
        for comp in $components; do
            case "$comp" in
                ring_mqtt)
                    log "Installiere ring-mqtt..."
                    curl -sfSL -o /tmp/ring-mqtt.zip \
                        "https://github.com/tsightler/ring-mqtt/releases/latest/download/ring-mqtt.zip" 2>/dev/null \
                        && unzip -q -o /tmp/ring-mqtt.zip -d /tmp/ring-mqtt-extract 2>/dev/null \
                        && cp -r /tmp/ring-mqtt-extract/custom_components/ring_mqtt "$INSTALL_DIR/ha_config/custom_components/" 2>/dev/null \
                        && log "ring-mqtt installiert" || log "ring-mqtt fehlgeschlagen"
                    ;;
                dreame_vacuum)
                    log "Installiere Dreame Vacuum..."
                    curl -sfSL -o /tmp/dreame.zip \
                        "https://github.com/Tasshack/dreame-vacuum/releases/latest/download/dreame_vacuum.zip" 2>/dev/null \
                        && unzip -q -o /tmp/dreame.zip -d "$INSTALL_DIR/ha_config/custom_components/dreame_vacuum" 2>/dev/null \
                        && log "Dreame installiert" || log "Dreame fehlgeschlagen"
                    ;;
                worxlandroid)
                    log "Installiere Worx Landroid..."
                    curl -sfSL -o /tmp/worx.zip \
                        "https://github.com/lubeda/EcovacsHomeassistant/releases/latest/download/worxlandroid.zip" 2>/dev/null \
                        && unzip -q -o /tmp/worx.zip -d "$INSTALL_DIR/ha_config/custom_components/worxlandroid" 2>/dev/null \
                        && log "Worx installiert" || log "Worx fehlgeschlagen"
                    ;;
                volkswagen_we_connect)
                    log "Installiere VW WeConnect..."
                    curl -sfSL -o /tmp/vw.zip \
                        "https://github.com/mitch-dc/ha-vwsfriend/archive/refs/heads/main.zip" 2>/dev/null \
                        && unzip -q -o /tmp/vw.zip -d /tmp/vw-extract 2>/dev/null \
                        && cp -r /tmp/vw-extract/*/custom_components/* "$INSTALL_DIR/ha_config/custom_components/" 2>/dev/null \
                        && log "VW installiert" || log "VW fehlgeschlagen"
                    ;;
            esac
        done
        # HA neu starten damit neue Komponenten geladen werden
        docker restart homeassistant >> "$INSTALL_DIR/setup-watcher.log" 2>&1 || true
        log "Komponenten-Installation abgeschlossen"
    fi

    # Drucker-Bridge starten
    if grep -q '"requested_at"' "$INSTALL_DIR/printer-start.flag" 2>/dev/null; then
        _printer_ip=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('printer_ip',''))" < "$INSTALL_DIR/printer-start.flag" 2>/dev/null || true)
        _mqtt_host=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mqtt_host',''))" < "$INSTALL_DIR/printer-start.flag" 2>/dev/null || true)
        _mqtt_port=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mqtt_port',1883))" < "$INSTALL_DIR/printer-start.flag" 2>/dev/null || true)
        echo '{}' > "$INSTALL_DIR/printer-start.flag"
        if [ -n "$_printer_ip" ] && [ -n "$_mqtt_host" ]; then
            log "Starte Anycubic-Bridge (Drucker: $_printer_ip, MQTT: $_mqtt_host:$_mqtt_port)..."
            # Env-Vars in .env setzen (grep prüft ob Zeile existiert, dann sed oder append)
            _set_env() {
                local key="$1" val="$2"
                if grep -q "^${key}=" "$INSTALL_DIR/.env" 2>/dev/null; then
                    sed -i "s|^${key}=.*|${key}=${val}|" "$INSTALL_DIR/.env"
                else
                    echo "${key}=${val}" >> "$INSTALL_DIR/.env"
                fi
            }
            _mqtt_user=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mqtt_user',''))" < "$INSTALL_DIR/printer-start.flag" 2>/dev/null || true)
            _mqtt_pass=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mqtt_pass',''))" < "$INSTALL_DIR/printer-start.flag" 2>/dev/null || true)
            _set_env "ANYCUBIC_S1_IP"       "$_printer_ip"
            _set_env "ANYCUBIC_MQTT_HOST"   "$_mqtt_host"
            _set_env "ANYCUBIC_MQTT_PORT"   "$_mqtt_port"
            _set_env "ANYCUBIC_MQTT_USER"   "$_mqtt_user"
            _set_env "ANYCUBIC_MQTT_PASS"   "$_mqtt_pass"
            cd "$INSTALL_DIR"
            docker compose --profile printer up -d anycubic-bridge >> "$INSTALL_DIR/setup-watcher.log" 2>&1 \
                && log "Anycubic-Bridge gestartet" || log "Anycubic-Bridge fehlgeschlagen"
        else
            log "Anycubic-Bridge: Drucker-IP oder MQTT-Host fehlt"
        fi
    fi

    sleep 3
done
