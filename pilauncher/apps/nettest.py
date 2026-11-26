"""Tester rete: diagnostica della presa Ethernet per l'helpdesk.

Collegando il cavo parte da solo: link, switch e porta (LLDP/CDP), 802.1X, DHCP, gateway, DNS, Internet.
Strumenti: ping continuo, rinnovo DHCP, lampeggio della porta sullo switch, test del cavo, risoluzione DNS.
"""
import threading
import time

import pygame

from core import netdiag as nd
from core.framework import Screen
from core.keyboard import Keyboard
from core.ui import T, Button, ListView, rrect, text, thick_arc, wrap

ROW_H = 43
LISTEN_MAX = 65          # LLDP arriva ogni ~30 s, CDP ogni ~60 s
DHCP_WAIT = 40
INTERNET_URL = "http://connectivitycheck.gstatic.com/generate_204"
HTTPS_URL = "https://www.google.com/generate_204"
DNS_TEST_NAME = "www.google.com"

ORDER = ["link", "switch", "ip", "gw", "dns", "inet"]
NAMES = {"link": "Cavo e link", "switch": "Switch e porta", "ip": "Indirizzo IP (DHCP)", "gw": "Gateway",
         "dns": "DNS", "inet": "Internet"}


# ================================================================ disegno
def status_icon(st):
    def draw(s, c, sz, col=None):
        cx, cy = c
        r = 9
        if st == "ok":
            pygame.draw.circle(s, T["ok"], c, r)
            pygame.draw.lines(s, T["bg"], False, [(cx - 4, cy), (cx - 1, cy + 3), (cx + 4, cy - 3)], 2)
        elif st == "warn":
            pygame.draw.circle(s, T["warn"], c, r)
            pygame.draw.line(s, T["bg"], (cx, cy - 5), (cx, cy + 1), 2)
            pygame.draw.circle(s, T["bg"], (cx, cy + 4), 1)
        elif st == "fail":
            pygame.draw.circle(s, T["danger"], c, r)
            pygame.draw.line(s, T["bg"], (cx - 3, cy - 3), (cx + 3, cy + 3), 2)
            pygame.draw.line(s, T["bg"], (cx + 3, cy - 3), (cx - 3, cy + 3), 2)
        elif st == "run":
            a = (time.time() * 4) % 6.283
            pygame.draw.circle(s, T["line"], c, r, 2)
            thick_arc(s, T["accent"], c, r - 1, a, a + 1.8, 3, 8)
        elif st == "off":
            pygame.draw.line(s, T["muted"], (cx - 5, cy), (cx + 5, cy), 2)
        else:
            pygame.draw.circle(s, T["line"], c, r, 2)
    return draw


def icon_net(s, c, sz, col):
    """Icona dell'app: presa RJ45 stilizzata."""
    cx, cy = c
    w, h = sz * 0.7, sz * 0.56
    body = pygame.Rect(0, 0, w, h)
    body.center = (cx, cy + sz * 0.04)
    pygame.draw.rect(s, col, body, max(2, int(sz * 0.08)), border_radius=3)
    tab = pygame.Rect(0, 0, w * 0.4, h * 0.26)
    tab.midtop = (cx, body.bottom - max(2, int(sz * 0.08)))
    pygame.draw.rect(s, col, tab)
    for i in range(4):
        x = body.x + w * (0.22 + i * 0.187)
        pygame.draw.line(s, col, (x, body.y + h * 0.22), (x, body.y + h * 0.5), max(2, int(sz * 0.05)))


