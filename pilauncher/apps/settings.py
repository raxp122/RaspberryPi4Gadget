"""App Impostazioni: Wi-Fi, Bluetooth, Sistema, Schermo e touch, Data e ora, Alimentazione."""
import re
import time

import pygame

from core import system as sysm
from core.calibrate import CalibScreen
from core.framework import Message, Screen
from core.keyboard import Keyboard
from core.ui import (T, Button, ListView, Toggle, icon_bt, icon_clock, icon_gear, icon_info,
                     icon_lock, icon_power, icon_refresh, icon_screen, icon_wifi, signal_bars, signal_level,
                     text, wrap)

ROW_H = 48


# ===================================================================== menu
class SettingsMain(Screen):
    title = "Impostazioni"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.wifi_sub, self.bt_sub = "…", "…"

    def enter(self):
        self.build()
        self.load()

    def resume(self):
        self.build()
        self.load()

    def load(self):
        def job():
            st = sysm.wifi_status()
            wifi = (f"Connesso a {st['connection']}" if st["connected"] else
                    "Non connesso" if sysm.wifi_radio() else "Spento")
            bt = "Acceso" if sysm.bt_powered()[0] else "Spento"
            return wifi, bt

        def done(res):
            self.wifi_sub, self.bt_sub = res
            self.build()

        self.mgr.run(job, done)

    def build(self):
        items = [
            {"title": "Wi-Fi", "subtitle": self.wifi_sub, "icon": icon_wifi, "chevron": True, "go": WifiScreen},
            {"title": "Bluetooth", "subtitle": self.bt_sub, "icon": icon_bt, "chevron": True, "go": BtScreen},
            {"title": "Schermo e touch", "subtitle": "Rotazione, calibrazione, velocità",
             "icon": icon_screen, "chevron": True, "go": DisplayScreen},
            {"title": "Data e ora", "subtitle": sysm_tz_cache(), "icon": icon_clock, "chevron": True,
             "go": TimeScreen},
            {"title": "Sistema", "subtitle": "Rete, temperatura, memoria, alimentazione", "icon": icon_info,
             "chevron": True, "go": SystemScreen},
            {"title": "Aggiornamenti", "subtitle": update_subtitle(self.mgr), "icon": icon_refresh,
             "chevron": True, "go": UpdateScreen,
             "subtitle_color": T["accent"] if self.mgr.status.get("update") else T["muted"]},
            {"title": "Alimentazione", "subtitle": "Riavvia o spegni", "icon": icon_power, "chevron": True,
             "go": PowerScreen},
        ]
        old = self.widgets[0].offset if self.widgets else 0
        lv = ListView(self.body, items, ROW_H, on_select=lambda it: self.mgr.push(it["go"](self.mgr)))
        lv.offset = min(old, lv.max_offset())
        self.widgets = [lv]


_tz = {"v": None}


def sysm_tz_cache():
    if _tz["v"] is None:
        _tz["v"] = sysm.tz_current()
    return _tz["v"]


