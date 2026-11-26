"""Schermata dello storico (prese di rete e Wi-Fi): elenco con data e ora, ricerca, dettagli, cancellazione."""
from core import history
from core.framework import Screen
from core.keyboard import Keyboard
from core.ui import T, Button, ListView, text

from .common import Detail

ST = {"ok": "OK", "warn": "attenzione", "fail": "errore", "off": "-", "wait": "-", "run": "-"}


# ------------------------------------------------------------ prese di rete
def net_entry(diag):
    """Voce di storico dal Tester rete."""
    nb = diag.listener.neighbor or {}
    ipi = diag.ipi or {}
    li = diag.li or {}
    checks = {k: diag.get(k) for k in ("link", "switch", "ip", "gw", "dns", "inet", "svc")}
    return {
        "switch": nb.get("name") or nb.get("chassis") or "", "port": nb.get("port") or "",
        "port_desc": nb.get("port_desc") or "", "vlan": nb.get("vlan"), "voice_vlan": nb.get("voice_vlan"),
        "mgmt": nb.get("mgmt") or "", "proto": nb.get("proto") or "", "eapol": bool(diag.listener.eapol),
        "ip": f"{ipi['addr']}/{ipi['prefix']}" if ipi.get("addr") else "", "gateway": ipi.get("gateway") or "",
        "dhcp": ipi.get("dynamic"), "dhcp_took": round(diag.dhcp_took) if diag.dhcp_took else None,
        "speed": li.get("speed"), "duplex": li.get("duplex"),
        "status": {k: c["st"] for k, c in checks.items()}, "summary": {k: c["sum"] for k, c in checks.items()},
    }


def net_title(e):
    if e.get("switch") or e.get("port"):
        return f"{e.get('switch') or '?'} · {e.get('port') or '?'}" + (f" · VLAN {e['vlan']}" if e.get("vlan") else "")
    return "Switch non identificato"


def net_sub(e):
    parts = [history.when(e["t"])]
    if e.get("port_desc"):
        parts.append(e["port_desc"])
    parts.append(e.get("ip") or "nessun IP")
    bad = [k for k, v in (e.get("status") or {}).items() if v in ("warn", "fail")]
    if bad:
        parts.append(f"{len(bad)} avvisi")
    return " · ".join(parts)


def net_rows(e):
    names = {"link": "Cavo e link", "switch": "Switch e porta", "ip": "Indirizzo IP", "gw": "Gateway", "dns": "DNS",
             "inet": "Internet", "svc": "Server aziendali"}
    rows = [("Data e ora", history.when(e["t"])), ("Switch", e.get("switch") or "—"), ("Porta", e.get("port") or "—"),
            ("Descrizione porta", e.get("port_desc") or "—"),
            ("VLAN dati / voce", f"{e.get('vlan') or '—'} / {e.get('voice_vlan') or '—'}"),
            ("IP di gestione switch", e.get("mgmt") or "—"), ("802.1X", "richiesto" if e.get("eapol") else "no"),
            ("Indirizzo IP", (e.get("ip") or "—") + (" (DHCP)" if e.get("dhcp") else "")),
            ("Gateway", e.get("gateway") or "—")]
    if e.get("dhcp_took"):
        rows.append(("Tempo per l'IP", f"{e['dhcp_took']} s"))
    if e.get("speed"):
        rows.append(("Link", f"{e['speed']} Mbit/s {e.get('duplex') or ''}".strip()))
    for k, name in names.items():
        st = (e.get("status") or {}).get(k)
        if st:
            rows.append((f"{name} [{ST.get(st, st)}]", (e.get("summary") or {}).get(k) or "—"))
    return rows


# ------------------------------------------------------------------- Wi-Fi
def wifi_title(e):
    if e.get("ssid"):
        return f"{e['ssid']} · {e.get('signal', '?')} dBm · can. {e.get('channel', '?')}"
    return "Non collegato"


def wifi_sub(e):
    parts = [history.when(e["t"])]
    if e.get("place"):
        parts.append(e["place"])
    parts.append(f"{e.get('n_networks', 0)} reti, {e.get('n_aps', 0)} AP")
    if e.get("hints"):
        parts.append(f"{len(e['hints'])} avvisi")
    return " · ".join(parts)