# ============================================================ diagnostica
class Diagnosis:
    """Esegue i controlli in un thread e tiene lo stato da mostrare."""

    def __init__(self, on_change):
        self.on_change = on_change
        self.checks = {}
        self.li, self.ipi = None, None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.rerun = threading.Event()
        self.running = False
        self.link_up_at = None
        self.listener = nd.NeighborListener(on_change=self._changed)
        self.reset("wait", "")

    def _changed(self):
        self.on_change()

    def set(self, key, st, summary, rows=None, hints=None):
        with self.lock:
            self.checks[key] = {"st": st, "sum": summary, "rows": rows or [], "hints": hints or []}
        self.on_change()

    def reset(self, st, summary):
        for k in ORDER:
            if k != "switch":
                self.set(k, st, summary)
        self.set("switch", st, summary)

    def start(self):
        if not nd.iface_present():
            for k in ORDER:
                self.set(k, "off", "")
            self.set("link", "fail", f"Interfaccia {nd.IFACE} non trovata")
            return
        self.listener.start()
        threading.Thread(target=self._loop, daemon=True).start()

    def close(self):
        self.stop.set()
        self.listener.close()

    # ciclo: segue il cavo e lancia la sequenza quando il link sale
    def _loop(self):
        was_up = None
        while not self.stop.is_set():
            up = nd.carrier()
            if up != was_up or self.rerun.is_set():
                self.rerun.clear()
                was_up = up
                if up:
                    if self.link_up_at is None:
                        self.link_up_at = time.time()
                    self._sequence()
                else:
                    self.link_up_at = None
                    self.listener.reset()
                    self.reset("off", "")
                    li = nd.link_info()
                    self.li = li
                    self.set("link", "fail", "Nessun cavo collegato", self._link_rows(li))
            self.stop.wait(1)

    def _sequence(self):
        self.running = True
        try:
            for k in ORDER:
                if k != "switch":
                    self.set(k, "wait", "")
            self._check_link()
            if not nd.carrier():
                return
            if not self._check_ip():
                for k in ("gw", "dns", "inet"):
                    self.set(k, "off", "Serve un indirizzo IP")
                return
            self._check_gw()
            self._check_dns()
            self._check_inet()
        finally:
            self.running = False
            self.on_change()

    # ---------------------------------------------------------- singoli test
    @staticmethod
    def _link_rows(li):
        rows = [("Interfaccia", nd.IFACE), ("MAC del tester", li["mac"] or "—")]
        if li["carrier"]:
            rows += [("Velocità", nd.fmt_speed(li["speed"])), ("Duplex", (li["duplex"] or "?").capitalize())]
        if li["partner_max"]:
            rows.append(("Massimo dello switch", nd.fmt_speed(li["partner_max"])))
        if li["autoneg"]:
            rows.append(("Autonegoziazione", "Sì" if li["autoneg"] == "on" else "No"))
        rows += [("Errori CRC", str(li["rx_crc"] or 0)),
                 ("Errori rx / tx", f"{li['rx_err'] or 0} / {li['tx_err'] or 0}"),
                 ("Cambi di link dall'avvio", str(li["flaps"] or 0))]
        return rows

    def _check_link(self):
        self.set("link", "run", "Lettura del link…")
        li = nd.link_info()
        self.li = li
        if not li["carrier"]:
            self.set("link", "fail", "Nessun cavo collegato", self._link_rows(li))
            return
        hints = nd.link_hints(li)
        dup = {"full": "Full duplex", "half": "Half duplex"}.get(li["duplex"], "duplex ?")
        summary = f"{nd.fmt_speed(li['speed'])} · {dup}"
        self.set("link", "warn" if hints else "ok", summary, self._link_rows(li), hints)

    def _check_ip(self):
        t0 = self.link_up_at or time.time()
        while not self.stop.is_set():
            ipi = nd.ip_info()
            self.ipi = ipi
            if ipi["addr"]:
                break
            waited = time.time() - t0
            if waited > DHCP_WAIT or not nd.carrier():
                self.set("ip", "fail", "Nessuna risposta DHCP", [("Stato NetworkManager", ipi["nm_state"] or "—")],
                         self._no_dhcp_hints())
                return False
            self.set("ip", "run", f"Attesa DHCP… {int(waited)} s")
            self.stop.wait(1)
        else:
            return False
        rows = [("Indirizzo", f"{ipi['addr']}/{ipi['prefix']}"),
                ("Tipo", "DHCP" if ipi["dynamic"] else "Statico"),
                ("Gateway", ipi["gateway"] or "—"),
                ("DNS", ", ".join(ipi["dns"]) or "—"),
                ("Dominio", ipi["domain"] or "—"),
                ("Server DHCP", ipi["dhcp_server"] or "—")]
        if ipi["lease_time"]:
            rows.append(("Durata lease", _dur(ipi["lease_time"])))
        if ipi["lease_left"] is not None:
            rows.append(("Lease rimanente", _dur(ipi["lease_left"])))
        hints = []
        if ipi["addr"].startswith("169.254."):
            hints.append("Indirizzo automatico 169.254: il DHCP non ha risposto")
        if not ipi["gateway"]:
            hints.append("Nessun gateway ricevuto dal DHCP")
        if not ipi["dns"]:
            hints.append("Nessun server DNS ricevuto dal DHCP")
        self.set("ip", "warn" if hints else "ok", f"{ipi['addr']}/{ipi['prefix']}", rows, hints)
        return True

    def _no_dhcp_hints(self):
        h = []
        if self.listener.eapol:
            h.append("La porta chiede l'autenticazione 802.1X: senza credenziali non dà accesso")
        nb = self.listener.neighbor
        if nb and nb.get("vlan"):
            h.append(f"La porta è sulla VLAN {nb['vlan']}: verifica che lì ci sia un DHCP")
        h.append("Possibili cause: porta disattivata o in una VLAN senza DHCP, NAC/802.1X, server DHCP pieno")
        return h

    def _check_gw(self):
        gw = self.ipi["gateway"]
        if not gw:
            self.set("gw", "off", "Nessun gateway")
            return
        self.set("gw", "run", f"Ping a {gw}…")
        p = nd.ping(gw, 5)
        rows = [("Indirizzo", gw)] + _ping_rows(p)
        if not p.get("sent"):
            self.set("gw", "fail", p["error"], rows)
        elif p["recv"] == 0:
            self.set("gw", "warn", f"{gw} non risponde al ping", rows,
                     ["Alcuni gateway bloccano il ping: guarda se DNS e Internet funzionano"])
        else:
            st = "warn" if p["loss"] else "ok"
            self.set("gw", st, f"{gw} · {p['avg']:.1f} ms · {p['loss']}% persi", rows,
                     ["Pacchetti persi: link instabile o rete congestionata"] if p["loss"] else [])

    def _check_dns(self):
        servers = self.ipi["dns"]
        if not servers:
            self.set("dns", "off", "Nessun server DNS")
            return
        self.set("dns", "run", f"Interrogo {servers[0]}…")
        rows, good, hints, best = [], 0, [], None
        names = [DNS_TEST_NAME] + ([self.ipi["domain"]] if self.ipi["domain"] else [])
        for srv in servers[:3]:
            for name in names:
                r = nd.dns_query(srv, name)
                if r["ok"]:
                    good += 1
                    best = best if best and best["ms"] <= r["ms"] else r
                    val = f"{r['ms']:.0f} ms · {', '.join(r['ips'][:3])}"
                else:
                    val = r["error"]
                    if name == DNS_TEST_NAME:
                        hints.append(f"{srv} non risolve nomi esterni")
                rows.append((f"{name} via {srv}", val))
        total = len(rows)
        if good == 0:
            self.set("dns", "fail", "Nessun server DNS risponde", rows, hints)
        else:
            self.set("dns", "warn" if good < total else "ok", f"{good}/{total} risposte · {best['ms']:.0f} ms",
                     rows, hints)

    def _check_inet(self):
        self.set("inet", "run", "Prova di connessione…")
        h = nd.http_check(INTERNET_URL)
        s = nd.http_check(HTTPS_URL)
        rows = [("HTTP", _http_txt(h)), ("HTTPS", _http_txt(s))]
        if h["code"] == 204 and s["code"] in (200, 204):
            self.set("inet", "ok", f"Raggiungibile · {s['ms']:.0f} ms", rows)
        elif h["code"] or s["code"]:
            self.set("inet", "warn", "Risposta inattesa", rows,
                     ["Il traffico passa da un proxy o da un portale di accesso"])
        else:
            self.set("inet", "fail", "Non raggiungibile", rows,
                     ["Internet bloccata: in azienda potrebbe servire il proxy, oppure il firewall blocca la rete"])

    # ------------------------------------------------------------- switch
    def switch_state(self):
        if not nd.carrier():
            return {"st": "off", "sum": "", "rows": [], "hints": []}
        lst = self.listener
        if lst.error:
            return {"st": "fail", "sum": lst.error, "rows": [], "hints": []}
        nb = lst.neighbor
        rows, hints = [], []
        if lst.eapol:
            hints.append("La porta chiede l'autenticazione 802.1X")
        if nb:
            name = nb.get("name") or nb.get("chassis") or "Switch"
            port = nb.get("port") or "?"
            summary = f"{name} · {port}" + (f" · VLAN {nb['vlan']}" if nb.get("vlan") else "")
            for k, lab in (("name", "Switch"), ("port", "Porta"), ("port_desc", "Descrizione porta"),
                           ("vlan", "VLAN dati"), ("voice_vlan", "VLAN voce"), ("mgmt", "IP di gestione"),
                           ("platform", "Modello"), ("chassis", "ID chassis"), ("desc", "Sistema"),
                           ("duplex", "Duplex (switch)"), ("proto", "Protocollo")):
                if nb.get(k):
                    rows.append((lab, str(nb[k])))
            if nb.get("vlan_names"):
                rows += [(f"Nome VLAN {v}", n) for v, n in nb["vlan_names"].items()]
            if lst.eapol:
                rows.append(("802.1X", "Richiesto"))
            return {"st": "warn" if hints else "ok", "sum": summary, "rows": rows, "hints": hints}
        waited = time.time() - lst.started
        if waited < LISTEN_MAX:
            extra = " · 802.1X attivo" if lst.eapol else ""
            return {"st": "run", "sum": f"In ascolto LLDP/CDP… {int(waited)} s{extra}", "rows": [], "hints": hints}
        hints.append("Lo switch non invia LLDP/CDP (disattivati, switch non gestito o presa a muro su hub)")
        return {"st": "warn", "sum": "Nessun annuncio dallo switch" + (" · 802.1X attivo" if lst.eapol else ""),
                "rows": rows, "hints": hints}

    def get(self, key):
        if key == "switch":
            return self.switch_state()
        with self.lock:
            return dict(self.checks.get(key, {"st": "wait", "sum": "", "rows": [], "hints": []}))


