"""Schermate del Tester Wi-Fi."""
import threading
import time

import pygame

from core import netdiag as nd
from core import wifidiag as wd
from core.framework import Screen
from core.ui import T, Button, ListView, icon_wifi, rrect, signal_bars, text

from apps.nettest.common import Detail, status_icon
from apps.nettest.report import ReportView, save

IFACE = wd.IFACE


def sig_color(dbm):
    lvl = wd.quality(dbm)[1]
    return T["ok"] if lvl >= 3 else T["warn"] if lvl == 2 else T["danger"]


def ap_name(ap):
    v = nd.vendor(ap["bssid"])
    return ap["bssid"] + (f" · {v[:18]}" if v else "")


def ap_line(ap):
    parts = [f"Canale {ap['channel']} ({wd.band_of(ap['freq'])}, {ap['width']} MHz)"]
    if ap["std"]:
        parts.append(ap["std"])
    if ap["stations"] is not None:
        parts.append(f"{ap['stations']} client")
    if ap["util"] is not None:
        parts.append(f"canale al {ap['util']}%")
    roam = "".join(x for x, on in (("k", ap["k"]), ("v", ap["v"]), ("r", ap["r"])) if on)
    if roam:
        parts.append("802.11" + "/".join(roam))
    return " · ".join(parts)


# ================================================================= principale
class WifiTest(Screen):
    title = "Tester Wi-Fi"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.aps, self.link, self.hints, self.src, self.err = [], None, [], "", ""
        self.scanned_at = 0
        self.monitor_log = None   # eventi dell'ultimo monitoraggio, per il report

    def enter(self):
        self.build()
        self.scan()

    def resume(self):
        self.build()

    def scan(self):
        def job():
            aps, src, err = wd.scan()
            link = wd.link_info()
            return aps, src, err, link

        def done(res):
            self.aps, self.src, self.err, self.link = res
            self.hints = wd.analyze(self.aps, self.link)
            self.scanned_at = time.time()
            self.build()
        self.mgr.run(job, done, "Scansione Wi-Fi…")

    def build(self):
        a, b = self.area, self.body
        nets = wd.group_by_ssid(self.aps)
        items = [
            {"title": "Reti visibili", "sub": f"{len(nets)} reti · {len(self.aps)} AP" if self.scanned_at else "…",
             "go": lambda: self.mgr.push(Networks(self.mgr, self))},
            {"title": "Occupazione dei canali", "sub": "AP per canale a 2,4 e 5 GHz",
             "go": lambda: self.mgr.push(Channels(self.mgr, self.aps))},
            {"title": "Test della connessione", "sub": "IP, gateway, DNS e Internet sul Wi-Fi",
             "go": lambda: self.mgr.push(ConnTest(self.mgr))},
            {"title": "Monitor segnale e roaming", "sub": "Segnale nel tempo e cambi di AP mentre ti sposti",
             "go": lambda: self.mgr.push(Monitor(self.mgr, self))},
            {"title": f"Avvisi ({len(self.hints)})" if self.hints else "Nessun avviso",
             "sub": self.hints[0] if self.hints else "Situazione Wi-Fi senza problemi evidenti",
             "go": (lambda: self.mgr.push(Detail(self.mgr, "Avvisi Wi-Fi", [], self.hints))) if self.hints else None,
             "warn": bool(self.hints)},
        ]
        self.widgets = [
            ListView((b.x, b.y + 74, b.w, b.h - 74), items, 46, render=_menu_row,
                     on_select=lambda it: it["go"] and it["go"]()),
            Button((a.right - 172, a.y + 6, 80, 28), "Report", self.report, size=13),
            Button((a.right - 86, a.y + 6, 78, 28), "Aggiorna", self.scan, size=13),
        ]

    def draw_content(self, s):
        b = self.body
        card = pygame.Rect(b.x + 8, b.y + 6, b.w - 16, 64)
        rrect(s, T["surface"], card, 10)
        lk = self.link
        if not lk:
            text(s, "Lettura del collegamento…", (card.x + 14, card.centery), 14, T["muted"], anchor="midleft")
            return
        if not lk["connected"]:
            text(s, "Non collegato a nessuna rete Wi-Fi", (card.x + 14, card.y + 20), 15, anchor="midleft")
            text(s, "Collegati da Impostazioni → Wi-Fi per testare la connessione", (card.x + 14, card.y + 44), 12,
                 T["muted"], anchor="midleft")
            return
        q, lvl = wd.quality(lk["signal"])
        icon_wifi(s, (card.x + 28, card.centery + 2), 30, sig_color(lk["signal"]), level=max(1, lvl), dim=T["line"])
        x = card.x + 54
        text(s, lk["ssid"] or "(nascosta)", (x, card.y + 16), 16, bold=True, anchor="midleft", maxw=card.w - 170)
        v = nd.vendor(lk["bssid"])
        text(s, f"AP {lk['bssid']}" + (f" · {v[:16]}" if v else ""), (x, card.y + 36), 12, T["muted"],
             anchor="midleft", maxw=card.w - 170)
        text(s, f"Canale {lk['channel']} · {wd.band_of(lk['freq'])} · {wd.short_rate(lk['rx_rate'])}",
             (x, card.y + 52), 12, T["muted"], anchor="midleft", maxw=card.w - 70)
        if lk["signal"] is not None:
            text(s, f"{lk['signal']:.0f} dBm", (card.right - 12, card.y + 20), 18, sig_color(lk["signal"]), bold=True,
                 anchor="midright")
            text(s, q, (card.right - 12, card.y + 40), 12, sig_color(lk["signal"]), anchor="midright")

    def report(self):
        if not self.scanned_at:
            self.mgr.toast("Fai prima una scansione")
            return
        content, short = build_report(self)
        from core.keyboard import Keyboard

        def done(label):
            name = save(self.mgr, content.replace("Presa/luogo: -", f"Luogo: {label.strip() or '-'}"),
                        "wifi-" + (label.strip() or "senza-nome"))
            self.mgr.toast("Report salvato")
            self.mgr.push(ReportView(self.mgr, name, None, short.replace("Luogo: -", f"Luogo: {label.strip()}")))
        self.mgr.push(Keyboard(self.mgr, "Luogo (es. magazzino, sala riunioni)", done, ok_label="Salva"))


