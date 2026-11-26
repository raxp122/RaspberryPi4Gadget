# RaspberryPi4Gadget

Un gadget portatile fatto con un Raspberry Pi 4 e uno schermo touch da 3.5".
Il cuore è **PiLauncher**, un launcher touch scritto in Python/pygame che parte all'accensione,
disegna direttamente sul framebuffer (niente desktop) e si aggiorna da solo dalle release di GitHub.

## Hardware
| Componente | Dettagli |
|---|---|
| Scheda | Raspberry Pi 4 |
| Schermo | HAT Kuman 3.5" SPI, 320×480, controller ILI9486 (driver DRM) |
| Touch | Resistivo ADS7846 / XPT2046 |
| Sistema | Raspberry Pi OS basato su Debian 13 (trixie), avvio in console |
| Alimentazione | 5 V / 3 A (alimentatore o powerbank) |

### Configurazione dello schermo
In fondo a `/boot/firmware/config.txt`, sotto `[all]`:
```
dtparam=spi=on
dtoverlay=piscreen,drm,speed=16000000,rotate=270
```
Col driver DRM il parametro `rotate` non ha effetto: la rotazione la fa il launcher (Impostazioni → Schermo e touch).

Avvio in console, senza desktop:
```bash
sudo raspi-config nonint do_boot_behaviour B1
```

## Installazione
Dal Raspberry, via SSH:
```bash
curl -fsSL https://raw.githubusercontent.com/raxp122/RaspberryPi4Gadget/main/install.sh | bash
```
Lo script:
1. installa i pacchetti necessari (`python3-pygame`, `network-manager`, `bluez`, `fonts-dejavu-core`, `ethtool`, ...);
2. scarica l'ultima release, ne verifica lo SHA-256 e la mette in `/opt/pilauncher`;
3. importa calibrazione e impostazioni da una vecchia installazione in `~/pilauncher`, se c'è;
4. crea il servizio `pilauncher.service` (avvio automatico) e disattiva il login testuale su tty1 (SSH resta attivo).

Al primo avvio, se manca la calibrazione, compaiono i mirini da toccare.

Per provare un branch prima del merge:
```bash
curl -fsSL https://raw.githubusercontent.com/raxp122/RaspberryPi4Gadget/<branch>/install.sh | bash -s -- --branch <branch>
```

## Uso
- La home mostra l'orologio e la griglia delle app.
- Toccando la barra di stato in alto si torna sempre alla home.
- La barra di stato mostra Wi-Fi, Bluetooth, temperatura della CPU, `⚡` se l'alimentazione è insufficiente
  e `↑` se c'è un aggiornamento.
- **Tester rete**: diagnostica della presa Ethernet per l'helpdesk (vedi sotto).
- **Impostazioni**: Wi-Fi, Bluetooth, Schermo e touch (rotazione, calibrazione, velocità SPI), Data e ora,
  Sistema, Aggiornamenti, Alimentazione.

## Tester rete
Si collega il cavo alla porta Ethernet del Pi e i controlli partono da soli, in sequenza:

| Controllo | Cosa mostra |
|---|---|
| Cavo e link | Velocità, duplex, massimo supportato dallo switch, errori CRC. Avvisa se il link è a 100 Mbit/s quando entrambi arrivano a 1 Gbit/s (tipico di un cavo con coppie rotte) |
| Switch e porta | Nome dello switch, porta, descrizione, VLAN dati e voce, IP di gestione, letti dagli annunci LLDP e CDP (ascolto fino a 65 s). Rileva se la porta chiede l'autenticazione 802.1X |
| Indirizzo IP | Indirizzo, gateway, DNS, dominio, server DHCP e durata del lease. Se il DHCP non risponde parte un test DHCP dettagliato (vedi sotto) |
| Gateway | Ping: tempi e pacchetti persi |
| DNS | Risoluzione di un nome esterno e del dominio interno su ogni server DNS ricevuto |
| Internet | Prova HTTP e HTTPS: distingue rete libera, proxy o portale, rete bloccata |

Toccando una riga si vedono tutti i dettagli.

### Test DHCP dettagliato
Quando il DHCP non risponde, il tester invia da solo le richieste DHCP per 12 secondi e registra:
- le **offerte** ricevute: indirizzo, server, gateway, DNS, relay (più server che rispondono = possibile DHCP non autorizzato);
- quanti **pacchetti** arrivano dalla porta e da quanti dispositivi;
- se il **link cade** durante la prova (porta bloccata da port security).

Dopo il test il tester **continua ad aspettare**: alcune porte aziendali danno l'indirizzo solo dopo 1–2 minuti
(spanning tree senza portfast, 802.1X con ripiego sul MAC). Quando l'IP arriva i controlli proseguono da soli
e il tempo impiegato compare nella riga Indirizzo IP.

Così si distingue una porta morta (nessun traffico) da una porta attiva che ignora il tester (port security,
assegnazione legata al MAC del PC, NAC/802.1X). Il test si può lanciare anche da Strumenti.