# ==================================================================== Wi-Fi
class WifiScreen(Screen):
    title = "Wi-Fi"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.radio, self.status, self.nets, self.saved, self.err = None, None, [], {}, ""
        self.loaded = False

    def enter(self):
        self.build()
        self.refresh(scan=True)

    def refresh(self, scan=True):
        def job():
            radio = sysm.wifi_radio()
            nets, err = sysm.wifi_scan(scan) if radio else ([], "")
            return radio, sysm.wifi_status(), sysm.wifi_saved(), nets, err

        def done(res):
            self.radio, self.status, self.saved, self.nets, self.err = res
            self.loaded = True
            self.build()

        self.mgr.run(job, done, "Ricerca reti…" if scan else "Aggiornamento…")

    def build(self):
        a, b = self.area, self.body
        tg = Toggle((a.right - 64, a.y + 6, 52, 28), self.radio, self.set_radio)
        tg.enabled = self.radio is not None
        ref = Button((b.right - 104, b.y + 6, 96, 30), "Cerca", lambda: self.refresh(True), size=13)
        ref.enabled = bool(self.radio)
        items = []
        for n in self.nets:
            tag = ("Connessa" if n["inuse"] else "Salvata" if n["ssid"] in self.saved else
                   "Protetta" if n["security"] else "Aperta")
            items.append({"title": n["ssid"], "subtitle": f"{tag} · {n['signal']}%", "net": n,
                          "subtitle_color": T["ok"] if n["inuse"] else T["muted"],
                          "draw_right": self._right(n)})
        empty = ("Wi-Fi spento" if self.radio is False else "Nessuna rete trovata" if self.loaded else "")
        lv = ListView((b.x, b.y + 42, b.w, b.h - 42), items, ROW_H, on_select=self.select, empty_text=empty)
        self.widgets = [lv, ref, tg]

    @staticmethod
    def _right(n):
        def draw(s, r):
            x = r.right - 26
            signal_bars(s, pygame.Rect(x, r.centery - 9, 24, 16), signal_level(n["signal"]))
            if n["security"]:
                icon_lock(s, (x - 14, r.centery - 2), 16, T["muted"])
                return 44
            return 26
        return draw

    def draw_content(self, s):
        b = self.body
        if self.status is None:
            msg, col = "Lettura stato…", T["muted"]
        elif self.status["connected"]:
            msg = f"Connesso a {self.status['connection']}" + (f" · {self.status['ip']}" if self.status["ip"] else "")
            col = T["ok"]
        else:
            msg, col = ("Wi-Fi spento" if self.radio is False else "Non connesso"), T["muted"]
        text(s, msg, (b.x + 14, b.y + 21), 13, col, anchor="midleft", maxw=b.w - 130)

    def set_radio(self, on):
        self.mgr.run(lambda: sysm.wifi_set_radio(on), lambda r: (time.sleep(0.5), self.refresh(on)),
                     "Accensione Wi-Fi…" if on else "Spegnimento Wi-Fi…")

    def select(self, it):
        n = it["net"]
        if n["inuse"] or n["ssid"] in self.saved:
            self.mgr.push(WifiDetail(self.mgr, self, n))
        elif not n["security"]:
            self.connect(n["ssid"], None)
        else:
            self.mgr.push(Keyboard(self.mgr, f"Password: {n['ssid']}", lambda pw: self.connect(n["ssid"], pw),
                                   password=True, ok_label="Connetti"))

    def connect(self, ssid, pw):
        self.mgr.run(lambda: sysm.wifi_connect(ssid, pw), self.after_action, f"Connessione a {ssid}…")

    def after_action(self, res):
        ok, err = res
        self.mgr.toast("Fatto" if ok else err)
        self.refresh(scan=False)


class WifiDetail(Screen):
    def __init__(self, mgr, parent, net):
        super().__init__(mgr)
        self.parent, self.net = parent, net
        self.title = net["ssid"]

    def build(self):
        b = self.body
        n, saved = self.net, self.parent.saved
        st = self.parent.status or {}
        items = [
            {"title": "Stato", "right": "Connessa" if n["inuse"] else "Salvata", "static": True},
            {"title": "Segnale", "right": f"{n['signal']}%", "static": True},
            {"title": "Sicurezza", "right": n["security"] or "Nessuna", "static": True},
        ]
        if n["inuse"] and st.get("ip"):
            items.append({"title": "Indirizzo IP", "right": st["ip"], "static": True})
        lv = ListView((b.x, b.y, b.w, b.h - 60), items, 40)
        bw = (b.w - 36) // 2
        y = b.bottom - 52
        if n["inuse"]:
            act = Button((12, y, bw, 42), "Disconnetti", self.disconnect)
        else:
            act = Button((12, y, bw, 42), "Connetti", self.connect, "primary")
        forget = Button((24 + bw, y, bw, 42), "Dimentica", self.forget, "danger")
        forget.enabled = n["ssid"] in saved
        self.widgets = [lv, act, forget]

    def _do(self, fn, busy):
        self.mgr.pop()
        self.mgr.run(fn, self.parent.after_action, busy)

    def connect(self):
        name = self.parent.saved.get(self.net["ssid"], self.net["ssid"])
        self._do(lambda: sysm.wifi_up(name), f"Connessione a {self.net['ssid']}…")

    def disconnect(self):
        self.mgr.confirm("Disconnettere?", "Se sei collegato via SSH tramite questa rete perderai la connessione.",
                         "Disconnetti", lambda: self._do(sysm.wifi_disconnect, "Disconnessione…"), True)

    def forget(self):
        name = self.parent.saved.get(self.net["ssid"], self.net["ssid"])
        self.mgr.confirm("Dimenticare la rete?", f"La password salvata per {self.net['ssid']} verrà eliminata.",
                         "Dimentica", lambda: self._do(lambda: sysm.wifi_forget(name), "Eliminazione…"), True)