def _menu_row(s, r, it):
    col = T["warn"] if it.get("warn") else T["muted"]
    text(s, it["title"], (r.x + 14, r.centery - 9), 15, anchor="midleft", maxw=r.w - 50)
    text(s, it["sub"], (r.x + 14, r.centery + 10), 12, col, anchor="midleft", maxw=r.w - 50)
    if it.get("go"):
        pygame.draw.lines(s, T["muted"], False, [(r.right - 18, r.centery - 5), (r.right - 13, r.centery),
                                                 (r.right - 18, r.centery + 5)], 2)


# ===================================================================== reti
class Networks(Screen):
    title = "Reti visibili"

    def __init__(self, mgr, main):
        super().__init__(mgr)
        self.main = main

    def build(self):
        items = []
        for n in wd.group_by_ssid(self.main.aps):
            items.append({"title": (n["ssid"] or "(rete nascosta)") + ("  ● collegato" if n["associated"] else ""),
                          "sub": f"{len(n['aps'])} AP · {', '.join(n['bands'])} · {n['security']}", "net": n,
                          "dbm": n["best"]})
        src = f"Fonte: {self.main.src}" if self.main.src != "iw" else ""
        self.widgets = [ListView(self.body, items, 46, render=_sig_row, empty_text=self.main.err or "Nessuna rete",
                                 on_select=lambda it: self.mgr.push(Aps(self.mgr, it["net"], self.main.link)))]
        self.note = src

    def draw_content(self, s):
        if self.note:
            text(s, self.note, (self.area.right - 12, self.area.y + 20), 11, T["muted"], anchor="midright")


