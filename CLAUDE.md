# PiLauncher — contesto del progetto

Launcher touch in Python/pygame per Raspberry Pi 4 con HAT schermo Kuman 3.5" SPI.
Comunicazione con l'utente in italiano.

## Hardware e sistema
- Raspberry Pi 4, Raspberry Pi OS basato su Debian 13 (trixie), kernel 6.18, avvio in console (desktop disattivato con `raspi-config nonint do_boot_behaviour B1`).
- Utente `raspberry`, hostname `raspberry`, accesso via SSH (`ssh raspberry@raspberry.local`).
- Schermo: controller ILI9486 (driver DRM), touch resistivo ADS7846 (XPT2046).
- `/boot/firmware/config.txt`, in fondo sotto `[all]`:
  ```
  dtparam=spi=on
  dtoverlay=piscreen,drm,speed=16000000,rotate=270
  ```
  Il parametro `rotate` dell'overlay non ha effetto col driver DRM: il pannello resta 320x480 verticale. La rotazione la fa il codice.
- Framebuffer `/dev/fb0` a 16 bpp (RGB565), 320x480. Touch su `/dev/input/eventN`, numero rilevato a runtime cercando "ADS7846" in `/proc/bus/input/devices`.
- Alimentazione: serve un alimentatore da 5 V / 3 A. Uso portatile previsto con powerbank.

## Repository e aggiornamenti OTA
- GitHub: `raxp122/RaspberryPi4Gadget` (pubblica). Il launcher sta in `pilauncher/`, l'installer in `install.sh` alla radice.
- Installazione sul Pi: `curl -fsSL https://raw.githubusercontent.com/raxp122/RaspberryPi4Gadget/main/install.sh | bash`
  (con `| bash -s -- --branch <nome>` installa un branch per le prove).
- Sul Pi il launcher sta in `/opt/pilauncher`: `current -> releases/<tag>`, `releases/` (attuale e precedente), `data/` (config.json, calib.json), `guard.sh`.
  Il servizio passa `PILAUNCHER_HOME` e `PILAUNCHER_DATA`; senza `PILAUNCHER_DATA` i dati restano nella cartella del codice (sviluppo).
- Release: `.github/workflows/release.yml` a ogni push su main che tocca `pilauncher/`. Tag `vX.Y.N`, `X.Y` da `pilauncher/VERSION`.
  Asset: `pilauncher-<tag>.tar.gz` + `.sha256`.
- `core/updater.py`: controlla `releases/latest` all'avvio e ogni 6 h (thread della barra di stato), installazione manuale da Impostazioni → Aggiornamenti.
  Dopo l'installazione scrive `data/pending`; il launcher conferma dopo 30 s di funzionamento. `guard.sh` (ExecStartPre) torna alla versione precedente dopo più di 3 avvii non confermati e scrive `data/rolled_back`.
- `calib.json` e `config.json` non vanno committati (`.gitignore`).