# ================================================================ Bluetooth
class BtScreen(Screen):
    title = "Bluetooth"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.powered, self.devices, self.loaded = None, [], False

    def enter(self):
        self.build()
        self.refresh()

    def refresh(self, scan=False):
        def job():
            powered, present = sysm.bt_powered()
            if not present:
                return None, []
            devs = sysm.bt_scan(10) if (scan and powered) else sysm.bt_list()
            return powered, devs

        def done(res):
            self.powered, self.devices = res
            self.loaded = True
            self.build()

        self.mgr.run(job, done, "Ricerca dispositivi (10 s)…" if scan else "Lettura dispositivi…")

    def build(self):
        a, b = self.area, self.body
        tg = Toggle((a.right - 64, a.y + 6, 52, 28), self.powered, self.set_power)
        tg.enabled = self.powered is not None and self.loaded
        scan = Button((b.right - 104, b.y + 6, 96, 30), "Cerca", lambda: self.refresh(True), size=13)
        scan.enabled = bool(self.powered)
        items = []
        for d in self.devices:
            sub = "Connesso" if d["connected"] else "Associato" if d["paired"] else "Disponibile"
            items.append({"title": d["name"], "subtitle": f"{sub} · {d['mac']}", "dev": d, "icon": icon_bt,
                          "icon_color": T["accent"] if d["connected"] else T["muted"],
                          "subtitle_color": T["ok"] if d["connected"] else T["muted"], "chevron": True})
        if not self.loaded:
            empty = ""
        elif self.powered is None:
            empty = "Nessun adattatore Bluetooth trovato"
        elif not self.powered:
            empty = "Bluetooth spento"
        else:
            empty = "Nessun dispositivo: premi Cerca"
        lv = ListView((b.x, b.y + 42, b.w, b.h - 42), items, ROW_H, on_select=self.select, empty_text=empty)
        self.widgets = [lv, scan, tg]

    def draw_content(self, s):
        b = self.body
        if self.powered:
            msg, col = f"Visibile come {sysm.hostname()}", T["ok"]
        elif self.powered is False:
            msg, col = "Spento", T["muted"]
        else:
            msg, col = ("Non disponibile" if self.loaded else "Lettura stato…"), T["muted"]
        text(s, msg, (b.x + 14, b.y + 21), 13, col, anchor="midleft", maxw=b.w - 130)

    def set_power(self, on):
        def job():
            ok, err = sysm.bt_set_power(on)
            time.sleep(0.5)
            return ok, err

        def done(res):
            if not res[0]:
                self.mgr.toast(res[1] or "Operazione non riuscita")
            self.refresh()

        self.mgr.run(job, done, "Accensione…" if on else "Spegnimento…")

    def select(self, it):
        self.mgr.push(BtDetail(self.mgr, self, it["dev"]))

    def after_action(self, res):
        ok, err = res
        self.mgr.toast("Fatto" if ok else err or "Operazione non riuscita")
        self.refresh()


