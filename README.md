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
1. installa i pacchetti necessari (`python3-pygame`, `network-manager`, `bluez`, `fonts-dejavu-core`, `ethtool`, `iw`, ...);
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
- **Tester Wi-Fi**: reti e AP visibili, canali, collegamento attuale, test della connessione, monitor del roaming.
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
| Internet | Prova HTTP e HTTPS: distingue rete libera, proxy o portale, rete bloccata. Percorso (traceroute) e MTU verso Internet |
| Server aziendali | Raggiungibilità dei server inseriti a mano (porte TCP o ping) e differenza di orario con il server NTP |

Dettagli raccolti in automatico, visibili toccando le righe:
- **Switch**: spanning tree (STP, RSTP, MSTP, PVST+), root bridge, costo, cambi di topologia; avviso se l'IP arriva
  tardi su una porta senza portfast.
- **Indirizzo IP**: IP duplicato (sonda ARP), tutti i server DHCP che rispondono (avviso se più di uno), relay DHCP,
  opzione 82, server NTP, TFTP per i telefoni (opzioni 66 e 150), proxy WPAD, nome DNS del tester, IPv6.
- **Gateway**: MAC e produttore, MTU.
- **DNS**: domain controller trovati via DNS (record SRV), presenza di `wpad.<dominio>`.

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

### Report per i ticket
Il pulsante **Report** chiede il nome della presa (proposto dalla descrizione della porta sullo switch) e salva sul
Pi un report in testo semplice con tutti i dati. Dal report:
- **QR code** a tutto schermo con il riassunto: si inquadra con il telefono e si incolla nel ticket. Se il testo
  è lungo viene diviso in più pagine.
- **Condividi via web** (in Strumenti → Report salvati): una pagina in sola lettura sulla porta 8080 con tutti i
  report, da aprire dal PC. Si spegne da sola dopo 30 minuti ed è raggiungibile da tutte le reti a cui è collegato il Pi.

Si tengono gli ultimi 200 report, in `/opt/pilauncher/data/reports/`.

### Server aziendali
In Strumenti → **Server aziendali** si inseriscono nome, indirizzo (IP o nome host) e porte TCP dei server da
controllare a ogni test. La lista resta **solo sul Pi** (`/opt/pilauncher/data/config.json`) e non finisce su GitHub.
Si può scrivere con la tastiera a schermo o con una **tastiera USB** (layout italiano, Invio conferma, Esc torna indietro).

### Scansioni attive
In Strumenti → **Scansioni attive**, spente finché non si attiva l'interruttore:
- **Dispositivi nella rete**: richiesta ARP a ogni indirizzo della rete (massimo /22), con nome DNS e produttore;
- **Porte aperte** su un indirizzo: prova 23 porte comuni (file, dominio, desktop remoto, stampa, web…).

Inviano traffico a molti indirizzi: vanno usate solo dove si è autorizzati.

Il pulsante **Strumenti** offre anche:
- **Ping continuo** verso un indirizzo a scelta, con grafico dei tempi;
- **Lampeggia la porta sullo switch**: spegne e riaccende il link ogni 1,5 s per 30 s, così il LED della porta
  nell'armadio di rete lampeggia e si trova la presa giusta;
- **Test del cavo** (`ethtool --cable-test`): stato delle 4 coppie e distanza del guasto, se il chip di rete lo supporta;
- **Rinnova DHCP** con il tempo impiegato;
- **Risolvi un nome** su tutti i DNS ricevuti.

Durante il test automatico il tester ascolta il traffico di servizio dello switch (LLDP, CDP, STP, 802.1X) e invia
solo traffico normale per un PC: richieste DHCP, una sonda ARP per il proprio indirizzo, ping, DNS, connessioni ai
server configurati e un traceroute. Lampeggio della porta e scansioni attive vanno avviati a mano.

## Tester Wi-Fi
Usa la scheda Wi-Fi del Pi (2,4 e 5 GHz) e il comando `iw` per avere più dettagli di quelli di NetworkManager.

- **Collegamento attuale**: rete, AP (BSSID e produttore), canale e banda, segnale in dBm con giudizio
  (ottimo ≥ -55, buono ≥ -67, sufficiente ≥ -75, scarso), velocità di collegamento.
- **Reti visibili**: tutte le reti con numero di AP, bande e sicurezza; per ogni AP segnale, canale, larghezza,
  standard (n/ac/ax), client collegati e occupazione del canale (se l'AP li pubblica), supporto al roaming 802.11k/v/r.
- **Occupazione dei canali**: grafico degli AP per canale a 2,4 e 5 GHz.
- **Test della connessione**: IP, gateway, DNS e Internet sul Wi-Fi.
- **Monitor segnale e roaming**: segnale ogni secondo, ping al gateway e cambi di AP mentre ci si sposta.
- **Avvisi**: dispositivo agganciato a un AP più debole di un altro della stessa rete, segnale sotto -67 dBm,
  rete solo a 2,4 GHz, canale congestionato, AP a 2,4 GHz fuori da 1/6/11, sicurezza obsoleta.
- **Report**: come per il Tester rete, con QR code e pagina web.

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
│   ├── netdiag.py          diagnostica di rete (link, LLDP/CDP/STP, 802.1X, DHCP, ARP, ping, DNS, TCP, NTP, HTTP)
│   ├── qr.py               generatore di QR code senza dipendenze
│   ├── webshare.py         pagina web dei report
│   ├── usbkbd.py           tastiere USB/Bluetooth (layout italiano)
│   ├── wifidiag.py         diagnostica Wi-Fi (scansione iw, collegamento, analisi)
│   └── home.py             home e ricerca automatica delle app
└── apps/
    ├── nettest/            app Tester rete (diag, main, ipconf, tools, report, targets, active)
    ├── wifitest/           app Tester Wi-Fi
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
