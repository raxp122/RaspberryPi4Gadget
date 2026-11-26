"""Report del Tester rete: testo per i ticket, salvataggio sul Pi, QR code e pagina web."""
import os
import re
import time

import pygame

from core import qr, webshare
from core import system as sysm
from core.framework import Screen
from core.keyboard import Keyboard
from core.ui import T, Button, ListView, text, wrap

from .common import NAMES, ORDER

MAX_REPORTS = 200
QR_PAGE = 700   # caratteri per pagina di QR: abbastanza piccolo da leggerlo dallo schermo da 3,5"
MARK = {"ok": "OK", "warn": "ATTENZIONE", "fail": "ERRORE", "off": "-", "wait": "-", "run": "in corso"}


def folder(mgr):
    return os.path.join(mgr.ctx.data_dir, "reports")


def _version(mgr):
    up = mgr.ctx.updater
    return up.version if up else "?"


def build(mgr, diag, label):
    """Report completo, in testo semplice."""
    when = time.strftime("%d/%m/%Y %H:%M")
    li = diag.li or {}
    out = ["REPORT TESTER RETE", f"Data: {when}", f"Presa: {label or '-'}",
           f"Tester: {sysm.hostname()} · PiLauncher {_version(mgr)} · MAC {li.get('mac') or '?'}", ""]
    for k in ORDER:
        c = diag.get(k)
        out.append(f"[{MARK.get(c['st'], c['st'])}] {NAMES[k]}: {c['sum'] or '-'}")
        for h in c["hints"]:
            out.append(f"   ! {h}")
        for key, val in c["rows"]:
            out.append(f"   {key}: {val}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def summary(mgr, diag, label):
    """Versione corta per il QR: una riga per controllo più i dati chiave."""
    when = time.strftime("%d/%m/%Y %H:%M")
    out = [f"Tester rete {when}", f"Presa: {label or '-'}"]
    for k in ORDER:
        c = diag.get(k)
        out.append(f"[{MARK.get(c['st'], c['st'])}] {NAMES[k]}: {c['sum'] or '-'}")
        keep = {"switch": ("Switch", "Porta", "Descrizione porta", "VLAN dati", "VLAN voce", "IP di gestione"),
                "ip": ("Gateway", "DNS", "Server DHCP", "IP duplicato", "Server DHCP che rispondono"),
                "link": ("Errori CRC",)}.get(k, ())
        for key, val in c["rows"]:
            if key in keep and val not in ("0", "No", "—"):
                out.append(f" {key}: {val}")
        for h in c["hints"][:2]:
            out.append(f" ! {h}")
    return "\n".join(out)


def save(mgr, content, label):
    d = folder(mgr)
    os.makedirs(d, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label or "").strip("-")[:40]
    name = time.strftime("%Y%m%d-%H%M%S") + (f"-{slug}" if slug else "") + ".txt"
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(content)
    files = list_reports(mgr)
    for old in files[MAX_REPORTS:]:
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    return name


def list_reports(mgr):
    d = folder(mgr)
    if not os.path.isdir(d):
        return []
    return sorted((f for f in os.listdir(d) if f.endswith(".txt")), reverse=True)


def read(mgr, name):
    with open(os.path.join(folder(mgr), name), encoding="utf-8") as f:
        return f.read()


def pages(txt, size=QR_PAGE):
    """Divide il testo in pagine per il QR, senza spezzare le righe."""
    out, cur = [], ""
    for line in txt.split("\n"):
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        if len(cur) + len(line) + 1 > size and cur:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    if len(out) > 1:
        out = [f"[{i}/{len(out)}]\n{p}" for i, p in enumerate(out, 1)]
    return out


def default_label(diag):
    nb = diag.listener.neighbor or {}
    parts = [nb.get("port_desc"), nb.get("port")]
    return " ".join(p for p in parts if p)[:40]


def ask_and_save(mgr, diag):
    """Chiede il nome della presa, salva e apre il report."""
    def done(label):
        content = build(mgr, diag, label.strip())
        short = summary(mgr, diag, label.strip())
        name = save(mgr, content, label.strip())
        mgr.toast("Report salvato")
        mgr.push(ReportView(mgr, name, content, short))
    mgr.push(Keyboard(mgr, "Nome presa / ufficio (facoltativo)", done, initial=default_label(diag),
                      ok_label="Salva"))


class ReportView(Screen):
    def __init__(self, mgr, name, content=None, short=None):
        super().__init__(mgr)
        self.name = name
        self.content = content if content is not None else read(mgr, name)
        self.short = short
        label = name[16:-4].replace("-", " ")
        self.title = label or f"Report {name[6:8]}/{name[4:6]} {name[9:11]}:{name[11:13]}"

    def build(self):
        b = self.body
        lines = []
        for ln in self.content.split("\n"):
            lines += wrap(ln, 12, b.w - 30) or [""]
        items = [{"t": ln, "static": True} for ln in lines]
        bw = (b.w - 36) // 2
        self.widgets = [
            ListView((b.x, b.y, b.w, b.h - 54), items, 17, render=_text_row),
            Button((12, b.bottom - 48, bw, 40), "Elimina", self.delete, "danger"),
            Button((24 + bw, b.bottom - 48, bw, 40), "QR code", self.qr, "primary"),
        ]

    def qr(self):
        self.mgr.push(QrScreen(self.mgr, pages(self.short or self.content)))

    def delete(self):
        def do():
            try:
                os.remove(os.path.join(folder(self.mgr), self.name))
            except OSError:
                pass
            self.mgr.pop()
            self.mgr.toast("Report eliminato")
        self.mgr.confirm("Eliminare il report?", self.name, "Elimina", do, True)


def _text_row(s, r, it):
    col = T["warn"] if it["t"].lstrip().startswith("!") else T["text"] if it["t"].startswith("[") else T["muted"]
    text(s, it["t"], (r.x + 12, r.centery), 12, col, anchor="midleft")


class QrScreen(Screen):
    """QR a tutto schermo; tocco = pagina successiva, ultima pagina = chiudi."""
    title = None
    fullscreen = True

    def __init__(self, mgr, pages_):
        super().__init__(mgr)
        self.pages = pages_ or [""]
        self.i = 0
        self.cache = {}

    def draw(self, s):
        s.fill((255, 255, 255))
        a = self.area
        if self.i not in self.cache:
            self.cache[self.i] = qr.encode(self.pages[self.i])
        side = pygame.Rect(0, 0, a.h, a.h)
        side.midleft = (a.x, a.centery)
        used = qr.draw(s, self.cache[self.i], side)
        x = used.right + 8
        w = a.right - x - 6
        info = [(f"Pagina {self.i + 1} di {len(self.pages)}" if len(self.pages) > 1 else "Report", True),
                ("Inquadra con il telefono e incolla il testo nel ticket.", False), ("", False),
                ("Tocca per " + ("la pagina dopo" if self.i + 1 < len(self.pages) else "chiudere"), False)]
        y = a.y + 40
        for ln, bold in info:
            for part in wrap(ln, 13, w, bold) or [""]:
                text(s, part, (x, y), 13, (20, 20, 20), bold=bold)
                y += 19

    def dispatch(self, kind, pos):
        if kind == "tap":
            if self.i + 1 < len(self.pages):
                self.i += 1
            else:
                self.mgr.pop()

    def on_key(self, kind, val):
        if val in ("esc",):
            self.mgr.pop()
        elif val in ("enter", "right", "down"):
            self.dispatch("tap", (0, 0))


class ReportsList(Screen):
    title = "Report salvati"

    def enter(self):
        self.build()

    def resume(self):
        self.build()

    def build(self):
        a, b = self.area, self.body
        web = webshare.get(folder(self.mgr))
        items = []
        if web.active:
            ips = [ip for ip in sysm.ip_addresses()]
            urls = ", ".join(f"http://{ip}:{webshare.PORT}" for ip in ips) or f"http://{sysm.hostname()}.local:8080"
            mins = max(0, int((web.until - time.time()) / 60))
            items.append({"t": f"Pagina web attiva per {mins} min: {urls}", "static": True, "web": True})
        for f in list_reports(self.mgr):
            d = f[:15]
            label = f[16:-4].replace("-", " ") or "senza nome"
            when = f"{d[6:8]}/{d[4:6]}/{d[:4]} {d[9:11]}:{d[11:13]}"
            items.append({"t": label, "sub": when, "f": f})
        self.widgets = [
            ListView(b, items, 44, render=_report_row, empty_text="Nessun report salvato",
                     on_select=lambda it: self.mgr.push(ReportView(self.mgr, it["f"]))),
            Button((a.right - 150, a.y + 6, 142, 28), "Spegni web" if web.active else "Condividi via web",
                   self.toggle_web, size=12),
        ]

    def toggle_web(self):
        web = webshare.get(folder(self.mgr))
        if web.active:
            web.stop()
        else:
            try:
                web.start()
            except OSError as e:
                self.mgr.toast(f"Impossibile avviare la pagina web: {e}")
        self.build()


def _report_row(s, r, it):
    if it.get("web"):
        for i, ln in enumerate(wrap(it["t"], 12, r.w - 28)[:2]):
            text(s, ln, (r.x + 14, r.centery - 8 + i * 16), 12, T["accent2"], anchor="midleft")
        return
    text(s, it["t"], (r.x + 14, r.centery - 9), 14, anchor="midleft", maxw=r.w - 28)
    text(s, it["sub"], (r.x + 14, r.centery + 10), 12, T["muted"], anchor="midleft")

