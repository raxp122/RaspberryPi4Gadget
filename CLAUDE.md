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

## Repository
- GitHub: `raxp122/RaspberryPi4Gadget`. Il launcher sta nella cartella `pilauncher/` della repo.
- Sul Pi: `git clone https://github.com/raxp122/RaspberryPi4Gadget.git ~/RaspberryPi4Gadget`, poi `./install.sh` da `pilauncher/` (il servizio usa la cartella da cui viene lanciato install.sh).
- `calib.json` e `config.json` sono specifici del dispositivo e non vanno committati (sono in `.gitignore`).

## Architettura (cartella pilauncher/, sul Pi ~/pilauncher)
- `main.py`: loop principale con select sul touch, ridisegno solo quando serve (`mgr.dirty`).
- `core/display.py`: ruota la superficie logica 480x320 (rot 90 o 270) e scrive su fb0 solo le righe cambiate. Mette tty1 in KD_GRAPHICS per bloccare fbcon.
- `core/touch.py`: legge evdev grezzo, applica la calibrazione affine e genera eventi down/move/up/tap/rawtap (soglia di trascinamento 16 px, mediane per filtrare il rumore).
- `core/calibrate.py`: 5 mirini e fit ai minimi quadrati. Salva `calib.json` con `{rot, x:[a,b,c], y:[d,e,f]}`. Se `rot` è diverso dalla rotazione attuale, il touch viene ribaltato di 180°.
- `core/framework.py`: Screen (ciclo di vita enter/resume/leave/build, draw/draw_content, dispatch), Manager (stack delle schermate, `run()` per task in thread con messaggio "busy", toast, confirm, barra di stato con thread di polling ogni 5 s), Context (config.json e calibrazione).
- `core/ui.py`: tema scuro, font DejaVu, icone vettoriali, widget Button, Toggle, ListView (scroll col trascinamento).
- `core/keyboard.py`: tastiera a schermo.
- `core/system.py`: wrapper per nmcli (Wi-Fi), bluetoothctl, timedatectl, vcgencmd, e modifica della velocità SPI in config.txt.
- `core/home.py`: orologio e griglia delle app. Le app vengono trovate automaticamente: ogni modulo in `apps/` con un dizionario `APP = {name, icon, color, order, screen}`.
- `apps/settings.py`: Wi-Fi, Bluetooth, Schermo e touch, Data e ora, Sistema, Alimentazione.
- Servizio systemd `pilauncher.service` (gira come root, Restart=always). `getty@tty1` è disattivato.

## Note
- Il pannello SPI a 16 MHz fa circa 6 fps a schermo intero: evitare animazioni a tutto schermo e preferire aggiornamenti parziali.
- Interfaccia e grafica devono essere originali (niente asset o UI di giochi o marchi esistenti).
- Log: `journalctl -u pilauncher -f`. Riavvio: `sudo systemctl restart pilauncher`.

## Stato
Launcher installato e funzionante, avvio automatico attivo. Prossimi passi: verificare Wi-Fi e Bluetooth sull'hardware reale, poi aggiungere altre app.