def wifi_rows(e):
    rows = [("Data e ora", history.when(e["t"])), ("Rete", e.get("ssid") or "non collegato"),
            ("AP", e.get("bssid") or "—"), ("Canale", f"{e.get('channel') or '—'} ({e.get('band') or '—'})"),
            ("Segnale", f"{e.get('signal')} dBm" if e.get("signal") is not None else "—"),
            ("Velocità", e.get("rate") or "—"), ("Reti / AP visibili", f"{e.get('n_networks', 0)} / {e.get('n_aps', 0)}")]
    rows += [(n, f"{a} AP · migliore {b} dBm") for n, a, b in e.get("networks", [])]
    return rows


KINDS = {
    "net": {"title": "Storico prese", "row_title": net_title, "row_sub": net_sub, "rows": net_rows,
            "hints": lambda e: [s for k, s in (e.get("summary") or {}).items()
                                if (e.get("status") or {}).get(k) in ("warn", "fail")]},
    "wifi": {"title": "Storico Wi-Fi", "row_title": wifi_title, "row_sub": wifi_sub, "rows": wifi_rows,
             "hints": lambda e: e.get("hints") or []},
}


class HistoryScreen(Screen):
    def __init__(self, mgr, kind):
        super().__init__(mgr)
        self.kind, self.k = kind, KINDS[kind]
        self.title = self.k["title"]
        self.query = ""

    def build(self):
        a, b = self.area, self.body
        items = []
        q = self.query.lower()
        for e in history.load(self.mgr.ctx.data_dir, self.kind):
            t, sub = self.k["row_title"](e), self.k["row_sub"](e)
            if q and q not in (t + " " + sub + " " + " ".join(str(v) for v in e.values())).lower():
                continue
            items.append({"title": t, "sub": sub, "e": e})
        empty = f"Nessun risultato per \"{self.query}\"" if q else "Nessun test registrato"
        self.widgets = [
            ListView((b.x, b.y + (30 if q else 0), b.w, b.h - (30 if q else 0)), items, 48, render=_row,
                     empty_text=empty, on_select=lambda it: self.mgr.push(HistoryDetail(self.mgr, self.kind, it["e"]))),
            Button((a.right - 186, a.y + 6, 84, 28), "Cerca", self.search, size=13),
            Button((a.right - 96, a.y + 6, 88, 28), "Svuota", self.clear, size=13),
        ]
        self.count = len(items)

    def resume(self):
        self.build()

    def draw_content(self, s):
        if self.query:
            b = self.body
            text(s, f"Filtro: \"{self.query}\" · {self.count} risultati (tocca Cerca per cambiarlo)",
                 (b.x + 14, b.y + 15), 12, T["accent2"], anchor="midleft", maxw=b.w - 28)

    def search(self):
        def done(v):
            self.query = v.strip()
            self.build()
        self.mgr.push(Keyboard(self.mgr, "Cerca (switch, porta, VLAN, IP, rete…)", done, initial=self.query,
                               ok_label="Cerca"))

    def clear(self):
        def do():
            history.clear(self.mgr.ctx.data_dir, self.kind)
            self.build()
        self.mgr.confirm("Svuotare lo storico?", "Tutte le voci verranno eliminate da questo dispositivo.",
                         "Svuota", do, True)


def _row(s, r, it):
    text(s, it["title"], (r.x + 14, r.centery - 9), 14, anchor="midleft", maxw=r.w - 28)
    text(s, it["sub"], (r.x + 14, r.centery + 10), 12, T["muted"], anchor="midleft", maxw=r.w - 28)


class HistoryDetail(Detail):
    def __init__(self, mgr, kind, e):
        k = KINDS[kind]
        super().__init__(mgr, history.when(e["t"]), k["rows"](e), k["hints"](e))
        self.kind, self.e = kind, e

    def build(self):
        super().build()
        a = self.area
        self.widgets.append(Button((a.right - 96, a.y + 6, 88, 28), "Elimina", self.delete, "danger", size=13))

    def delete(self):
        def do():
            history.remove(self.mgr.ctx.data_dir, self.kind, self.e["t"])
            self.mgr.pop()
        self.mgr.confirm("Eliminare questa voce?", self.title, "Elimina", do, True)
