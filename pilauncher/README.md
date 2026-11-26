# PiLauncher

Launcher touch per Raspberry Pi con schermo SPI 3.5" (ILI9486 + touch ADS7846).
Disegna direttamente su `/dev/fb0`, legge il touch senza desktop e parte all'accensione.

## Installazione
Dal Raspberry (via SSH):
```bash
curl -fsSL https://raw.githubusercontent.com/raxp122/RaspberryPi4Gadget/main/install.sh | bash
```
Installa l'ultima release in `/opt/pilauncher` e importa `calib.json`/`config.json` da `~/pilauncher`, se ci sono.
Se la calibrazione manca, all'avvio compare la schermata con i mirini.

## Aggiornamenti OTA
- Ogni push su `main` che tocca `pilauncher/` crea una release `vX.Y.N` (GitHub Action `release.yml`).
  `X.Y` si cambia in `pilauncher/VERSION`, `N` cresce da solo.
- Il launcher controlla GitHub all'avvio e ogni 6 ore; se c'è una versione nuova compare `↑` nella barra di stato.
- Impostazioni → Aggiornamenti → Installa: scarica, verifica lo SHA-256, attiva la nuova versione e si riavvia.
- Se la nuova versione non resta avviata per 30 secondi e si riavvia più di 3 volte, `guard.sh` torna da solo
  alla versione precedente.

Struttura in `/opt/pilauncher`: `current` (link alla versione in uso), `releases/` (versione attuale e precedente),
`data/` (config e calibrazione), `guard.sh`.

## Comandi utili
| Cosa | Comando |
|---|---|
| Log in tempo reale | `journalctl -u pilauncher -f` |
| Riavvia il launcher | `sudo systemctl restart pilauncher` |
| Ferma il launcher | `sudo systemctl stop pilauncher` |
| Ricalibra da SSH | `sudo systemctl stop pilauncher && sudo PILAUNCHER_DATA=/opt/pilauncher/data python3 /opt/pilauncher/current/main.py --calibrate` |
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
- `VERSION`: serie della versione (`1.0`); nel pacchetto di release diventa il tag completo
- `guard.sh`: rollback automatico, eseguito da systemd prima di ogni avvio
- `data/config.json`, `data/calib.json`: rotazione e calibrazione (fuori dal codice)
- `core/updater.py`: controllo, download e installazione degli aggiornamenti
- `core/`: display, touch, widget, tastiera, calibrazione, comandi di sistema
- `apps/settings.py`: app Impostazioni