class BtDetail(Screen):
    def __init__(self, mgr, parent, dev):
        super().__init__(mgr)
        self.parent, self.dev = parent, dev
        self.title = dev["name"]

    def build(self):
        b, d = self.body, self.dev
        items = [
            {"title": "Indirizzo", "right": d["mac"], "static": True},
            {"title": "Stato", "right": "Connesso" if d["connected"] else "Associato" if d["paired"]
             else "Non associato", "static": True},
        ]
        lv = ListView((b.x, b.y, b.w, b.h - 60), items, 40)
        bw = (b.w - 36) // 2
        y = b.bottom - 52
        if not d["paired"]:
            main = Button((12, y, b.w - 24, 42), "Associa e connetti", self.pair, "primary")
            self.widgets = [lv, main]
            return
        if d["connected"]:
            main = Button((12, y, bw, 42), "Disconnetti", self.disconnect)
        else:
            main = Button((12, y, bw, 42), "Connetti", self.connect, "primary")
        rem = Button((24 + bw, y, bw, 42), "Rimuovi", self.remove, "danger")
        self.widgets = [lv, main, rem]

    def draw_content(self, s):
        if not self.dev["paired"]:
            b = self.body
            text(s, "Metti il dispositivo in modalità abbinamento prima di associarlo.",
                 (b.centerx, b.bottom - 72), 12, T["muted"], anchor="center")

    def _do(self, fn, busy):
        self.mgr.pop()
        self.mgr.run(fn, self.parent.after_action, busy)

    def pair(self):
        self._do(lambda: sysm.bt_pair_connect(self.dev["mac"]), "Associazione (fino a 30 s)…")

    def connect(self):
        self._do(lambda: sysm.bt_connect(self.dev["mac"]), "Connessione…")

    def disconnect(self):
        self._do(lambda: sysm.bt_disconnect(self.dev["mac"]), "Disconnessione…")

    def remove(self):
        self.mgr.confirm("Rimuovere il dispositivo?", "Andrà associato di nuovo per riutilizzarlo.", "Rimuovi",
                         lambda: self._do(lambda: sysm.bt_remove(self.dev["mac"]), "Rimozione…"), True)


# ================================================================== Sistema
class SystemScreen(Screen):
    title = "Sistema"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.items, self.next, self.loading = [], 0, False

    def update(self, now):
        if now >= self.next and not self.loading:
            self.loading = True
            self.next = now + 3
            self.mgr.run(self.collect, self.done)

    @staticmethod
    def collect():
        rows = [("Nome host", sysm.hostname()), ("Indirizzo IP", ", ".join(sysm.ip_addresses()) or "—")]
        t = sysm.cpu_temp()
        rows.append(("Temperatura CPU", f"{t:.1f} °C" if t is not None else "—"))
        try:
            import os
            l1, l5, _ = os.getloadavg()
            rows.append(("Carico CPU (1/5 min)", f"{l1:.2f} / {l5:.2f}"))
        except OSError:
            pass
        m = sysm.mem_info()
        if m:
            rows.append(("Memoria", f"{sysm.human_bytes(m[0] - m[1])} / {sysm.human_bytes(m[0])}"))
        d = sysm.disk_info()
        if d:
            rows.append(("Spazio disco", f"{sysm.human_bytes(d[1])} / {sysm.human_bytes(d[0])}"))
        up = sysm.uptime()
        if up:
            rows.append(("Acceso da", sysm.human_duration(up)))
        th = sysm.throttled()
        if th is None:
            pw, col = "—", None
        elif th["now_undervolt"]:
            pw, col = "Sottotensione ORA", T["danger"]
        elif th["past_undervolt"]:
            pw, col = "Sottotensione dall'avvio", T["warn"]
        elif th["now_throttled"]:
            pw, col = "CPU rallentata (calore)", T["warn"]
        else:
            pw, col = "OK", T["ok"]
        rows.append(("Alimentazione", pw, col))
        rows += [("Sistema operativo", sysm.os_name()), ("Kernel", sysm.kernel())]
        return rows

    def done(self, rows):
        self.loading = False
        self.items = [{"title": r[0], "right": r[1], "static": True,
                       **({"right_color": r[2]} if len(r) > 2 and r[2] else {})} for r in rows]
        old = self.widgets[0].offset if self.widgets else 0
        lv = ListView(self.body, self.items, 40)
        lv.offset = min(old, lv.max_offset())
        self.widgets = [lv]


