"""Scansioni attive: inviano traffico a molti indirizzi, quindi sono spente finché non le si abilita."""
import ipaddress
import threading

from core import netdiag as nd
from core.framework import Screen
from core.keyboard import Keyboard
from core.ui import T, ListView, Toggle, text, wrap

from .common import Detail, net_cfg

COMMON_PORTS = [(21, "FTP"), (22, "SSH"), (23, "Telnet"), (25, "SMTP"), (53, "DNS"), (80, "HTTP"), (88, "Kerberos"),
                (135, "RPC"), (139, "NetBIOS"), (389, "LDAP"), (443, "HTTPS"), (445, "SMB"), (515, "LPD"),
                (631, "IPP"), (636, "LDAPS"), (1433, "SQL Server"), (3306, "MySQL"), (3389, "Desktop remoto"),
                (5060, "SIP"), (5900, "VNC"), (8080, "HTTP alt"), (8443, "HTTPS alt"), (9100, "Stampa RAW")]


class ActiveScreen(Screen):
    title = "Scansioni attive"

    def __init__(self, mgr, main):
        super().__init__(mgr)
        self.main = main

    @property
    def enabled(self):
        return bool(net_cfg(self.mgr).get("active_scans"))

    def build(self):
        a, b = self.area, self.body
        tg = Toggle((a.right - 64, a.y + 6, 52, 28), self.enabled, self.set_enabled)
        items = [
            {"title": "Dispositivi nella rete", "subtitle": "Interroga ogni indirizzo della rete (ARP)", "act": self.scan},
            {"title": "Porte aperte su un indirizzo", "subtitle": "Prova 23 porte comuni (TCP)", "act": self.ports},
        ]
        lv = ListView((b.x, b.y + 70, b.w, b.h - 70), items, 50, on_select=lambda it: it["act"]())
        self.widgets = [lv, tg] if self.enabled else [tg]

    def draw_content(self, s):
        b = self.body
        msg = ("Abilitate. Usale solo dove sei autorizzato: possono far scattare gli allarmi di sicurezza della rete."
               if self.enabled else "Spente. Il tester resta in solo ascolto. Usa l'interruttore in alto per abilitarle "
               "dove sei autorizzato.")
        for i, ln in enumerate(wrap(msg, 13, b.w - 28)[:3]):
            text(s, ln, (b.x + 14, b.y + 10 + i * 18), 13, T["warn"] if self.enabled else T["muted"])
        if not self.enabled:
            for i, it in enumerate(("Dispositivi nella rete", "Porte aperte su un indirizzo")):
                text(s, it, (b.x + 14, b.y + 95 + i * 50), 15, T["muted"], anchor="midleft")

    def set_enabled(self, on):
        net_cfg(self.mgr)["active_scans"] = on
        self.mgr.ctx.save_config()
        self.build()

    def scan(self):
        ipi = self.main.diag.ipi or {}
        if not ipi.get("addr"):
            self.mgr.toast("Serve un indirizzo IP sulla porta")
            return
        self.mgr.push(ScanScreen(self.mgr, ipi))

    def ports(self):
        def go(host):
            host = host.strip()
            if not host:
                return
            dns = (self.main.diag.ipi or {}).get("dns") or []

            def job():
                ip, err = nd.resolve(host, dns)
                if not ip:
                    return [("Errore", f"{host}: {err}")]
                res = []
                for p, name in COMMON_PORTS:
                    r = nd.tcp_check(ip, p, timeout=0.8)
                    if r["ok"]:
                        res.append((f"{p} {name}", f"aperta · {r['ms']:.0f} ms"))
                return [("Indirizzo", ip)] + (res or [("Porte aperte", "nessuna tra quelle comuni")])
            self.mgr.run(job, lambda rows: self.mgr.push(Detail(self.mgr, f"Porte di {host}", rows)),
                         f"Scansione di {host}…")
        self.mgr.push(Keyboard(self.mgr, "Indirizzo da scansionare", go, layout="123", ok_label="Avvia"))


class ScanScreen(Screen):
    title = "Dispositivi nella rete"

    def __init__(self, mgr, ipi):
        super().__init__(mgr)
        self.ipi = ipi
        self.net = ipaddress.IPv4Network(f"{ipi['addr']}/{ipi['prefix']}", strict=False)
        self.done, self.prog, self.res = False, (0, 0, 0), []

    def enter(self):
        self.build()

        def prog(i, n, found):
            self.prog = (i, n, found)
            self.mgr.dirty = True

        def job():
            try:
                found = nd.arp_scan(str(self.net), self.ipi["addr"], progress=prog)
            except OSError as e:
                self.res = [{"title": "Errore", "subtitle": str(e), "static": True}]
                self.done = True
                return
            dns = self.ipi.get("dns") or []
            items = []
            for ip, mac in found:
                name = ""
                if dns:
                    r = nd.dns_lookup(dns[0], nd.reverse_name(ip), "PTR", timeout=0.7)
                    name = r["answers"][0] if r["ok"] else ""
                v = nd.vendor(mac)
                items.append({"title": ip + (f"  {name}" if name else ""),
                              "subtitle": mac + (f" · {v}" if v else ""), "static": True})
                self.prog = (self.prog[1], self.prog[1], len(items))
                self.mgr.dirty = True
            self.res = items
            self.done = True
            self.build()
            self.mgr.dirty = True

        threading.Thread(target=job, daemon=True).start()

    def build(self):
        b = self.body
        self.widgets = [ListView((b.x, b.y + 30, b.w, b.h - 30), self.res, 44,
                                 empty_text="" if not self.done else "Nessun dispositivo ha risposto")]

    def draw_content(self, s):
        b = self.body
        i, n, found = self.prog
        msg = (f"{len(self.res)} dispositivi in {self.net}" if self.done else
               f"Scansione di {self.net}: {i}/{n} · {found} trovati…")
        text(s, msg, (b.x + 14, b.y + 15), 13, T["muted"], anchor="midleft")