def _dur(sec):
    sec = int(sec)
    if sec >= 86400:
        return f"{sec // 86400} g {sec // 3600 % 24} h"
    if sec >= 3600:
        return f"{sec // 3600} h {sec // 60 % 60} min"
    return f"{sec // 60} min {sec % 60} s"


def _ping_rows(p):
    if not p.get("sent"):
        return [("Errore", p.get("error", "?"))]
    rows = [("Risposte", f"{p['recv']}/{p['sent']} ({p['loss']}% persi)")]
    if p["avg"] is not None:
        rows.append(("Tempo min / medio / max", f"{p['min']:.1f} / {p['avg']:.1f} / {p['max']:.1f} ms"))
    return rows


def _http_txt(r):
    if r["code"]:
        return f"codice {r['code']} · {r['ms']:.0f} ms"
    return r["error"]


# ================================================================ schermate
class NetTest(Screen):
    title = "Tester rete"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.diag = Diagnosis(self._changed)
        self.next_tick = 0

    def _changed(self):
        self.mgr.dirty = True

    def enter(self):
        self.build()
        self.diag.start()

    def leave(self):
        if self not in self.mgr.stack:  # uscita dall'app, non apertura di una sottoschermata
            self.diag.close()

    def build(self):
        a, b = self.area, self.body
        old = self.widgets[0].offset if self.widgets else 0
        lv = ListView(b, [{"key": k} for k in ORDER], ROW_H, render=self._row, on_select=self.open_detail)
        lv.offset = min(old, lv.max_offset())
        self.widgets = [
            lv,
            Button((a.right - 186, a.y + 6, 96, 28), "Strumenti", lambda: self.mgr.push(Tools(self.mgr, self)),
                   size=13),
            Button((a.right - 84, a.y + 6, 76, 28), "Ripeti", self.repeat, size=13),
        ]

    def _row(self, s, r, it):
        c = self.diag.get(it["key"])
        status_icon(c["st"])(s, (r.x + 24, r.centery), 20)
        x, right = r.x + 46, r.right - 30
        if c["rows"] or c["hints"]:
            pygame.draw.lines(s, T["muted"], False, [(r.right - 18, r.centery - 5), (r.right - 13, r.centery),
                                                     (r.right - 18, r.centery + 5)], 2)
        text(s, NAMES[it["key"]], (x, r.centery - 9), 14, anchor="midleft", maxw=right - x)
        col = {"ok": T["ok"], "warn": T["warn"], "fail": T["danger"]}.get(c["st"], T["muted"])
        text(s, c["sum"] or ("In attesa" if c["st"] == "wait" else ""), (x, r.centery + 10), 12, col,
             anchor="midleft", maxw=right - x)

    def update(self, now):
        # ridisegno 2 volte al secondo mentre qualcosa è in corso (contatori e icona che gira)
        busy = self.diag.running or self.diag.get("switch")["st"] == "run"
        if busy and now >= self.next_tick:
            self.next_tick = now + 0.5
            self.mgr.dirty = True

    def repeat(self):
        self.diag.listener.reset()
        self.diag.rerun.set()

    def open_detail(self, it):
        c = self.diag.get(it["key"])
        if c["rows"] or c["hints"]:
            self.mgr.push(Detail(self.mgr, NAMES[it["key"]], c["rows"], c["hints"]))