# =========================================================== Schermo e touch
class DisplayScreen(Screen):
    title = "Schermo e touch"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.speed = None

    def enter(self):
        self.speed = sysm.spi_speed_get()
        self.build()

    def build(self):
        rot = self.mgr.ctx.config.get("rot", 90)
        items = [
            {"title": "Capovolgi schermo", "subtitle": f"Rotazione attuale: {rot}°", "act": self.flip},
            {"title": "Calibra touch", "subtitle": "Tocca 5 mirini per migliorare la precisione", "chevron": True,
             "act": lambda: self.mgr.push(CalibScreen(self.mgr))},
            {"title": "Velocità SPI", "subtitle": "Più alta = schermo più fluido (richiede riavvio)",
             "right": f"{self.speed // 1_000_000} MHz" if self.speed else "?", "chevron": True,
             "act": lambda: self.mgr.push(SpiScreen(self.mgr, self.speed))},
        ]
        self.widgets = [ListView(self.body, items, 54, on_select=lambda it: it["act"]())]

    def flip(self):
        ctx = self.mgr.ctx
        ctx.set_rotation(270 if ctx.config.get("rot", 90) == 90 else 90)
        self.build()
        self.mgr.toast("Schermo capovolto")


class SpiScreen(Screen):
    title = "Velocità SPI"
    OPTIONS = [16, 24, 32, 40]

    def __init__(self, mgr, current):
        super().__init__(mgr)
        self.current = current

    def build(self):
        b = self.body
        items = []
        for mhz in self.OPTIONS:
            cur = self.current == mhz * 1_000_000
            note = {16: "Sicura", 24: "Di solito stabile", 32: "Spesso funziona", 40: "Sperimentale"}[mhz]
            items.append({"title": f"{mhz} MHz", "subtitle": note, "mhz": mhz,
                          "right": "attuale" if cur else "", "right_color": T["ok"]})
        self.widgets = [ListView((b.x, b.y, b.w, b.h - 44), items, 46, on_select=self.pick)]

    def draw_content(self, s):
        b = self.body
        text(s, "Se lo schermo resta bianco, rimetti speed=16000000 in config.txt via SSH.",
             (b.centerx, b.bottom - 22), 11, T["muted"], anchor="center", maxw=b.w - 20)

    def pick(self, it):
        hz = it["mhz"] * 1_000_000
        if hz == self.current:
            return

        def apply():
            ok, err = sysm.spi_speed_set(hz)
            if ok:
                self.mgr.pop()
                self.mgr.confirm("Riavviare ora?", f"La velocità {it['mhz']} MHz sarà attiva dopo il riavvio.",
                                 "Riavvia", lambda: do_power(self.mgr, "reboot"))
            else:
                self.mgr.toast(err)

        self.mgr.confirm(f"Impostare {it['mhz']} MHz?", "Viene salvata una copia di config.txt "
                         "(config.txt.pilauncher.bak).", "Imposta", apply)


# =============================================================== Data e ora
class TimeScreen(Screen):
    title = "Data e ora"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.tz, self.ntp = sysm_tz_cache(), None

    def enter(self):
        self.build()
        self.load()

    def resume(self):
        self.tz = sysm_tz_cache()
        self.build()

    def load(self):
        def done(res):
            self.tz, self.ntp = res
            _tz["v"] = self.tz
            self.build()

        self.mgr.run(lambda: (sysm.tz_current(), sysm.ntp_synced()), done)

    def build(self):
        b = self.body
        items = [
            {"title": "Fuso orario", "right": self.tz, "chevron": True,
             "act": lambda: self.mgr.push(TzScreen(self.mgr, self.tz))},
            {"title": "Sincronizzazione automatica", "static": True,
             "right": "—" if self.ntp is None else "Sincronizzata" if self.ntp else "Non sincronizzata",
             "right_color": T["ok"] if self.ntp else T["muted"]},
        ]
        self.widgets = [ListView((b.x, b.y + 92, b.w, b.h - 92), items, ROW_H,
                                 on_select=lambda it: it["act"]())]

    def draw_content(self, s):
        b = self.body
        now = time.localtime()
        text(s, time.strftime("%H:%M", now), (b.centerx, b.y + 36), 40, bold=True, anchor="center")
        text(s, time.strftime("%d/%m/%Y", now), (b.centerx, b.y + 72), 14, T["muted"], anchor="center")
        pygame.draw.line(s, T["line"], (b.x, b.y + 91), (b.right, b.y + 91))


