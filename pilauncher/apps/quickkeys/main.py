"""Tastiera Rapida.

1. Modalità Chiavetta: collegato al tuo PC con la USB-C, il gadget appare come una chiavetta; ci copi dei file .txt.
2. Stacchi il cavo (il gadget si spegne), lo colleghi al PC su cui scrivere e si riaccende.
3. Modalità Tastiera: il gadget appare come una tastiera; tocchi un file e lo digita. Poi lo puoi eliminare.

Le chiavi di ripristino BitLocker (48 cifre) vengono riconosciute e digitate come sole cifre: funzionano con
qualunque layout e anche nella schermata di BitLocker prima dell'avvio di Windows.
"""
import os
import threading
import time

import pygame

from core import fatdisk, hidkeys, usbgadget
from core.framework import Screen
from core.ui import T, Button, ListView, Toggle, rrect, text, wrap

IMAGE_MB = 64
ROW0, ROW = 86, 38     # posizione e passo delle opzioni nella schermata principale
MAX_FILE = 64 * 1024


def cfg(mgr):
    c = mgr.ctx.config.setdefault("quickkeys", {})
    c.setdefault("layout", "IT")
    c.setdefault("enter", False)
    c.setdefault("autodelete", False)
    return c


def image_path(mgr):
    return os.path.join(mgr.ctx.data_dir, "quickkeys.img")


def ensure_image(mgr):
    p = image_path(mgr)
    if not os.path.exists(p):
        fatdisk.format_fat16(p, IMAGE_MB, "TASTIERA")
    return p


def text_files(mgr):
    """File .txt della chiavetta, con contenuto e tipo."""
    p = ensure_image(mgr)
    out = []
    for e in fatdisk.list_files(p):
        if e["hidden"] or not e["name"].lower().endswith(".txt") or e["name"].startswith(("._", "~$")):
            continue
        body = fatdisk.decode_text(fatdisk.read_file(p, e, MAX_FILE))
        out.append({"entry": e, "name": e["name"], "text": body, "bitlocker": hidkeys.is_bitlocker(body)})
    return out


def mask(s, keep=6):
    s = " ".join(s.split())
    return s[:keep] + "•" * min(12, max(0, len(s) - keep)) if len(s) > keep else s


def icon_app(s, c, sz, col):
    cx, cy = c
    body = pygame.Rect(0, 0, sz * 0.8, sz * 0.5)
    body.center = (cx, cy)
    pygame.draw.rect(s, col, body, max(2, int(sz * 0.07)), border_radius=4)
    kw = body.w / 6
    for row in range(2):
        for i in range(5):
            r = pygame.Rect(0, 0, kw * 0.6, kw * 0.6)
            r.center = (body.x + kw * (i + 0.5) + kw * 0.5, body.y + body.h * (0.32 + row * 0.3))
            pygame.draw.rect(s, col, r)
    pygame.draw.line(s, col, (body.x + body.w * 0.3, body.y + body.h * 0.8), (body.x + body.w * 0.7,
                                                                                body.y + body.h * 0.8), 2)


class ModeButton(Button):
    """Pulsante grande con titolo e sottotitolo."""
    def __init__(self, rect, title, sub, cb, kind):
        super().__init__(rect, "", cb, kind)
        self.t, self.sub = title, sub

    def draw(self, s):
        super().draw(s)
        fg = T["text"] if self.enabled else T["muted"]
        text(s, self.t, (self.rect.centerx, self.rect.y + 26), 18, fg, bold=True, anchor="center")
        text(s, self.sub, (self.rect.centerx, self.rect.y + 50), 12, fg, anchor="center")