## Architettura (cartella pilauncher/)
- `main.py`: loop principale con select sul touch, ridisegno solo quando serve (`mgr.dirty`).
- `core/display.py`: ruota la superficie logica 480x320 (rot 90 o 270) e scrive su fb0 solo le righe cambiate. Mette tty1 in KD_GRAPHICS per bloccare fbcon.
- `core/touch.py`: legge evdev grezzo, applica la calibrazione affine e genera eventi down/move/up/tap/rawtap (soglia di trascinamento 16 px, mediane per filtrare il rumore).
- `core/calibrate.py`: 5 mirini e fit ai minimi quadrati. Salva `calib.json` con `{rot, x:[a,b,c], y:[d,e,f]}`. Se `rot` è diverso dalla rotazione attuale, il touch viene ribaltato di 180°.
- `core/framework.py`: Screen (ciclo di vita enter/resume/leave/build, draw/draw_content, dispatch), Manager (stack delle schermate, `run()` per task in thread con messaggio "busy", toast, confirm, barra di stato con thread di polling ogni 5 s), Context (config.json e calibrazione).
- `core/ui.py`: tema scuro, font DejaVu, icone vettoriali, widget Button, Toggle, ListView (scroll col trascinamento).
- `core/keyboard.py`: tastiera a schermo.
- `core/system.py`: wrapper per nmcli (Wi-Fi), bluetoothctl, timedatectl, vcgencmd, e modifica della velocità SPI in config.txt.
- `core/home.py`: orologio e griglia delle app. Le app vengono trovate automaticamente: ogni modulo in `apps/` con un dizionario `APP = {name, icon, color, order, screen}`.
- `core/netdiag.py`: diagnostica di eth0 (sysfs + ethtool per il link, socket AF_PACKET per LLDP/CDP/EAPOL, `ip -j` e nmcli per IP/DHCP, ping, query DNS fatte a mano con SO_BINDTODEVICE, curl --interface per HTTP/HTTPS, ethtool --cable-test, lampeggio porta con ip link down/up).
- `apps/nettest/` (pacchetto): app Tester rete per l'helpdesk (l'utente lavora all'helpdesk di Aboca). Sequenza automatica al collegamento del cavo, dettagli per riga, strumenti (ping continuo, lampeggio porta, test cavo, rinnovo DHCP, DNS). In azienda le prese hanno IP fissi: la riga Indirizzo IP apre la configurazione (DHCP o profili IP fisso salvati in config.json sotto `nettest`, applicati con il profilo NetworkManager `pilauncher-eth0` con DAD) e il rilevamento della rete via ARP passivo. In azienda il tester non ha ricevuto l'IP sulla presa: l'utente dice che l'IP è legato alla porta dello switch (forse DHCP per porta, con port security o NAC). Se il DHCP di sistema fallisce parte `dhcp_probe` (DISCOVER costruito a mano su AF_PACKET, conta offerte e traffico) per capire la causa. Poi continua ad aspettare: sulla presa aziendale l'IP è arrivato dopo più di 40 s (premendo Ripeti), quindi porta lenta (STP/802.1X+MAB); il tempo al DHCP viene mostrato.
- Tester rete, file: `common.py` (costanti, Detail), `diag.py` (sequenza: link, switch, ip + `_ip_extra`, gw, dns, inet con traceroute, svc = server aziendali + NTP; ogni passo in `_safe`), `main.py`, `ipconf.py`, `tools.py`, `report.py` (testo, QR a pagine, lista, web), `targets.py` (server salvati solo in data/config.json sotto `nettest.targets`, mai su GitHub), `active.py` (scansioni ARP e porte, abilitate da `nettest.active_scans`).
- `core/qr.py`: encoder QR scritto a mano (niente dipendenze: l'OTA non installa pacchetti apt). Verificato con ZXing su tutte le 40 versioni.
- `core/webshare.py`: pagina dei report sulla porta 8080, spegnimento automatico dopo 30 min.
- `core/usbkbd.py`: tastiere evdev con layout italiano, eventi a `Screen.on_key(kind, val)` (Esc = indietro).
- Le dipendenze apt nuove vanno aggiunte in `install.sh`, ma i Pi aggiornati via OTA non le ricevono: il codice deve funzionare anche senza (es. `ieee-data` per i produttori dei MAC è facoltativo).
- `core/wifidiag.py` + `apps/wifitest/`: Tester Wi-Fi. Scansione con `iw dev wlan0 scan` (ripiego `scan dump`, poi nmcli), parser di BSS Load (client, occupazione), HT/VHT/HE, RSN, 802.11k/v/r; `link_info` da `iw link` + `station dump`; `analyze` produce gli avvisi (AP più forte ignorato, segnale < -67, canali 2,4 fuori 1/6/11, congestione). Il report riusa `apps/nettest/report.py`.
- `apps/settings.py`: Wi-Fi, Bluetooth, Schermo e touch, Data e ora, Sistema, Aggiornamenti, Alimentazione.
- Servizio systemd `pilauncher.service` (gira come root, Restart=always). `getty@tty1` è disattivato.

## Note
- Il pannello SPI a 16 MHz fa circa 6 fps a schermo intero: evitare animazioni a tutto schermo e preferire aggiornamenti parziali.
- Interfaccia e grafica devono essere originali (niente asset o UI di giochi o marchi esistenti).
- Log: `journalctl -u pilauncher -f`. Riavvio: `sudo systemctl restart pilauncher`.

## Stato
Launcher installato e funzionante, avvio automatico attivo. Aggiornamenti OTA funzionanti. Aggiunta l'app Tester rete (da provare sulla rete aziendale: LLDP/CDP, 802.1X, test cavo col PHY BCM54213PE non verificati). Prossimi passi (vedi anche le idee della KB in fondo): verificare Wi-Fi e Bluetooth sull'hardware reale, poi aggiungere altre app.

## Idee dalla KB aziendale (da fare)
IP Scanner con lista di IP attesi, Reachability Check con handshake TLS, Printer Probe (ping, SNMP, 9100, LPR, IPP) e etichetta ZPL di prova, SIP OPTIONS ping, gadget USB-C (tastiera HID per sequenze Autopilot/OOBE e diskpart, chiavetta virtuale con installer), checklist operative locali (consegna, enrollment, dismissione), Status Board dei job, Room Kit (orologio a schermo intero, test display PoE).
