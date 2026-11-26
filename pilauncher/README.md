# PiLauncher

Launcher touch per Raspberry Pi con schermo SPI 3.5" (ILI9486 + touch ADS7846).
Disegna direttamente su `/dev/fb0`, legge il touch senza desktop e parte all'accensione.

## Installazione
```bash
cd ~/pilauncher
chmod +x install.sh
./install.sh
```
La calibrazione fatta con `~/pipboy/calib.py` viene importata automaticamente.
Se manca, all'avvio compare la schermata con i mirini.

## Comandi utili
| Cosa | Comando |
|---|---|
| Log in tempo reale | `journalctl -u pilauncher -f` |
| Riavvia il launcher | `sudo systemctl restart pilauncher` |
| Ferma il launcher | `sudo systemctl stop pilauncher` |
| Ricalibra da SSH | `sudo systemctl stop pilauncher && sudo python3 main.py --calibrate` |
| Disinstalla | `sudo systemctl disable --now pilauncher && sudo systemctl enable --now getty@tty1` |

Toccando la barra di stato in alto si torna sempre alla home.

## Aggiungere un'app
Crea un file in `apps/`, ad esempio `apps/meteo.py`, che definisca una classe `Screen`
e un dizionario `APP`:
```python
from core.framework import Screen
from core.ui import text, icon_info

class Meteo(Screen):
    title = "Meteo"
    def draw_content(self, s):
        text(s, "Ciao!", self.body.center, 24, anchor="center")

APP = {"name": "Meteo", "icon": icon_info, "color": (40, 120, 200), "order": 10, "screen": Meteo}
```
Poi `sudo systemctl restart pilauncher`: l'icona compare nella home.

## File
- `config.json`: rotazione (creato al primo cambio)
- `calib.json`: calibrazione del touch
- `core/`: display, touch, widget, tastiera, calibrazione, comandi di sistema
- `apps/settings.py`: app Impostazioni