### Prese con IP fisso
Toccando la riga **Indirizzo IP** si sceglie come configurare la porta del tester:
- **Automatico (DHCP)**;
- uno degli **IP fissi salvati** (indirizzo, maschera, gateway, DNS e una nota, ad esempio la presa o l'ufficio);
- **Rileva la rete della porta**: ascolta per 25 secondi le richieste ARP degli altri dispositivi e propone la rete
  /24 e il gateway più probabili, con l'elenco degli indirizzi già in uso. Mostra anche gli indirizzi **cercati ma
  assenti**: dispositivi che la rete prova a raggiungere ma che non rispondono, tra cui spesso il PC scollegato da
  quella presa. È un indizio, non una certezza: con gli IP fissi l'indirizzo sta nel PC, non nella presa.

La configurazione resta salvata e vale anche ai collegamenti successivi. Prima di usare un IP fisso il tester controlla
che non sia già occupato da un altro dispositivo (rilevamento dei duplicati di NetworkManager).

Il pulsante **Strumenti** offre:
- **Ping continuo** verso un indirizzo a scelta, con grafico dei tempi;
- **Lampeggia la porta sullo switch**: spegne e riaccende il link ogni 1,5 s per 30 s, così il LED della porta
  nell'armadio di rete lampeggia e si trova la presa giusta;
- **Test del cavo** (`ethtool --cable-test`): stato delle 4 coppie e distanza del guasto, se il chip di rete lo supporta;
- **Rinnova DHCP** con il tempo impiegato;
- **Risolvi un nome** su tutti i DNS ricevuti.

Il tester ascolta solo il traffico di servizio dello switch (LLDP, CDP, 802.1X) e non invia nulla di insolito sulla
rete, a parte il lampeggio della porta, che va avviato a mano.

## Aggiornamenti OTA
```
push su main ──► GitHub Action "Release" ──► release vX.Y.N ──► il Pi la vede ──► Installa dal touch
```
- **Release automatica**: ogni push su `main` che modifica `pilauncher/` crea una release con
  `pilauncher-vX.Y.N.tar.gz` e il suo `.sha256` ([`release.yml`](.github/workflows/release.yml)).
  `X.Y` si decide nel file [`pilauncher/VERSION`](pilauncher/VERSION), `N` cresce da solo.
- **Controllo**: il launcher interroga GitHub all'avvio e poi ogni 6 ore.
- **Installazione**: manuale, da Impostazioni → Aggiornamenti → Installa. Il pacchetto viene scaricato,
  verificato, estratto in una cartella nuova e attivato cambiando un link simbolico; poi il launcher si riavvia.
- **Rollback automatico**: se la nuova versione non resta avviata per 30 secondi e viene riavviata più di 3 volte,
  [`guard.sh`](pilauncher/guard.sh) torna alla versione precedente e lo segnala nella schermata Aggiornamenti.

Struttura sul Pi:
```
/opt/pilauncher/
├── current -> releases/v1.0.3   versione in uso
├── releases/                    versione attuale e precedente
├── data/                        config.json, calib.json (restano tra un aggiornamento e l'altro)
└── guard.sh                     eseguito da systemd prima di ogni avvio
```

## Comandi utili
| Cosa | Comando |
|---|---|
| Log in tempo reale | `journalctl -u pilauncher -f` |
| Riavvia il launcher | `sudo systemctl restart pilauncher` |
| Ferma il launcher | `sudo systemctl stop pilauncher` |
| Versione installata | `readlink /opt/pilauncher/current` |
| Ricalibra da SSH | `sudo systemctl stop pilauncher && sudo PILAUNCHER_DATA=/opt/pilauncher/data python3 /opt/pilauncher/current/main.py --calibrate` |
| Disinstalla | `sudo systemctl disable --now pilauncher && sudo systemctl enable --now getty@tty1` |

## Struttura della repo
```
install.sh                  installer da GitHub
.github/workflows/          release automatica
pilauncher/
├── main.py                 loop principale
├── VERSION                 serie della versione (es. 1.0)
├── guard.sh                rollback automatico
├── core/
│   ├── display.py          rotazione e scrittura su /dev/fb0 (solo le righe cambiate)
│   ├── touch.py            lettura evdev, calibrazione, gesti (tap, trascinamento)
│   ├── calibrate.py        calibrazione a 5 punti
│   ├── framework.py        schermate, navigazione, barra di stato, dialoghi, task in background
│   ├── ui.py               tema, font, icone vettoriali, Button, Toggle, ListView
│   ├── keyboard.py         tastiera a schermo
│   ├── system.py           Wi-Fi, Bluetooth, data/ora, info di sistema, alimentazione
│   ├── updater.py          aggiornamenti OTA
│   ├── netdiag.py          diagnostica di rete (link, LLDP/CDP, 802.1X, DHCP, ping, DNS, HTTP)
│   └── home.py             home e ricerca automatica delle app
└── apps/
    ├── nettest.py          app Tester rete
    └── settings.py         app Impostazioni
```

## Scrivere un'app
Ogni file in `pilauncher/apps/` che definisce un dizionario `APP` compare da solo nella home:
```python
from core.framework import Screen
from core.ui import text, icon_info

class Meteo(Screen):
    title = "Meteo"

    def draw_content(self, s):
        text(s, "Ciao!", self.body.center, 24, anchor="center")

APP = {"name": "Meteo", "icon": icon_info, "color": (40, 120, 200), "order": 10, "screen": Meteo}
```
Cose da sapere:
- La superficie logica è 480×320. `self.body` è l'area sotto la barra di stato e l'intestazione.
- Si ridisegna solo quando `mgr.dirty` è vero: dopo un tocco succede da solo, per le animazioni va impostato.
- Lo schermo SPI fa circa 6 fps a schermo intero: meglio aggiornamenti piccoli che animazioni a tutto schermo.
- Le operazioni lente (rete, comandi di sistema) vanno in `self.mgr.run(funzione, al_termine, "Messaggio…")`,
  che le esegue in un thread e mostra un indicatore.
- `self.mgr.toast("…")` mostra un avviso, `self.mgr.confirm(...)` un dialogo di conferma.

Flusso di sviluppo: si lavora su un branch, lo si prova sul Pi con `install.sh --branch`,
poi il merge su `main` crea la release e tutti i Pi la ricevono come aggiornamento.

## Licenza
Vedi [LICENSE](LICENSE).