# ===================================================================== principale
class QuickKeys(Screen):
    title = "Tastiera Rapida"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.state = None

    def enter(self):
        self.build()
        self.mgr.run(usbgadget.status, self._got_state)

    def resume(self):
        self.build()

    def _got_state(self, st):
        self.state = st
        self.build()

    def build(self):
        b = self.body
        c = cfg(self.mgr)
        w = (b.w - 36) // 2
        ok = self.state == "ok"
        self.widgets = []
        if self.state == "overlay":
            self.widgets.append(Button((20, b.y + 150, b.w - 40, 44), "Abilita la USB-C (poi riavvia)",
                                       self.enable, "primary"))
            return
        if self.state == "reboot":
            self.widgets.append(Button((20, b.y + 150, b.w - 40, 44), "Riavvia ora", self.reboot, "primary"))
            return
        k1 = ModeButton((12, b.y + 6, w, 72), "Chiavetta", "Carica i file dal tuo PC",
                        lambda: self.mgr.push(StorageMode(self.mgr)), "normal")
        k2 = ModeButton((24 + w, b.y + 6, w, 72), "Tastiera", "Scrivi su questo PC",
                        lambda: self.mgr.push(KeyboardMode(self.mgr)), "primary")
        k1.enabled = k2.enabled = ok
        y = b.y + ROW0
        self.widgets += [k1, k2,
                         Button((b.right - 104, y + 2, 92, 30), f"Layout {c['layout']}", self.toggle_layout, size=13),
                         Toggle((b.right - 64, y + ROW + 4, 52, 28), c["enter"], lambda v: self.set("enter", v)),
                         Toggle((b.right - 64, y + 2 * ROW + 4, 52, 28), c["autodelete"],
                                lambda v: self.set("autodelete", v)),
                         Button((12, b.bottom - 38, 150, 32), "Spegni il gadget", self.poweroff, size=13)]

    def draw_content(self, s):
        b = self.body
        if self.state is None:
            text(s, "Controllo della porta USB-C…", b.center, 14, T["muted"], anchor="center")
            return
        if self.state in ("overlay", "reboot"):
            msg = ("La porta USB-C non è ancora in modalità dispositivo. Abilitandola si aggiunge una riga a "
                   "config.txt; poi serve un riavvio." if self.state == "overlay" else
                   "La modalità dispositivo è abilitata in config.txt ma non ancora attiva: riavvia il gadget.")
            for i, ln in enumerate(wrap(msg, 14, b.w - 40)):
                text(s, ln, (b.x + 20, b.y + 30 + i * 20), 14)
            text(s, "Le 4 porte USB-A non possono fare da tastiera: si usa solo la USB-C.", (b.x + 20, b.y + 124),
                 12, T["muted"])
            return
        y = b.y + ROW0
        for i, (lab, sub) in enumerate((("Layout della tastiera del PC", "Per lettere e simboli (le cifre vanno sempre)"),
                                        ("Premi Invio alla fine", "Dopo aver scritto il testo"),
                                        ("Elimina il file dopo averlo scritto", "Consigliato per le chiavi BitLocker"))):
            text(s, lab, (b.x + 14, y + 4 + i * ROW), 14)
            text(s, sub, (b.x + 14, y + 22 + i * ROW), 11, T["muted"])

    def toggle_layout(self):
        c = cfg(self.mgr)
        c["layout"] = "US" if c["layout"] == "IT" else "IT"
        self.mgr.ctx.save_config()
        self.build()

    def set(self, key, v):
        cfg(self.mgr)[key] = v
        self.mgr.ctx.save_config()

    def enable(self):
        def do():
            ok, err = usbgadget.enable_overlay()
            if not ok:
                self.mgr.toast(f"Non riuscito: {err}")
                return
            self.state = "reboot"
            self.build()
        self.mgr.confirm("Abilitare la USB-C?", "Aggiungo 'dtoverlay=dwc2,dr_mode=peripheral' in config.txt. "
                         "L'alimentazione dalla USB-C continua a funzionare. Serve un riavvio.", "Abilita", do)

    def reboot(self):
        from apps.settings import do_power
        do_power(self.mgr, "reboot")

    def poweroff(self):
        from apps.settings import do_power

        def do():
            try:
                usbgadget.stop()
            except OSError:
                pass
            do_power(self.mgr, "poweroff")
        self.mgr.confirm("Spegnere il gadget?", "Poi puoi staccare il cavo in sicurezza.", "Spegni", do)