class TzScreen(Screen):
    title = "Fuso orario"

    def __init__(self, mgr, current):
        super().__init__(mgr)
        self.current, self.zones = current, []

    def enter(self):
        self.build()

        def done(zones):
            self.zones = zones
            self.build()
            if self.current in zones:
                self.widgets[0].scroll_to(zones.index(self.current))

        self.mgr.run(sysm.tz_list, done, "Caricamento…")

    def build(self):
        items = [{"title": z, "tz": z, "right": "attuale" if z == self.current else "", "right_color": T["ok"]}
                 for z in self.zones]
        old = self.widgets[0].offset if self.widgets else 0
        lv = ListView(self.body, items, 40, on_select=self.pick)
        lv.offset = min(old, lv.max_offset())
        self.widgets = [lv]

    def pick(self, it):
        tz = it["tz"]

        def done(res):
            ok, err = res
            if ok:
                _tz["v"] = tz
                self.mgr.pop()
                self.mgr.toast(f"Fuso orario: {tz}")
            else:
                self.mgr.toast(err or "Operazione non riuscita")

        self.mgr.run(lambda: sysm.tz_set(tz), done, "Impostazione…")


# ============================================================ Alimentazione
def do_power(mgr, action):
    if action == "reboot":
        mgr.push(Message(mgr, "Riavvio…", "Il launcher ripartirà da solo tra poco."))
        mgr.run(lambda: (time.sleep(1), sysm.reboot()))
    else:
        mgr.push(Message(mgr, "Spegnimento…", "Attendi che il LED verde smetta di lampeggiare prima di staccare "
                                              "l'alimentazione. Lo schermo resterà acceso finché c'è corrente."))
        mgr.run(lambda: (time.sleep(1), sysm.poweroff()))


class PowerScreen(Screen):
    title = "Alimentazione"

    def build(self):
        b = self.body
        w = b.w - 40
        self.widgets = [
            Button((20, b.y + 20, w, 50), "Riavvia launcher", lambda: self.mgr.confirm(
                "Riavviare il launcher?", "Il programma si chiude e riparte (serve il servizio systemd).",
                "Riavvia", self.restart_launcher)),
            Button((20, b.y + 84, w, 50), "Riavvia il Raspberry", lambda: self.mgr.confirm(
                "Riavviare?", "Il Raspberry Pi verrà riavviato.", "Riavvia",
                lambda: do_power(self.mgr, "reboot")), "primary"),
            Button((20, b.y + 148, w, 50), "Spegni", lambda: self.mgr.confirm(
                "Spegnere?", "Per riaccenderlo dovrai staccare e ricollegare l'alimentazione.", "Spegni",
                lambda: do_power(self.mgr, "poweroff"), True), "danger"),
        ]

    def restart_launcher(self):
        self.mgr.quit = True


# ============================================================ Aggiornamenti
def update_subtitle(mgr):
    up = mgr.ctx.updater
    if up is None:
        return ""
    if up.newer_available():
        return f"Disponibile {up.latest['tag']} (in uso {up.version})"
    return f"Versione {up.version}"


def clean_notes(body):
    """Note di release generate da GitHub -> righe leggibili sul display."""
    out = []
    for ln in body.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln.startswith("**Full Changelog"):
            continue
        ln = re.sub(r" by @\S+ in \S+$", "", ln)
        ln = re.sub(r"https?://\S+", "", ln).strip()
        if ln.startswith(("* ", "- ")):
            ln = "• " + ln[2:]
        out.append(ln)
    return out