class Detail(Screen):
    def __init__(self, mgr, title, rows, hints=()):
        super().__init__(mgr)
        self.title = title
        self.rows, self.hints = rows, list(hints)

    def build(self):
        items = [{"title": h, "static": True, "title_color": T["warn"], "hint": True} for h in self.hints]
        items += [{"title": k, "subtitle": v, "static": True} for k, v in self.rows]
        self.widgets = [ListView(self.body, items, 46, render=_detail_row)]


def _detail_row(s, r, it):
    x, maxw = r.x + 14, r.w - 28
    if it.get("hint"):
        lines = wrap(it["title"], 12, maxw - 14)[:2]
        pygame.draw.circle(s, T["warn"], (x + 3, r.centery), 3)
        for i, ln in enumerate(lines):
            text(s, ln, (x + 14, r.centery + (i - (len(lines) - 1) / 2) * 16), 12, T["warn"], anchor="midleft")
        return
    text(s, it["title"], (x, r.centery - 9), 12, T["muted"], anchor="midleft", maxw=maxw)
    text(s, it["subtitle"], (x, r.centery + 9), 14, anchor="midleft", maxw=maxw)


# ================================================================ strumenti
class Tools(Screen):
    title = "Strumenti di rete"

    def __init__(self, mgr, main):
        super().__init__(mgr)
        self.main = main

    def build(self):
        items = [
            {"title": "Ping continuo", "subtitle": "Verso un indirizzo o un nome a scelta", "act": self.ping},
            {"title": "Lampeggia la porta sullo switch", "subtitle": "Per trovare la porta nell'armadio di rete",
             "act": self.blink},
            {"title": "Test del cavo", "subtitle": "Controlla le 4 coppie e la distanza di un guasto",
             "act": self.cable},
            {"title": "Rinnova DHCP", "subtitle": "Rilascia e richiede di nuovo l'indirizzo", "act": self.renew},
            {"title": "Risolvi un nome (DNS)", "subtitle": "Interroga i DNS ricevuti dal DHCP", "act": self.dns},
        ]
        self.widgets = [ListView(self.body, items, 51, on_select=lambda it: it["act"](), )]

    def ping(self):
        ipi = self.main.diag.ipi or {}
        self.mgr.push(Keyboard(self.mgr, "Indirizzo da pingare", lambda h: h.strip() and self.mgr.push(
            PingScreen(self.mgr, h.strip())), initial=ipi.get("gateway") or "", ok_label="Avvia"))

    def blink(self):
        self.mgr.confirm("Lampeggiare la porta?", "Il link viene spento e riacceso ogni 1,5 s per circa 30 s: "
                         "il LED della porta sullo switch lampeggia. La rete del tester si interrompe.",
                         "Avvia", lambda: self.mgr.push(BlinkScreen(self.mgr)))

    def cable(self):
        self.mgr.confirm("Testare il cavo?", "Il link cade per qualche secondo. Funziona meglio con il cavo "
                         "staccato dall'altra parte.", "Avvia", self._cable)

    def _cable(self):
        def done(r):
            if not r["ok"]:
                self.mgr.toast(r["error"], 4)
                return
            rows = []
            for p, v in sorted(r["pairs"].items()):
                val = v["code"] + (f" a {v['len']:.1f} m" if v["len"] is not None else "")
                rows.append((f"Coppia {p}", val))
            bad = [k for k, v in r["pairs"].items() if v["code"] != "OK"]
            hints = [f"Coppie con problemi: {', '.join(sorted(bad))}"] if bad else []
            self.mgr.push(Detail(self.mgr, "Test del cavo", rows, hints))
        self.mgr.run(nd.cable_test, done, "Test del cavo…")

    def renew(self):
        def done(res):
            ok, secs, err = res
            self.mgr.toast(f"Indirizzo ottenuto in {secs:.1f} s" if ok else f"DHCP non riuscito: {err}", 4)
            self.main.diag.rerun.set()
        self.mgr.run(nd.renew_dhcp, done, "Rinnovo DHCP…")

    def dns(self):
        self.mgr.push(Keyboard(self.mgr, "Nome da risolvere", self._dns, ok_label="Cerca"))

    def _dns(self, name):
        name = name.strip()
        servers = (self.main.diag.ipi or {}).get("dns") or []
        if not name:
            return
        if not servers:
            self.mgr.toast("Nessun server DNS: serve prima un indirizzo dal DHCP")
            return

        def job():
            rows = []
            for srv in servers[:3]:
                r = nd.dns_query(srv, name)
                rows.append((srv, f"{r['ms']:.0f} ms · {', '.join(r['ips'])}" if r["ok"] else r["error"]))
            return rows
        self.mgr.run(job, lambda rows: self.mgr.push(Detail(self.mgr, name, rows)), f"Risolvo {name}…")


