"""Server aziendali da controllare: inseriti a mano e salvati solo sul Pi (data/config.json), mai su GitHub."""
from core import netdiag as nd
from core.framework import Screen
from core.keyboard import Keyboard
from core.ui import T, Button, ListView, text, wrap

from .common import net_cfg, targets


def parse_ports(v):
    ports = []
    for p in v.replace(",", " ").split():
        if not p.isdigit() or not 0 < int(p) < 65536:
            return None
        ports.append(int(p))
    return ports


class TargetsScreen(Screen):
    title = "Server aziendali"

    def __init__(self, mgr, main=None):
        super().__init__(mgr)
        self.main = main

    def build(self):
        tg = targets(net_cfg(self.mgr))
        items = [{"title": t.get("name") or t["host"],
                  "subtitle": t["host"] + (" · porte " + ", ".join(map(str, t["ports"])) if t.get("ports") else
                                           " · solo ping"), "i": i} for i, t in enumerate(tg)]
        items.append({"title": "+ Aggiungi server", "subtitle": "Nome o IP, e le porte da provare", "i": None})
        self.widgets = [ListView(self.body, items, 46, on_select=lambda it: self.mgr.push(
            TargetEdit(self.mgr, it["i"], self.main)))]

    def draw_content(self, s):
        b = self.body
        if not targets(net_cfg(self.mgr)):
            text(s, "La lista resta solo su questo dispositivo.", (b.centerx, b.bottom - 40), 12, T["muted"],
                 anchor="center")
            text(s, "Va bene anche una tastiera USB.", (b.centerx, b.bottom - 22), 12, T["muted"], anchor="center")


EXAMPLES = "Es. 445 (file), 88 e 389 (dominio), 3389 (desktop remoto), 443 (web), 9100 (stampanti)"


class TargetEdit(Screen):
    def __init__(self, mgr, idx, main=None):
        super().__init__(mgr)
        self.idx, self.main = idx, main
        tg = targets(net_cfg(mgr))
        self.t = dict(tg[idx]) if idx is not None else {"name": "", "host": "", "ports": []}
        self.title = "Modifica server" if idx is not None else "Nuovo server"

    def build(self):
        t, b = self.t, self.body
        items = [
            {"title": "Nome", "value": t["name"] or "es. File server", "f": "name"},
            {"title": "Indirizzo o nome host", "value": t["host"] or "tocca per inserirlo", "f": "host"},
            {"title": "Porte TCP", "value": ", ".join(map(str, t["ports"])) or "nessuna (solo ping)", "f": "ports"},
        ]
        self.widgets = [ListView((b.x, b.y, b.w, 132), items, 44, render=_field_row,
                                 on_select=lambda it: self.edit(it["f"]))]
        if self.idx is not None:
            bw = (b.w - 36) // 2
            self.widgets += [Button((12, b.bottom - 50, bw, 42), "Elimina", self.delete, "danger"),
                             Button((24 + bw, b.bottom - 50, bw, 42), "Salva", self.save, "primary")]
        else:
            self.widgets.append(Button((12, b.bottom - 50, b.w - 24, 42), "Salva", self.save, "primary"))

    def draw_content(self, s):
        b = self.body
        for i, ln in enumerate(wrap(EXAMPLES, 11, b.w - 28)):
            text(s, ln, (b.x + 14, b.y + 142 + i * 16), 11, T["muted"])

    def edit(self, f):
        t = self.t
        titles = {"name": "Nome del server", "host": "Indirizzo IP o nome host", "ports": "Porte (es. 445 3389)"}
        initial = ", ".join(map(str, t["ports"])) if f == "ports" else t[f]

        def done(v):
            v = v.strip()
            if f == "ports":
                ports = parse_ports(v)
                if ports is None:
                    self.mgr.toast("Porte non valide: numeri da 1 a 65535 separati da spazio")
                    return
                t["ports"] = ports
            else:
                t[f] = v
            self.build()
        self.mgr.push(Keyboard(self.mgr, titles[f], done, initial=initial,
                               layout="123" if f == "ports" else "abc"))

    def save(self):
        t = self.t
        if not t["host"]:
            self.mgr.toast("Inserisci l'indirizzo o il nome del server")
            return
        if " " in t["host"] or (t["host"][0].isdigit() and t["host"].count(".") == 3 and not nd.valid_ip(t["host"])):
            self.mgr.toast("Indirizzo non valido")
            return
        cfg = net_cfg(self.mgr)
        tg = targets(cfg)
        if self.idx is None:
            tg.append(t)
        else:
            tg[self.idx] = t
        self.mgr.ctx.save_config()
        self.mgr.pop()
        self.mgr.toast("Salvato: verrà controllato al prossimo test")

    def delete(self):
        def do():
            del targets(net_cfg(self.mgr))[self.idx]
            self.mgr.ctx.save_config()
            self.mgr.pop()
        self.mgr.confirm("Eliminare il server?", self.t.get("name") or self.t["host"], "Elimina", do, True)


def _field_row(s, r, it):
    text(s, it["title"], (r.x + 14, r.centery), 13, T["muted"], anchor="midleft")
    text(s, it["value"], (r.right - 14, r.centery), 15, anchor="midright", maxw=r.w // 2 + 20)