# =================================================================== chiavetta
class StorageMode(Screen):
    title = "Chiavetta"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.err, self.host, self.ready = "", "?", False

    def enter(self):
        self.build()

        def job():
            usbgadget.start("storage", ensure_image(self.mgr))

        def done(_):
            self.ready = True
        self.mgr.run(job, done, "Preparo la chiavetta…")

    def leave(self):
        if self not in self.mgr.stack:
            try:
                usbgadget.stop()
            except OSError:
                pass

    def update(self, now):
        if int(now) != getattr(self, "_t", None):
            self._t = int(now)
            h = usbgadget.host_state()
            if h != self.host:
                self.host = h
                self.mgr.dirty = True

    def build(self):
        b = self.body
        self.widgets = [Button((12, b.bottom - 50, b.w - 24, 42), "Fine", self.mgr.pop, "primary")]

    def draw_content(self, s):
        b = self.body
        card = pygame.Rect(b.x + 12, b.y + 8, b.w - 24, 44)
        rrect(s, T["surface"], card, 10)
        connected = self.host == "configured"
        msg = ("Collegata: sul PC apri la chiavetta TASTIERA" if connected else
               "In attesa del PC: collega il cavo USB-C" if self.ready else "Avvio…")
        pygame.draw.circle(s, T["ok"] if connected else T["warn"], (card.x + 22, card.centery), 8)
        text(s, msg, (card.x + 40, card.centery), 14, anchor="midleft", maxw=card.w - 50)
        steps = ["1. Copia nella chiavetta i file .txt da scrivere (una chiave BitLocker o un testo per file).",
                 "2. Su Windows usa \"Espelli\" prima di staccare.",
                 "3. Stacca il cavo, collega il gadget al PC su cui scrivere e apri la modalità Tastiera."]
        y = card.bottom + 10
        for st in steps:
            for ln in wrap(st, 13, b.w - 40):
                text(s, ln, (b.x + 20, y), 13)
                y += 17
            y += 3
        note = "I file restano solo sul gadget. Se la chiavetta non compare, il PC potrebbe bloccare le chiavette USB."
        for i, ln in enumerate(wrap(note, 11, b.w - 40)):
            text(s, ln, (b.x + 20, y + i * 14), 11, T["muted"])


# ==================================================================== tastiera
class KeyboardMode(Screen):
    title = "Tastiera"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.files, self.err, self.host, self.loaded = [], "", "?", False

    def enter(self):
        self.build()

        def job():
            usbgadget.start("keyboard")   # ferma la chiavetta: da qui l'immagine si può leggere
            return text_files(self.mgr)

        def done(files):
            self.files, self.loaded = files, True
            self.build()
        self.mgr.run(job, done, "Avvio la tastiera…")

    def resume(self):
        try:
            self.files = text_files(self.mgr)
        except (OSError, ValueError) as e:
            self.err = str(e)
        self.build()

    def leave(self):
        if self not in self.mgr.stack:
            try:
                usbgadget.stop()
            except OSError:
                pass

    def update(self, now):
        if int(now) != getattr(self, "_t", None):
            self._t = int(now)
            h = usbgadget.host_state()
            if h != self.host:
                self.host = h
                self.mgr.dirty = True

    def build(self):
        b = self.body
        items = []
        for f in self.files:
            kind = "Chiave BitLocker · 48 cifre" if f["bitlocker"] else f"Testo · {len(f['text'])} caratteri"
            items.append({"title": f["name"][:-4], "sub": f"{kind} · {mask(f['text'])}", "f": f})
        empty = "Nessun file .txt: caricali in modalità Chiavetta" if self.loaded else ""
        self.widgets = [ListView((b.x, b.y + 36, b.w, b.h - 36), items, 48, render=_file_row, empty_text=empty,
                                 on_select=lambda it: self.mgr.push(TypeScreen(self.mgr, it["f"], self)))]

    def draw_content(self, s):
        b = self.body
        connected = self.host == "configured"
        pygame.draw.circle(s, T["ok"] if connected else T["warn"], (b.x + 20, b.y + 18), 7)
        text(s, "Il PC vede la tastiera" if connected else "Collega il cavo USB-C al PC su cui scrivere",
             (b.x + 34, b.y + 18), 13, anchor="midleft")


def _file_row(s, r, it):
    text(s, it["title"], (r.x + 14, r.centery - 9), 15, anchor="midleft", maxw=r.w - 40)
    text(s, it["sub"], (r.x + 14, r.centery + 10), 12, T["muted"], anchor="midleft", maxw=r.w - 40)
    pygame.draw.lines(s, T["muted"], False, [(r.right - 18, r.centery - 5), (r.right - 13, r.centery),
                                             (r.right - 18, r.centery + 5)], 2)


