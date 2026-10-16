# 📡 Module Documentation: Kismet RF Ingestion Engine

## 📌 Rolle im System

Kismet ist das passive Sensor-System im Fahrzeug. Es steuert die Alfa AWUS036AXML Wi-Fi-Karte im Monitor-Mode, den Bluetooth-Dongle sowie den USB-GPS-Empfänger. Es horcht lautlos auf alle Frames in der Luft, dekodiert sie und verknüpft sie in Echtzeit mit den GPS-Koordinaten.

*Hinweis zu Mobilfunk (LTE/5G):* Kismet selbst ist primär auf Wi-Fi, Bluetooth und BLE spezialisiert. Direkte zelluläre Masten-Erfassung (Cell-ID / eNodeB) wird von Kismet standardmäßig **nicht** unterstützt. Für Zell-Dateningestion müsste extern ein SDR (z. B. RTL-SDR mit `gr-gsm`) oder ein separates Modem-Skript (via `ModemManager`) parallel angebunden werden.

## 🛠️ Docker Deployment Config & Privilegien

Da Kismet direkten Zugriff auf die USB-Hardware und die Netzwerk-Interfaces des Host-Systems (z. B. Debian) benötigt, läuft dieser Container im `host`-Netzwerkmodus und mit `privileged: true`:

```
services:
  kismet:
    image: kismet/kismet:latest
    container_name: wardrivrr_kismet
    restart: unless-stopped
    network_mode: host
    privileged: true
    volumes:
      - ./kismet_configs:/etc/kismet/kismet_site.conf
      - kismet_logs:/home/kismet/logs

volumes:
  kismet_logs:

```

## ⚙️ Wichtige Konfiguration (`kismet_site.conf`)

```ini
# Server Name im Netzwerk
server_name=wardrivrr

# GPS Input via lokalem gpsd service auf Port 2947
gps=gpsd:host=localhost,port=2947

# Alfa AWUS036AXML (Wi-Fi 6E, MediaTek MT7921AU) im Monitor Mode
source=wlan1:name=AlfaAWUS036AXML:type=linuxwifi

# USB Bluetooth Dongle für BLE / Beacon / TPMS Tracking
source=hci1:name=USB_Bluetooth:type=linuxbluetooth

# Logging Optimierung (Keine gigantischen Roh-PCAPs speichern, nur die kompakten SQLite-Databases)
log_types=kismet,kis_db
```