def _sig_row(s, r, it):
    dbm = it.get("dbm")
    right = r.right - 12
    if dbm is not None:
        signal_bars(s, pygame.Rect(right - 24, r.centery - 9, 24, 16), wd.quality(dbm)[1], sig_color(dbm))
        tr = text(s, f"{dbm:.0f} dBm", (right - 30, r.centery), 13, sig_color(dbm), anchor="midright")
        right = tr.x - 8
    text(s, it["title"], (r.x + 14, r.centery - 9), 15, anchor="midleft", maxw=right - r.x - 20)
    text(s, it["sub"], (r.x + 14, r.centery + 10), 12, T["muted"], anchor="midleft", maxw=r.w - 28)


class Aps(Screen):
    def __init__(self, mgr, net, link):
        super().__init__(mgr)
        self.net, self.link = net, link
        self.title = net["ssid"] or "(rete nascosta)"

    def build(self):
        cur = (self.link or {}).get("bssid")
        items = [{"title": ap_name(ap) + ("  ● collegato" if ap["bssid"] == cur else ""), "sub": ap_line(ap),
                  "dbm": ap["signal"], "ap": ap} for ap in self.net["aps"]]
        self.widgets = [ListView(self.body, items, 46, render=_sig_row,
                                 on_select=lambda it: self.mgr.push(Detail(self.mgr, it["ap"]["bssid"],
                                                                           ap_rows(it["ap"]))))]


def ap_rows(ap):
    rows = [("Rete", ap["ssid"] or "(nascosta)"), ("BSSID (MAC dell'AP)", ap["bssid"])]
    v = nd.vendor(ap["bssid"])
    if v:
        rows.append(("Produttore", v))
    rows += [("Segnale", f"{ap['signal']:.0f} dBm ({wd.quality(ap['signal'])[0]})" if ap["signal"] is not None else "?"),
             ("Canale", f"{ap['channel']} · {wd.band_of(ap['freq'])} · {ap['freq']:.0f} MHz"),
             ("Larghezza", f"{ap['width']} MHz"), ("Standard", "802.11" + ap["std"] if ap["std"] else "—"),
             ("Sicurezza", ap["security"])]
    if ap["stations"] is not None:
        rows.append(("Client collegati", str(ap["stations"])))
    if ap["util"] is not None:
        rows.append(("Occupazione del canale", f"{ap['util']}%"))
    rows.append(("Roaming 802.11k / v / r", " / ".join("sì" if ap[x] else "no" for x in "kvr")))
    return rows