class TypeScreen(Screen):
    def __init__(self, mgr, f, parent):
        super().__init__(mgr)
        self.f, self.parent = f, parent
        self.title = f["name"][:-4]
        c = cfg(mgr)
        self.seq, self.bad = hidkeys.prepare(f["text"], c["layout"], c["enter"])
        self.show, self.typing, self.prog = False, False, (0, 0)
        self.stop = threading.Event()

    def build(self):
        b = self.body
        w = (b.w - 36) // 2
        if self.typing:
            self.widgets = [Button((12, b.bottom - 54, b.w - 24, 46), "Interrompi", self.stop.set, "danger")]
            return
        self.widgets = [
            Button((b.right - 96, b.y + 6, 84, 28), "Nascondi" if self.show else "Mostra", self.toggle, size=12),
            Button((12, b.bottom - 54, w, 46), "Elimina", self.delete, "danger"),
            Button((24 + w, b.bottom - 54, w, 46), "Scrivi", self.write, "primary"),
        ]

    def toggle(self):
        self.show = not self.show
        self.build()

    def draw_content(self, s):
        b = self.body
        c = cfg(self.mgr)
        kind = ("Chiave di ripristino BitLocker: scrivo solo le 48 cifre" if self.f["bitlocker"] else
                f"Testo · layout {c['layout']}" + (" · Invio alla fine" if c["enter"] else ""))
        text(s, kind, (b.x + 14, b.y + 20), 13, T["accent2"], anchor="midleft", maxw=b.w - 120)
        box = pygame.Rect(b.x + 12, b.y + 40, b.w - 24, b.h - 106)
        rrect(s, T["surface"], box, 8)
        body = self.f["text"] if self.show else mask(self.f["text"], 6)
        y = box.y + 8
        for ln in body.replace("\r", "").split("\n"):
            for part in wrap(ln, 14, box.w - 20) or [""]:
                if y > box.bottom - 18:
                    break
                text(s, part, (box.x + 10, y), 14)
                y += 19
        if self.typing:
            i, n = self.prog
            text(s, f"Sto scrivendo… {i}/{n} tasti", (b.centerx, box.bottom - 16), 13, T["accent2"], anchor="center")
        elif self.bad:
            text(s, "Non digitabili (saltati): " + " ".join(self.bad[:10]), (box.x + 10, box.bottom - 16), 12,
                 T["warn"], anchor="midleft", maxw=box.w - 20)

    def write(self):
        if usbgadget.host_state() != "configured":
            self.mgr.toast("Il PC non vede ancora la tastiera: controlla il cavo USB-C")
            return
        self.typing, self.prog = True, (0, len(self.seq))
        self.stop.clear()
        self.build()

        def prog(i, n):
            self.prog = (i, n)
            self.mgr.dirty = True

        def job():
            time.sleep(0.5)
            try:
                hidkeys.type_sequence(self.seq, progress=prog, stop=self.stop)
            except (OSError, RuntimeError) as e:
                return str(e)
            return "interrotta" if self.stop.is_set() else ""

        def done(err):
            self.typing = False
            self.build()
            if err:
                self.mgr.toast("Scrittura " + err if err == "interrotta" else f"Scrittura non riuscita: {err}", 4)
                return
            if cfg(self.mgr)["autodelete"]:
                self._delete()
                self.mgr.toast("Scritto ed eliminato")
            else:
                self.mgr.toast("Scritto")
        self.mgr.run(job, done)

    def delete(self):
        self.mgr.confirm("Eliminare il file?", f"{self.f['name']} verrà cancellato dal gadget.", "Elimina",
                         self._delete, True)

    def _delete(self):
        try:
            fatdisk.delete_file(image_path(self.mgr), self.f["entry"])
        except (OSError, ValueError) as e:
            self.mgr.toast(f"Non riuscito: {e}")
            return
        if self.mgr.top is self:
            self.mgr.pop()
        self.mgr.toast("File eliminato")


APP = {"name": "Tastiera Rapida", "icon": icon_app, "color": (150, 90, 200), "order": 7, "screen": QuickKeys}