class UpdateScreen(Screen):
    title = "Aggiornamenti"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.up = mgr.ctx.updater
        self.progress = ""
        self.working = False

    def enter(self):
        self.build()
        if self.up.enabled and time.time() - self.up.checked_at > 300:
            self.check()

    def check(self):
        def done(_):
            self.mgr.status["update"] = self.up.newer_available()
            self.build()
            if not self.up.newer_available():
                self.mgr.toast("Il launcher è aggiornato")

        self.mgr.run(self.up.check, done, "Controllo aggiornamenti…")

    def build(self):
        b = self.body
        w = b.w - 40
        self.widgets = []
        if not self.up.enabled or self.working:
            return
        if self.up.newer_available():
            self.widgets.append(Button((20, b.bottom - 58, w // 2 - 6, 46), "Controlla", self.check))
            self.widgets.append(Button((20 + w // 2 + 6, b.bottom - 58, w // 2 - 6, 46),
                                       f"Installa {self.up.latest['tag']}", self.ask_install, "primary", size=14))
        else:
            self.widgets.append(Button((20, b.bottom - 58, w, 46), "Controlla aggiornamenti", self.check))

    def draw_content(self, s):
        b, up = self.body, self.up
        x = b.x + 20
        text(s, "Versione in uso", (x, b.y + 14), 12, T["muted"])
        text(s, up.version, (x, b.y + 30), 20, bold=True)
        if up.latest:
            col = T["accent"] if up.newer_available() else T["muted"]
            text(s, "Ultima pubblicata", (b.centerx, b.y + 14), 12, T["muted"])
            text(s, up.latest["tag"], (b.centerx, b.y + 30), 20, col, bold=True)
        y = b.y + 66
        if not up.enabled:
            lines = ["Installazione di sviluppo: aggiornamenti disattivati.",
                     "Installa con lo script da GitHub per attivare gli aggiornamenti OTA."]
        elif self.working:
            lines = [self.progress or "Preparazione…", "Non spegnere il Raspberry."]
        elif up.error:
            lines = [up.error]
        elif up.newer_available():
            lines = ["Novità:"] + (clean_notes(up.latest["notes"]) or ["(nessuna nota)"])
        elif up.latest:
            lines = ["Nessun aggiornamento disponibile."]
        else:
            lines = []
        bad = up.rolled_back()
        if bad and not self.working:
            lines = [f"{bad} non partiva ed è stata annullata."] + lines
        max_y = b.bottom - 66
        for ln in lines:
            for part in wrap(ln, 13, b.w - 40):
                if y > max_y - 18:
                    return
                text(s, part, (x, y), 13, T["text"] if self.working else T["muted"])
                y += 18

    def ask_install(self):
        tag = self.up.latest["tag"]
        self.mgr.confirm(f"Installare {tag}?", "Il launcher scarica la nuova versione e si riavvia. "
                         "Se non parte, torna da solo alla versione attuale.", "Installa", self.install)

    def install(self):
        self.working, self.progress = True, ""
        self.build()

        def prog(msg):
            self.progress = msg
            self.mgr.dirty = True

        def job():
            try:
                return self.up.install(prog), None
            except Exception as e:  # noqa: BLE001
                return None, e

        def done(res):
            tag, err = res
            self.working = False
            if err is not None:
                self.build()
                self.mgr.toast(f"Aggiornamento non riuscito: {err}", 5)
                return
            self.mgr.push(Message(self.mgr, f"Aggiornato a {tag}", "Riavvio del launcher…"))
            self.mgr.run(lambda: time.sleep(1.5), lambda _: setattr(self.mgr, "quit", True))

        self.mgr.run(job, done)

    def resume(self):
        self.build()


# ===================================================================== APP
def _icon(s, c, sz, col, hole=None):
    icon_gear(s, c, sz, col, hole)


APP = {"name": "Impostazioni", "icon": _icon, "icon_hole": True, "color": (88, 98, 118), "order": 0,
       "screen": SettingsMain}
