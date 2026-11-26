#!/bin/bash
# Installa PiLauncher come servizio che parte all'accensione.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Pacchetti necessari"
sudo apt install -y python3-pygame network-manager bluez fonts-dejavu-core

echo "==> Servizio systemd"
sudo tee /etc/systemd/system/pilauncher.service >/dev/null <<EOF
[Unit]
Description=PiLauncher (schermo touch SPI)
After=systemd-user-sessions.service NetworkManager.service bluetooth.service

[Service]
Type=simple
User=root
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/main.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

echo "==> Login testuale su tty1 disattivato (resta SSH)"
sudo systemctl disable --now getty@tty1.service || true

sudo systemctl daemon-reload
sudo systemctl enable --now pilauncher.service
echo "Fatto. Log:  journalctl -u pilauncher -f"