# =================================================================== canali
class Channels(Screen):
    title = "Occupazione dei canali"

    def __init__(self, mgr, aps):
        super().__init__(mgr)
        self.aps = aps
        self.band = "2,4 GHz"

    def build(self):
        a = self.area
        other = "5 GHz" if self.band == "2,4 GHz" else "2,4 GHz"
        self.widgets = [Button((a.right - 104, a.y + 6, 96, 28), other, self.switch, size=13)]

    def switch(self):
        self.band = "5 GHz" if self.band == "2,4 GHz" else "2,4 GHz"
        self.build()

    def draw_content(self, s):
        b = self.body
        use = wd.channel_usage(self.aps).get(self.band, {})
        chans = list(range(1, 14)) if self.band == "2,4 GHz" else sorted(use) or [36, 40, 44, 48]
        g = pygame.Rect(b.x + 30, b.y + 24, b.w - 46, b.h - 60)
        text(s, f"AP per canale · {self.band}", (b.x + 14, b.y + 10), 13, T["muted"], anchor="midleft")
        top = max([len(v) for v in use.values()] + [4])
        bw = g.w / len(chans)
        for i in range(0, top + 1, max(1, top // 4)):
            y = g.bottom - g.h * i / top
            pygame.draw.line(s, T["line"], (g.x, y), (g.right, y))
            text(s, str(i), (g.x - 6, y), 10, T["muted"], anchor="midright")
        for i, ch in enumerate(chans):
            lst = use.get(ch, [])
            x = g.x + i * bw
            if lst:
                best = max(a["signal"] or -100 for a in lst)
                h = g.h * len(lst) / top
                rrect(s, sig_color(best), (x + bw * 0.15, g.bottom - h, bw * 0.7, h), 3)
            col = T["accent2"] if self.band == "2,4 GHz" and ch in (1, 6, 11) else T["muted"]
            text(s, str(ch), (x + bw / 2, g.bottom + 10), 10 if bw < 20 else 11, col, anchor="center")
        text(s, "Colore = segnale più forte sul canale. A 2,4 GHz usare solo 1, 6, 11.", (b.x + 14, b.bottom - 10), 11,
             T["muted"], anchor="midleft")


# ======================================================= test connessione
class ConnTest(Screen):
    title = "Test della connessione Wi-Fi"
    STEPS = [("ip", "Indirizzo IP"), ("gw", "Gateway"), ("dns", "DNS"), ("inet", "Internet")]

    def __init__(self, mgr):
        super().__init__(mgr)
        self.res = {k: ("wait", "", []) for k, _ in self.STEPS}

    def enter(self):
        self.build()
        threading.Thread(target=self._run, daemon=True).start()

    def _set(self, k, st, summary, rows=()):
        self.res[k] = (st, summary, list(rows))
        self.mgr.dirty = True
        self.build()

    def _run(self):
        self._set("ip", "run", "Lettura…")
        ipi = nd.ip_info(IFACE)
        if not ipi["addr"]:
            self._set("ip", "fail", "Nessun indirizzo IP sul Wi-Fi")
            for k in ("gw", "dns", "inet"):
                self._set(k, "off", "")
            return
        self._set("ip", "ok", f"{ipi['addr']}/{ipi['prefix']}",
                  [("Gateway", ipi["gateway"] or "—"), ("DNS", ", ".join(ipi["dns"]) or "—"),
                   ("Server DHCP", ipi["dhcp_server"] or "—"), ("Dominio", ipi["domain"] or "—")])
        gw = ipi["gateway"]
        if gw:
            self._set("gw", "run", f"Ping a {gw}…")
            p = nd.ping(gw, 10, iface=IFACE)
            if p.get("recv"):
                st = "ok" if p["loss"] == 0 and p["avg"] < 30 else "warn"
                self._set("gw", st, f"{p['avg']:.1f} ms · {p['loss']}% persi",
                          [("Min / medio / max", f"{p['min']:.1f} / {p['avg']:.1f} / {p['max']:.1f} ms")])
            else:
                self._set("gw", "warn", "Il gateway non risponde al ping")
        else:
            self._set("gw", "off", "Nessun gateway")
        if ipi["dns"]:
            r = nd.dns_query(ipi["dns"][0], "www.google.com", iface=IFACE)
            self._set("dns", "ok" if r["ok"] else "fail",
                      f"{r['ms']:.0f} ms" if r["ok"] else r["error"])
        else:
            self._set("dns", "off", "Nessun DNS")
        h = nd.http_check("https://www.google.com/generate_204", iface=IFACE)
        self._set("inet", "ok" if h["code"] in (200, 204) else "warn" if h["code"] else "fail",
                  f"Raggiungibile · {h['ms']:.0f} ms" if h["code"] in (200, 204) else
                  f"Risposta {h['code']} (proxy?)" if h["code"] else h["error"])

    def build(self):
        items = []
        for k, name in self.STEPS:
            st, summary, rows = self.res[k]
            items.append({"k": k, "name": name, "st": st, "sum": summary, "rows": rows})
        self.widgets = [ListView(self.body, items, 50, render=_step_row,
                                 on_select=lambda it: it["rows"] and self.mgr.push(
                                     Detail(self.mgr, it["name"], it["rows"])))]

    def update(self, now):
        if any(v[0] == "run" for v in self.res.values()) and int(now * 2) != getattr(self, "_t", 0):
            self._t = int(now * 2)
            self.mgr.dirty = True


def _step_row(s, r, it):
    status_icon(it["st"])(s, (r.x + 24, r.centery), 20)
    text(s, it["name"], (r.x + 46, r.centery - 9), 15, anchor="midleft")
    col = {"ok": T["ok"], "warn": T["warn"], "fail": T["danger"]}.get(it["st"], T["muted"])
    text(s, it["sum"] or ("In attesa" if it["st"] == "wait" else ""), (r.x + 46, r.centery + 10), 12, col,
         anchor="midleft", maxw=r.w - 70)


# ================================================================== monitor
class Monitor(Screen):
    """Segnale ogni secondo, ping al gateway, cambi di AP (roaming) mentre si cammina."""
    title = "Monitor segnale e roaming"

    def __init__(self, mgr, main):
        super().__init__(mgr)
        self.main = main
        self.samples = []      # (t, dbm, bssid, ping_ms|None|False)
        self.events = []       # (t, testo)
        self.stop = threading.Event()
        self.gw = None
        self.started = time.time()

    def enter(self):
        self.build()
        threading.Thread(target=self._loop, daemon=True).start()

    def leave(self):
        if self not in self.mgr.stack:
            self.stop.set()
            self.main.monitor_log = {"events": list(self.events), "samples": list(self.samples)}

    def _loop(self):
        self.gw = nd.ip_info(IFACE)["gateway"]
        last = None
        while not self.stop.is_set():
            t0 = time.time()
            lk = wd.link_info()
            png = None
            if self.gw and lk["connected"]:
                p = nd.ping(self.gw, 1, iface=IFACE)
                png = p["avg"] if p.get("recv") else False
            b = lk["bssid"] if lk["connected"] else None
            if last is not None and b != last[0]:
                if b is None:
                    self.events.append((t0, "Collegamento perso"))
                elif last[0] is None:
                    self.events.append((t0, f"Ricollegato a {b} (canale {lk['channel']})"))
                else:
                    self.events.append((t0, f"Roaming {last[0][-8:]} → {b[-8:]} (canale {lk['channel']}, "
                                            f"{lk['signal']:.0f} dBm)"))
            last = (b,)
            self.samples.append((t0, lk["signal"] if lk["connected"] else None, b, png))
            self.samples = self.samples[-600:]
            self.mgr.dirty = True
            self.stop.wait(max(0.1, 1 - (time.time() - t0)))

    def draw_content(self, s):
        b = self.body
        cur = self.samples[-1] if self.samples else None
        sigs = [x[1] for x in self.samples if x[1] is not None]
        pings = [x[3] for x in self.samples if x[3] is not None]
        lost = sum(1 for p in pings if p is False)
        x = b.x + 14
        if cur and cur[1] is not None:
            text(s, f"{cur[1]:.0f} dBm", (x, b.y + 8), 26, sig_color(cur[1]), bold=True)
            text(s, f"AP {cur[2]}", (x + 142, b.y + 6), 11, T["muted"])
        else:
            text(s, "Non collegato" if self.samples else "Avvio…", (x, b.y + 8), 22, T["danger"] if self.samples else
                 T["muted"], bold=True)
        stats = [("Min", f"{min(sigs):.0f}" if sigs else "—"), ("Medio", f"{sum(sigs) / len(sigs):.0f}" if sigs else "—"),
                 ("Ping persi", f"{lost}/{len(pings)}"), ("Roaming", str(sum(1 for e in self.events if "Roaming" in e[1])))]
        for i, (k, v) in enumerate(stats):
            cx = x + 142 + i * 76
            text(s, k, (cx, b.y + 28), 10, T["muted"])
            text(s, v, (cx, b.y + 41), 13, bold=True)
        g = pygame.Rect(b.x + 34, b.y + 64, b.w - 46, b.h - 120)
        rrect(s, T["surface"], g, 6)
        for dbm in (-40, -55, -67, -80):
            y = g.y + g.h * (-30 - dbm) / 60
            pygame.draw.line(s, T["line"], (g.x, y), (g.right, y))
            text(s, str(dbm), (g.x - 4, y), 10, T["muted"], anchor="midright")
        data = self.samples[-(g.w // 3):]
        prev_b = None
        for i, (_, dbm, bssid, png) in enumerate(data):
            px = g.x + 2 + i * 3
            if bssid != prev_b and i > 0:
                pygame.draw.line(s, T["accent2"], (px, g.y), (px, g.bottom), 1)
            prev_b = bssid
            if png is False:
                pygame.draw.rect(s, T["danger"], (px, g.bottom - 4, 2, 4))
            if dbm is None:
                continue
            h = max(2, min(g.h, g.h * (dbm + 90) / 60))
            pygame.draw.rect(s, sig_color(dbm), (px, g.bottom - h, 2, h))
        ev = self.events[-2:]
        y = g.bottom + 8
        for t, msg in ev:
            text(s, time.strftime("%H:%M:%S ", time.localtime(t)) + msg, (x, y), 11, T["accent2"], maxw=b.w - 28)
            y += 15
        if not ev:
            text(s, "Cammina tra gli AP: i cambi di AP compaiono qui e come linee blu nel grafico.", (x, y), 11,
                 T["muted"], maxw=b.w - 28)


# =================================================================== report
def build_report(main):
    when = time.strftime("%d/%m/%Y %H:%M")
    lk = main.link or {}
    out = ["REPORT TESTER WI-FI", f"Data: {when}", "Presa/luogo: -", ""]
    if lk.get("connected"):
        out += ["COLLEGAMENTO", f"   Rete: {lk['ssid']}", f"   AP: {lk['bssid']} {nd.vendor(lk['bssid'])}".rstrip(),
                f"   Canale: {lk['channel']} ({wd.band_of(lk['freq'])})",
                f"   Segnale: {lk['signal']:.0f} dBm ({wd.quality(lk['signal'])[0]})" if lk["signal"] is not None else
                "   Segnale: ?", f"   Velocità rx: {wd.short_rate(lk['rx_rate'])}",
                f"   Velocità tx: {wd.short_rate(lk['tx_rate'])}"]
        if lk.get("tx_retries") is not None:
            out.append(f"   Ritrasmissioni / fallite: {lk['tx_retries']} / {lk['tx_failed']}")
        out.append("")
    else:
        out += ["COLLEGAMENTO: non collegato", ""]
    if main.hints:
        out.append("AVVISI")
        out += [f"   ! {h}" for h in main.hints]
        out.append("")
    out.append("RETI VISIBILI")
    for n in wd.group_by_ssid(main.aps):
        out.append(f"   {n['ssid'] or '(nascosta)'} · {len(n['aps'])} AP · {n['security']}")
        for ap in n["aps"]:
            sig = f"{ap['signal']:.0f} dBm" if ap["signal"] is not None else "?"
            out.append(f"      {ap['bssid']} {sig} · {ap_line(ap)}")
    log = main.monitor_log
    if log and log["samples"]:
        sigs = [x[1] for x in log["samples"] if x[1] is not None]
        pings = [x[3] for x in log["samples"] if x[3] is not None]
        out += ["", "MONITORAGGIO",
                f"   Durata: {len(log['samples'])} s · segnale min/medio "
                f"{min(sigs):.0f}/{sum(sigs) / len(sigs):.0f} dBm" if sigs else "   Nessun campione con segnale",
                f"   Ping al gateway persi: {sum(1 for p in pings if p is False)}/{len(pings)}"]
        out += ["   " + time.strftime("%H:%M:%S ", time.localtime(t)) + m for t, m in log["events"]]
    content = "\n".join(out) + "\n"
    short = [f"Tester Wi-Fi {when}", "Luogo: -"]
    if lk.get("connected"):
        short.append(f"{lk['ssid']} · AP {lk['bssid']} · can. {lk['channel']} · "
                     + (f"{lk['signal']:.0f} dBm" if lk["signal"] is not None else "?"))
    short += [f"! {h}" for h in main.hints[:4]]
    for n in wd.group_by_ssid(main.aps)[:8]:
        short.append(f"{n['ssid'] or '(nascosta)'}: {len(n['aps'])} AP, migliore "
                     + (f"{n['best']:.0f} dBm" if n["best"] is not None else "?"))
    return content, "\n".join(short)


def icon_app(s, c, sz, col):
    icon_wifi(s, (c[0], c[1] + sz * 0.08), sz * 0.9, col, level=4, dim=col)


APP = {"name": "Tester Wi-Fi", "icon": icon_app, "color": (60, 110, 200), "order": 6, "screen": WifiTest}