class PingScreen(Screen):
    def __init__(self, mgr, host):
        super().__init__(mgr)
        self.title = f"Ping {host}"
        self.host = host
        self.rtts = []          # None = perso
        self.stop = threading.Event()
        self.error = ""

    def enter(self):
        self.build()
        threading.Thread(target=self._loop, daemon=True).start()

    def leave(self):
        if self not in self.mgr.stack:
            self.stop.set()

    def _loop(self):
        while not self.stop.is_set():
            t0 = time.time()
            p = nd.ping(self.host, 1, iface=nd.IFACE if nd.carrier() else None)
            if not p.get("sent"):
                self.error = p["error"]
            else:
                self.error = ""
                self.rtts.append(p["avg"] if p["recv"] else None)
                self.rtts = self.rtts[-300:]
            self.mgr.dirty = True
            self.stop.wait(max(0.0, 1 - (time.time() - t0)))

    def draw_content(self, s):
        b = self.body
        ok = [x for x in self.rtts if x is not None]
        sent, lost = len(self.rtts), len(self.rtts) - len(ok)
        last = self.rtts[-1] if self.rtts else None
        x = b.x + 16
        col = T["danger"] if (self.rtts and last is None) else T["text"]
        big = "—" if not self.rtts else ("perso" if last is None else f"{last:.1f} ms")
        text(s, big, (x, b.y + 10), 30, col, bold=True)
        stats = [("Inviati", str(sent)), ("Persi", f"{lost} ({lost * 100 // max(1, sent)}%)"),
                 ("Min", f"{min(ok):.1f}" if ok else "—"), ("Medio", f"{sum(ok) / len(ok):.1f}" if ok else "—"),
                 ("Max", f"{max(ok):.1f}" if ok else "—")]
        for i, (k, v) in enumerate(stats):
            cx = b.x + 16 + i * (b.w - 32) // 5
            text(s, k, (cx, b.y + 56), 11, T["muted"])
            text(s, v, (cx, b.y + 72), 14, bold=True)
        g = pygame.Rect(b.x + 16, b.y + 102, b.w - 32, b.h - 116)
        rrect(s, T["surface"], g, 8)
        data = self.rtts[-(g.w // 6):]
        top = max([v for v in data if v is not None] + [1.0]) * 1.2
        for i, v in enumerate(data):
            bx = g.x + 4 + i * 6
            if v is None:
                pygame.draw.rect(s, T["danger"], (bx, g.y + 4, 4, g.h - 8), border_radius=1)
            else:
                h = max(2, int((g.h - 8) * v / top))
                pygame.draw.rect(s, T["accent"], (bx, g.bottom - 4 - h, 4, h), border_radius=1)
        text(s, f"{top:.0f} ms", (g.right - 6, g.y + 4), 10, T["muted"], anchor="topright")
        if self.error:
            text(s, self.error, g.center, 13, T["warn"], anchor="center", maxw=g.w - 20)


class BlinkScreen(Screen):
    title = "Lampeggio porta"
    back = False

    def __init__(self, mgr):
        super().__init__(mgr)
        self.stop = threading.Event()
        self.step, self.total, self.finished, self.link_on = 0, 10, False, True

    def enter(self):
        self.build()

        def prog(i, n, on):
            self.step, self.total, self.link_on = i, n, on
            self.mgr.dirty = True

        def job():
            nd.blink_port(self.stop, cycles=self.total, period=3.0, progress=prog)
            self.finished = True
            self.mgr.dirty = True

        threading.Thread(target=job, daemon=True).start()

    def build(self):
        b = self.body
        self.widgets = [Button((40, b.bottom - 64, b.w - 80, 48), "Ferma", self.end, "danger")]

    def end(self):
        self.stop.set()
        self.mgr.pop()

    def leave(self):
        self.stop.set()

    def update(self, now):
        if self.finished and self.mgr.top is self:
            self.mgr.pop()
            self.mgr.toast("Lampeggio finito, il link è di nuovo attivo")

    def draw_content(self, s):
        b = self.body
        on = self.link_on
        text(s, "Guarda i LED dello switch:", (b.centerx, b.y + 30), 15, anchor="center")
        text(s, "la porta collegata al tester si spegne e si riaccende.", (b.centerx, b.y + 52), 13, T["muted"],
             anchor="center")
        pygame.draw.circle(s, T["ok"] if on else T["surface2"], (b.centerx, b.y + 108), 22)
        text(s, "link acceso" if on else "link spento", (b.centerx, b.y + 108), 11, T["bg"] if on else T["muted"],
             anchor="center")
        text(s, f"Ciclo {self.step} di {self.total}", (b.centerx, b.y + 150), 14, T["muted"], anchor="center")


APP = {"name": "Tester rete", "icon": icon_net, "color": (36, 140, 110), "order": 5, "screen": NetTest}
