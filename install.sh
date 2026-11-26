#!/bin/bash
# Installa (o reinstalla) PiLauncher dall'ultima release GitHub, con aggiornamenti OTA.
#   curl -fsSL https://raw.githubusercontent.com/raxp122/RaspberryPi4Gadget/main/install.sh | bash
# Per provare un branch invece dell'ultima release:
#   curl -fsSL .../<branch>/install.sh | bash -s -- --branch <branch>
set -euo pipefail

REPO="raxp122/RaspberryPi4Gadget"
BASE="/opt/pilauncher"
BRANCH=""
while [ $# -gt 0 ]; do
    case "$1" in
        --branch) BRANCH="$2"; shift 2 ;;
        *) echo "Opzione sconosciuta: $1" >&2; exit 1 ;;
    esac
done

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
USER_HOME="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Pacchetti necessari"
$SUDO apt-get install -y python3-pygame network-manager bluez fonts-dejavu-core curl ca-certificates ethtool iputils-ping ieee-data

mkdir -p "$TMP/pkg"
if [ -n "$BRANCH" ]; then
    TAG="dev-$(echo "$BRANCH" | tr '/' '-')"
    echo "==> Scarico il branch $BRANCH"
    curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" -o "$TMP/src.tar.gz"
    tar -xzf "$TMP/src.tar.gz" -C "$TMP/pkg" --strip-components=2 --wildcards '*/pilauncher/*'
    echo "$TAG" > "$TMP/pkg/VERSION"
else
    echo "==> Cerco l'ultima release"
    curl -fsSL -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/$REPO/releases/latest" -o "$TMP/release.json" || {
        echo "Nessuna release trovata su GitHub. Fai il merge su main e attendi la GitHub Action." >&2
        exit 1
    }
    TAG="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag_name"])' "$TMP/release.json")"
    NAME="pilauncher-$TAG.tar.gz"
    URL="https://github.com/$REPO/releases/download/$TAG/$NAME"
    echo "==> Scarico $TAG"
    curl -fsSL "$URL" -o "$TMP/$NAME"
    curl -fsSL "$URL.sha256" -o "$TMP/$NAME.sha256"
    (cd "$TMP" && sha256sum -c "$NAME.sha256")
    tar -xzf "$TMP/$NAME" -C "$TMP/pkg"
fi
[ -f "$TMP/pkg/main.py" ] || { echo "Pacchetto non valido" >&2; exit 1; }

echo "==> Installo in $BASE/releases/$TAG"
$SUDO mkdir -p "$BASE/releases" "$BASE/data"
$SUDO rm -rf "$BASE/releases/$TAG"
$SUDO cp -r "$TMP/pkg" "$BASE/releases/$TAG"
$SUDO install -m 755 "$BASE/releases/$TAG/guard.sh" "$BASE/guard.sh"
$SUDO ln -sfn "releases/$TAG" "$BASE/current.new"
$SUDO mv -Tf "$BASE/current.new" "$BASE/current"
$SUDO rm -f "$BASE/data/pending" "$BASE/data/pending_tries" "$BASE/data/rolled_back"

# recupera calibrazione e impostazioni dalla vecchia installazione in ~/pilauncher
for f in calib.json config.json; do
    if [ ! -f "$BASE/data/$f" ] && [ -f "$USER_HOME/pilauncher/$f" ]; then
        echo "==> Importo $f da $USER_HOME/pilauncher"
        $SUDO cp "$USER_HOME/pilauncher/$f" "$BASE/data/$f"
    fi
done

echo "==> Servizio systemd"
$SUDO tee /etc/systemd/system/pilauncher.service >/dev/null <<UNIT
[Unit]
Description=PiLauncher (schermo touch SPI)
After=systemd-user-sessions.service NetworkManager.service bluetooth.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=root
Environment=PILAUNCHER_HOME=$BASE
Environment=PILAUNCHER_DATA=$BASE/data
WorkingDirectory=$BASE/current
ExecStartPre=-/bin/sh $BASE/guard.sh
ExecStart=/usr/bin/python3 $BASE/current/main.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT

echo "==> Login testuale su tty1 disattivato (resta SSH)"
$SUDO systemctl disable --now getty@tty1.service 2>/dev/null || true

$SUDO systemctl daemon-reload
$SUDO systemctl enable pilauncher.service
$SUDO systemctl restart pilauncher.service
echo
echo "PiLauncher $TAG installato in $BASE."
if [ -d "$USER_HOME/pilauncher" ]; then
    echo "La vecchia cartella $USER_HOME/pilauncher non viene più usata: puoi cancellarla."
fi
echo "Log: journalctl -u pilauncher -f"
