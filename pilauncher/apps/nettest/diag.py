"""Sequenza dei controlli del Tester rete."""
import threading
import time
import traceback

from core import netdiag as nd

from .common import (LISTEN_MAX, DHCP_WAIT, INTERNET_URL, HTTPS_URL, DNS_TEST_NAME, TRACE_TARGET, NTP_FAIL, ORDER, _dur,
    _ping_rows, _http_txt)


# ============================================================ diagnostica
class Diagnosis:
    """Esegue i controlli in un thread e tiene lo stato da mostrare."""

    def __init__(self, on_change, get_targets=lambda: []):
        self.on_change, self.get_targets = on_change, get_targets
        self.dhcp_info = None
        self.dhcp_took = None
        self.dcs = []
        self.checks = {}
        self.li, self.ipi = None, None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.rerun = threading.Event()
        self.running = False
        self.link_up_at = None
        self.probe_sum = ""
        self.listener = nd.NeighborListener(on_change=self._changed)
        self.reset("wait", "")

    def _changed(self):
        self.on_change()

    def set(self, key, st, summary, rows=None, hints=None):
        with self.lock:
            self.checks[key] = {"st": st, "sum": summary, "rows": rows or [], "hints": hints or []}
        self.on_change()

    def extend(self, key, rows=(), hints=(), st=None, summary=None):
        """Aggiunge righe e avvisi a un controllo già fatto (peggiorando lo stato se serve)."""
        rank = {"ok": 0, "warn": 1, "fail": 2}
        with self.lock:
            c = self.checks.get(key)
            if not c:
                return
            c["rows"] = c["rows"] + list(rows)
            c["hints"] = c["hints"] + list(hints)
            if st and rank.get(st, 0) > rank.get(c["st"], 0):
                c["st"] = st
            if summary:
                c["sum"] = summary
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
                if self.rerun.is_set() and up:
                    self.link_up_at = time.time()
                self.rerun.clear()
                was_up = up
                if up:
                    if self.link_up_at is None:
                        self.link_up_at = time.time()
                    try:
                        self._sequence()
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
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
                for k in ("gw", "dns", "inet", "svc"):
                    self.set(k, "off", "Serve un indirizzo IP")
                return
            for key, step in (("ip", self._ip_extra), ("gw", self._check_gw), ("dns", self._check_dns),
                              ("inet", self._check_inet), ("svc", self._check_services)):
                self._safe(key, step)
        finally:
            self.running = False
            self.on_change()

    def _safe(self, key, step):
        """Un errore in un controllo non deve fermare gli altri né il thread che segue il cavo."""
        try:
            step()
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            c = self.get(key)
            self.set(key, "fail", f"Errore interno: {e}"[:80], c["rows"], c["hints"])

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
        probed = False
        while not self.stop.is_set():
            ipi = nd.ip_info()
            self.ipi = ipi
            if ipi["addr"]:
                break
            if not nd.carrier() or self.rerun.is_set():
                return False
            waited = time.time() - t0
            if waited > DHCP_WAIT and not probed:
                probed = True
                self._dhcp_failed(ipi)
            elif probed:
                # non ci si arrende: alcune porte danno l'IP dopo 1-2 minuti (802.1X con ripiego sul MAC)
                c = self.get("ip")
                self.set("ip", "fail", f"{self.probe_sum} · attendo ancora ({int(waited)} s)", c["rows"], c["hints"])
            else:
                self.set("ip", "run", f"Attesa DHCP… {int(waited)} s · tocca per l'IP fisso")
            self.stop.wait(1)
        else:
            return False
        took = time.time() - t0
        rows = [("Indirizzo", f"{ipi['addr']}/{ipi['prefix']}"),
                ("Tipo", "DHCP" if ipi["dynamic"] else "Statico"),
                ("Gateway", ipi["gateway"] or "—"),
                ("DNS", ", ".join(ipi["dns"]) or "—"),
                ("Dominio", ipi["domain"] or "—"),
                ("Server DHCP", ipi["dhcp_server"] or "—")]
        if ipi["dynamic"] and took >= 2:
            rows.insert(2, ("Tempo per ottenere l'IP", f"{took:.0f} s dal collegamento"))
        if ipi["lease_time"]:
            rows.append(("Durata lease", _dur(ipi["lease_time"])))
        if ipi["lease_left"] is not None:
            rows.append(("Lease rimanente", _dur(ipi["lease_left"])))
        hints = []
        if ipi["addr"].startswith("169.254."):
            hints.append("Indirizzo automatico 169.254: il DHCP non ha risposto")
        if ipi["dynamic"] and took > 30:
            hints.append(f"L'indirizzo è arrivato dopo {took:.0f} s: porta lenta (spanning tree senza portfast "
                         "o 802.1X con ripiego sul MAC)")
        if not ipi["gateway"]:
            hints.append("Nessun gateway ricevuto dal DHCP")
        if not ipi["dns"]:
            hints.append("Nessun server DNS ricevuto dal DHCP")
        self.dhcp_took = took if ipi["dynamic"] else None
        kind = (f"DHCP in {took:.0f} s" if took >= 2 else "DHCP") if ipi["dynamic"] else "fisso"
        self.set("ip", "warn" if hints else "ok", f"{ipi['addr']}/{ipi['prefix']} · {kind}", rows, hints)
        return True

    def _ip_extra(self):
        """Dopo aver ottenuto l'IP: duplicati, server DHCP presenti, opzioni, nome DNS, IPv6."""
        ipi = self.ipi
        c = self.get("ip")
        st0 = c["st"]
        self.set("ip", "run", c["sum"] + " · altri controlli…", c["rows"], c["hints"])
        rows, hints, st = [], [], None
        try:
            dup = nd.arp_duplicate(ipi["addr"])
        except OSError:
            dup = None
        rows.append(("IP duplicato", f"SÌ, usato anche da {dup}" if dup else "No"))
        if dup:
            hints.append(f"Un altro dispositivo ({dup}) usa lo stesso indirizzo {ipi['addr']}")
            st = "fail"
        if ipi["dynamic"]:
            try:
                r = nd.dhcp_probe(5)
            except OSError:
                r = None
            if r and r["offers"]:
                servers = sorted({o["server"] or o["src_ip"] for o in r["offers"]})
                rows.append(("Server DHCP che rispondono", ", ".join(servers)))
                if len(servers) > 1:
                    hints.append(f"Rispondono {len(servers)} server DHCP: possibile DHCP non autorizzato in rete")
                    st = st or "warn"
                o = r["offers"][0]
                self.dhcp_info = o
                if o["giaddr"] != "0.0.0.0":
                    rows.append(("Relay DHCP (interfaccia della VLAN)", o["giaddr"]))
                rows.append(("Opzione 82 (info porta)", "Sì" if o["opt82"] else "No"))
                for key, lab in (("ntp", "Server NTP (DHCP)"), ("tftp_ips", "TFTP opz. 150 (telefoni)")):
                    if o[key]:
                        rows.append((lab, ", ".join(o[key])))
                if o["tftp"]:
                    rows.append(("TFTP opz. 66", o["tftp"]))
                if o["wpad"]:
                    rows.append(("Proxy automatico (WPAD)", o["wpad"]))
        if ipi["dns"]:
            r = nd.dns_lookup(ipi["dns"][0], nd.reverse_name(ipi["addr"]), "PTR")
            rows.append(("Nome DNS del tester", r["answers"][0] if r["ok"] else "nessuno"))
        v6 = nd.ipv6_info()
        rows.append(("IPv6", ", ".join(v6["addrs"]) if v6["addrs"] else "non presente"))
        if v6["router"]:
            rows.append(("Router IPv6", v6["router"]))
        c = self.get("ip")
        self.set("ip", st0, c["sum"].replace(" · altri controlli…", ""), c["rows"], c["hints"])
        self.extend("ip", rows, hints, st)

    def _dhcp_failed(self, ipi):
        """Il DHCP di sistema non ha risposto: prova diretta per capire perché."""
        def prog(t, total, r):
            self.set("ip", "run", f"Analisi DHCP… {t}/{total} s · {r['frames']} pacchetti ricevuti")
        try:
            r = nd.dhcp_probe(12, progress=prog)
            st, summary, rows, hints = nd.dhcp_probe_report(r)
        except OSError as e:
            st, summary, rows, hints = "fail", "Nessuna risposta DHCP", [("Prova diretta", str(e))], []
        if st == "ok":
            hints.insert(0, "Il server risponde alla prova diretta ma il sistema non ha preso l'indirizzo: "
                            "usa Rinnova DHCP negli strumenti")
        rows.append(("Stato NetworkManager", ipi["nm_state"] or "—"))
        self.probe_sum = summary
        self.set("ip", "warn" if st == "ok" else "fail", summary + " · attendo ancora", rows,
                 hints + ["Il tester continua ad aspettare: alcune porte danno l'indirizzo dopo 1-2 minuti"]
                 + self._no_dhcp_hints())

    def _no_dhcp_hints(self):
        h = []
        if self.listener.eapol:
            h.append("La porta chiede l'autenticazione 802.1X: senza credenziali non dà accesso")
        nb = self.listener.neighbor
        if nb and nb.get("vlan"):
            h.append(f"La porta è sulla VLAN {nb['vlan']}: verifica che lì ci sia un DHCP")
        h.append("Se la porta usa un IP fisso, impostalo qui sotto")
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
        mac = nd.neighbor_mac(gw)
        extra = []
        if mac:
            v = nd.vendor(mac)
            extra.append(("MAC del gateway", mac + (f" ({v})" if v else "")))
        mtu = nd.path_mtu(gw)
        extra.append(("MTU verso il gateway", f"{mtu} byte" if mtu else "non misurabile (ping bloccato)"))
        hints = [f"MTU {mtu}: inferiore a 1500, possibili problemi con pacchetti grandi"] if mtu and mtu < 1500 else []
        self.extend("gw", extra, hints, "warn" if hints else None)

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
        domain = self.ipi["domain"] or (self.dhcp_info or {}).get("domain")
        self.dcs = []
        if domain:
            r = nd.dns_lookup(servers[0], f"_ldap._tcp.dc._msdcs.{domain}", "SRV")
            if r["ok"]:
                self.dcs = [a.rsplit(":", 1)[0] for a in r["answers"]]
                rows.append(("Domain controller", ", ".join(self.dcs)))
            else:
                rows.append(("Domain controller", "non trovati"))
            w = nd.dns_lookup(servers[0], f"wpad.{domain}", "A")
            rows.append(("wpad." + domain, ", ".join(w["answers"]) if w["ok"] else "non presente"))
        total = len([r for r in rows if " via " in r[0]])
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
        c = self.get("inet")
        base = c["sum"]
        self.set("inet", "run", base + " · percorso…", c["rows"], c["hints"])

        def prog(h):
            cc = self.get("inet")
            self.set("inet", "run", f"{base} · percorso, salto {len(h)}…", cc["rows"], cc["hints"])
        hops, reached = nd.traceroute(TRACE_TARGET, progress=prog)
        cc = self.get("inet")
        self.set("inet", c["st"], base, cc["rows"], cc["hints"])
        extra = [(f"Salto {t}", ip or "* (nessuna risposta)") for t, ip in hops]
        extra.append((f"Percorso verso {TRACE_TARGET}", "completo" if reached else "interrotto (ICMP filtrato?)"))
        mtu = nd.path_mtu(TRACE_TARGET) if reached else None
        if mtu:
            extra.append(("MTU verso Internet", f"{mtu} byte"))
        self.extend("inet", extra)

    def _check_services(self):
        """Server inseriti a mano (salvati solo sul Pi) e controllo dell'ora."""
        tg = self.get_targets()
        dns = self.ipi["dns"]
        rows, hints, ok, tot = [], [], 0, 0
        self.set("svc", "run", "Controllo…")
        for t in tg:
            tot += 1
            label = t.get("name") or t["host"]
            ip, err = nd.resolve(t["host"], dns)
            if not ip:
                rows.append((label, f"{t['host']}: nome non risolto ({err})"))
                continue
            ports = t.get("ports") or []
            if ports:
                res = [(p, nd.tcp_check(ip, p)) for p in ports]
                good = all(r["ok"] for _, r in res)
                val = " · ".join(f"{p} {'ok' if r['ok'] else 'NO'}" for p, r in res)
                bad = [f"{p}: {r['error']}" for p, r in res if not r["ok"]]
                if bad:
                    hints.append(f"{label}: " + "; ".join(bad))
            else:
                pr = nd.ping(ip, 2)
                good = pr.get("recv", 0) > 0
                val = f"ping {pr['avg']:.0f} ms" if good and pr.get("avg") is not None else "non risponde al ping"
            ok += good
            rows.append((label, f"{ip} · {val}"))
            self.set("svc", "run", f"Controllo {tot}/{len(tg)}…", rows)
        ntp_servers = ((self.dhcp_info or {}).get("ntp") or []) + self.dcs[:1] + dns[:1]
        offset, used = None, None
        for srv in ntp_servers:
            ip, _ = nd.resolve(srv, dns)
            offset = nd.ntp_offset(ip) if ip else None
            if offset is not None:
                used = srv
                break
        st_time = None
        if offset is None:
            rows.append(("Orario", "nessun server NTP raggiungibile"))
        else:
            rows.append((f"Orario rispetto a {used}", f"{offset:+.1f} s"))
            if abs(offset) > NTP_FAIL:
                hints.append(f"L'ora del server {used} differisce di {abs(offset) / 60:.0f} minuti dal tester: "
                             "se il tester ha l'ora giusta, il login al dominio sui PC fallisce")
                st_time = "warn"
        if not tg:
            hints.insert(0, "Nessun server configurato: aggiungili da Strumenti → Server aziendali")
            self.set("svc", st_time or "off", "Nessun server configurato · tocca per aggiungerli", rows, hints)
            return
        st = "ok" if ok == tot else "warn" if ok else "fail"
        if st_time and st == "ok":
            st = st_time
        self.set("svc", st, f"{ok}/{tot} raggiungibili", rows, hints)

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
            self._stp_rows(rows, hints)
            return {"st": "warn" if hints else "ok", "sum": summary, "rows": rows, "hints": hints}
        waited = time.time() - lst.started
        if waited < LISTEN_MAX:
            extra = " · 802.1X attivo" if lst.eapol else ""
            return {"st": "run", "sum": f"In ascolto LLDP/CDP… {int(waited)} s{extra}", "rows": [], "hints": hints}
        self._stp_rows(rows, hints)
        hints.append("Lo switch non invia LLDP/CDP (disattivati, switch non gestito o presa a muro su hub)")
        return {"st": "warn", "sum": "Nessun annuncio dallo switch" + (" · 802.1X attivo" if lst.eapol else ""),
                "rows": rows, "hints": hints}

    def _stp_rows(self, rows, hints):
        stp = self.listener.stp
        if not stp:
            rows.append(("Spanning tree", "nessun BPDU ricevuto"))
            return
        rows.append(("Spanning tree", stp["proto"]))
        vlan = f" · VLAN/istanza {stp['root_ext']}" if stp["root_ext"] else ""
        rows.append(("Root bridge", f"{stp['root_mac']} (priorità {stp['root_prio']}){vlan}"))
        rows.append(("Switch che invia i BPDU", f"{stp['bridge_mac']} (priorità {stp['bridge_prio']})"))
        rows.append(("Costo verso il root", "0 (questo switch è il root)" if stp["is_root_port"] else str(stp["cost"])))
        if stp["tc"]:
            hints.append("Cambio di topologia spanning tree in corso")
        if self.dhcp_took and self.dhcp_took > 25:
            hints.append(f"La porta partecipa allo spanning tree e l'IP è arrivato dopo {self.dhcp_took:.0f} s: "
                         "probabilmente manca portfast (edge port)")

    def get(self, key):
        if key == "switch":
            return self.switch_state()
        with self.lock:
            return dict(self.checks.get(key, {"st": "wait", "sum": "", "rows": [], "hints": []}))
