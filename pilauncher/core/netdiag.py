"""Diagnostica della rete cablata (eth0): link, switch (LLDP/CDP), 802.1X, DHCP, ping, DNS, Internet.

Tutte le funzioni sono bloccanti: vanno chiamate da un thread. Richiedono root (il launcher gira come root).
"""
import json
import os
import random
import re
import socket
import struct
import threading
import time

from .system import run

IFACE = "eth0"
SO_BINDTODEVICE = 25
SYS = "/sys/class/net"


# ===================================================================== link
def _sys(name, iface=IFACE):
    try:
        with open(f"{SYS}/{iface}/{name}") as f:
            return f.read().strip()
    except OSError:
        return None


def _sys_int(name, iface=IFACE):
    v = _sys(name, iface)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def iface_present(iface=IFACE):
    return os.path.isdir(f"{SYS}/{iface}")


def carrier(iface=IFACE):
    return _sys("carrier", iface) == "1"


def _modes_max(modes):
    speeds = [int(m) for m in re.findall(r"(\d+)base", modes)]
    return max(speeds) if speeds else None


def _ethtool_fields(out):
    """Output di `ethtool eth0` -> {chiave: valore}, unendo le righe di continuazione."""
    fields, key = {}, None
    for line in out.splitlines():
        if ":" in line and not line.startswith("\t\t") and not line.startswith(" " * 8):
            k, v = line.split(":", 1)
            key = k.strip()
            fields[key] = v.strip()
        elif key:
            fields[key] += " " + line.strip()
    return fields


def link_info(iface=IFACE):
    info = {
        "present": iface_present(iface),
        "carrier": carrier(iface),
        "mac": _sys("address", iface),
        "speed": None, "duplex": None,
        "flaps": _sys_int("carrier_changes", iface),
        "rx_crc": _sys_int("statistics/rx_crc_errors", iface),
        "rx_err": _sys_int("statistics/rx_errors", iface),
        "tx_err": _sys_int("statistics/tx_errors", iface),
        "our_max": None, "partner_max": None, "autoneg": None,
    }
    if info["carrier"]:
        sp = _sys_int("speed", iface)
        info["speed"] = sp if sp and sp > 0 else None
        info["duplex"] = _sys("duplex", iface)
    rc, out, _ = run(["ethtool", iface], 5)
    if rc == 0:
        f = _ethtool_fields(out)
        info["our_max"] = _modes_max(f.get("Supported link modes", ""))
        info["partner_max"] = _modes_max(f.get("Link partner advertised link modes", ""))
        info["autoneg"] = f.get("Auto-negotiation")
    return info


def link_hints(li):
    """Avvisi leggibili sul link."""
    hints = []
    if not li["carrier"]:
        return hints
    sp = li["speed"]
    if li["duplex"] == "half":
        hints.append("Half duplex: possibile impostazione forzata sullo switch")
    if sp and li["partner_max"] and li["our_max"]:
        best = min(li["partner_max"], li["our_max"])
        if sp < best:
            hints.append(f"Link a {sp} Mbit/s ma entrambi arrivano a {best}: probabile cavo con coppie danneggiate")
        elif li["partner_max"] < li["our_max"]:
            hints.append(f"La porta dello switch arriva al massimo a {li['partner_max']} Mbit/s")
    elif sp == 100 and (li["our_max"] or 1000) >= 1000:
        hints.append("Link a 100 Mbit/s: porta a 100 o cavo con coppie danneggiate")
    if li["rx_crc"]:
        hints.append(f"{li['rx_crc']} errori CRC: cavo o connettore difettoso")
    return hints


def fmt_speed(mbit):
    if not mbit:
        return "?"
    return f"{mbit // 1000} Gbit/s" if mbit >= 1000 else f"{mbit} Mbit/s"


# ======================================================================= IP
def ip_info(iface=IFACE):
    """Indirizzo, gateway, DNS e opzioni DHCP dell'interfaccia."""
    info = {"addr": None, "prefix": None, "dynamic": None, "lease_left": None, "gateway": None,
            "dns": [], "domain": None, "dhcp_server": None, "lease_time": None, "nm_state": None}
    rc, out, _ = run(["ip", "-j", "-4", "addr", "show", "dev", iface], 5)
    try:
        for a in (json.loads(out)[0].get("addr_info", []) if rc == 0 and out.strip() else []):
            if a.get("family") == "inet":
                info["addr"], info["prefix"] = a.get("local"), a.get("prefixlen")
                info["dynamic"] = bool(a.get("dynamic"))
                vl = a.get("valid_life_time")
                info["lease_left"] = vl if isinstance(vl, int) and vl < 0xFFFFFFFF else None
                break
    except (ValueError, IndexError):
        pass
    rc, out, _ = run(["ip", "-j", "-4", "route", "show", "default", "dev", iface], 5)
    try:
        routes = json.loads(out) if rc == 0 and out.strip() else []
        if routes:
            info["gateway"] = routes[0].get("gateway")
    except ValueError:
        pass
    rc, out, _ = run(["nmcli", "-t", "-f", "GENERAL.STATE,IP4.DNS,DHCP4", "device", "show", iface], 5)
    for line in out.splitlines():
        k, _, v = line.partition(":")
        if k == "GENERAL.STATE":
            info["nm_state"] = v
        elif k.startswith("IP4.DNS") and v:
            info["dns"].append(v)
        elif k.startswith("DHCP4.OPTION"):
            ok, _, ov = v.partition(" = ")
            ok = ok.strip()
            if ok == "dhcp_server_identifier":
                info["dhcp_server"] = ov
            elif ok == "dhcp_lease_time":
                info["lease_time"] = int(ov) if ov.isdigit() else None
            elif ok == "domain_name":
                info["domain"] = ov.split()[0] if ov else None
    return info


def renew_dhcp(iface=IFACE, timeout=40):
    """Scollega e ricollega l'interfaccia con NetworkManager. Ritorna (ok, secondi, errore)."""
    run(["nmcli", "device", "disconnect", iface], 15)
    t0 = time.time()
    rc, out, err = run(["nmcli", "--wait", str(timeout), "device", "connect", iface], timeout + 10)
    dt = time.time() - t0
    if rc != 0:
        return False, dt, (err or out).strip().replace("Error: ", "")[:160] or "nessuna risposta"
    return True, dt, ""


# ======================================================== profilo di rete
NM_CON = "pilauncher-eth0"


def parse_prefix(v):
    """'24', '/24' o '255.255.255.0' -> 24 (None se non valido)."""
    import ipaddress
    v = str(v).strip().lstrip("/")
    try:
        if "." in v:
            return ipaddress.IPv4Network(f"0.0.0.0/{v}").prefixlen
        n = int(v)
        return n if 0 < n <= 32 else None
    except ValueError:
        return None


def valid_ip(v):
    import ipaddress
    try:
        ipaddress.IPv4Address(str(v).strip())
        return True
    except ValueError:
        return False


def apply_ip_config(prof, iface=IFACE, timeout=20):
    """Configura eth0 con NetworkManager. prof None = DHCP, altrimenti {addr, prefix, gw, dns:[...]}.

    Usa un profilo dedicato con priorità alta, così resta valido anche ai prossimi collegamenti del cavo.
    Ritorna (ok, messaggio)."""
    rc, out, _ = run(["nmcli", "-t", "-f", "NAME", "connection", "show"], 5)
    if NM_CON not in out.splitlines():
        rc, out, err = run(["nmcli", "connection", "add", "type", "ethernet", "ifname", iface, "con-name", NM_CON,
                            "connection.autoconnect", "yes", "connection.autoconnect-priority", "100"], 10)
        if rc != 0:
            return False, (err or out).strip()[:160]
    if prof is None:
        args = ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", "",
                "ipv4.dad-timeout", "-1"]
    else:
        args = ["ipv4.method", "manual", "ipv4.addresses", f"{prof['addr']}/{prof['prefix']}",
                "ipv4.gateway", prof.get("gw") or "", "ipv4.dns", " ".join(prof.get("dns") or []),
                "ipv4.dad-timeout", "3000"]
    rc, out, err = run(["nmcli", "connection", "modify", NM_CON] + args, 10)
    if rc != 0:
        return False, (err or out).strip().replace("Error: ", "")[:160]
    if not carrier(iface):
        return True, "Salvato: verrà usato quando colleghi il cavo"
    rc, out, err = run(["nmcli", "--wait", str(timeout), "connection", "up", NM_CON], timeout + 10)
    if rc != 0:
        txt = (err or out).lower()
        if prof is not None and ("ip configuration" in txt or "dad" in txt or "already" in txt):
            return False, f"{prof['addr']} sembra già usato da un altro dispositivo"
        if prof is None:
            return False, "Nessuna risposta DHCP"
        return False, (err or out).strip().replace("Error: ", "")[:160]
    return True, "Configurazione applicata"


# ============================================================ ascolto ARP
def sniff_arp(secs=20, iface=IFACE, stop=None, progress=None):
    """Ascolta le richieste ARP sulla porta per capire la rete: ritorna
    {ips: {ip: n}, targets: {ip: n}, subnet, gateway} con subnet /24 più frequente e gateway più richiesto."""
    ips, targets = {}, {}
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806))
    try:
        s.bind((iface, 0))
        s.settimeout(0.5)
        t_end = time.time() + secs
        while time.time() < t_end and not (stop and stop.is_set()):
            if progress:
                progress(secs - int(t_end - time.time()), secs, len(ips))
            try:
                f = s.recv(256)
            except socket.timeout:
                continue
            off = 14
            if len(f) >= 18 and f[12:14] == b"\x81\x00":
                off = 18
            a = f[off:off + 28]
            if len(a) < 28 or a[:2] != b"\x00\x01" or a[2:4] != b"\x08\x00":
                continue
            spa, tpa = socket.inet_ntoa(a[14:18]), socket.inet_ntoa(a[24:28])
            if spa != "0.0.0.0":
                ips[spa] = ips.get(spa, 0) + 1
            if a[7] == 1 and tpa != spa:
                targets[tpa] = targets.get(tpa, 0) + 1
    finally:
        s.close()
    nets = {}
    for ip in list(ips) + list(targets):
        if ip.startswith(("169.254.", "0.")):
            continue
        n = ip.rsplit(".", 1)[0]
        nets[n] = nets.get(n, 0) + ips.get(ip, 0) + targets.get(ip, 0)
    subnet = max(nets, key=nets.get) if nets else None
    gw = None
    if subnet:
        cand = {ip: c for ip, c in targets.items() if ip.startswith(subnet + ".")}
        gw = max(cand, key=cand.get) if cand else None
    # indirizzi cercati più volte da altri ma che non rispondono mai: dispositivi spenti o scollegati,
    # tra cui spesso il PC che di solito sta su questa presa
    missing = sorted((ip for ip, c in targets.items() if ip not in ips and c >= 2 and ip != gw
                      and (not subnet or ip.startswith(subnet + "."))), key=lambda ip: -targets[ip])
    return {"ips": ips, "targets": targets, "subnet": subnet, "gateway": gw, "missing": missing}


# ===================================================================== ping
_PING_RX = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received")
_PING_RTT = re.compile(r"= ([\d.]+)/([\d.]+)/([\d.]+)")


def ping(host, count=5, iface=IFACE, interval=0.2):
    cmd = ["ping", "-n", "-q", "-c", str(count), "-i", str(interval), "-W", "1"]
    if iface:
        cmd += ["-I", iface]
    rc, out, err = run(cmd + [host], count * (interval + 1) + 5)
    m = _PING_RX.search(out)
    if not m:
        return {"ok": False, "error": (err or out).strip().splitlines()[-1][:120] if (err or out).strip()
                else "ping non riuscito"}
    sent, recv = int(m.group(1)), int(m.group(2))
    res = {"ok": recv > 0, "sent": sent, "recv": recv, "loss": 100 - recv * 100 // max(1, sent),
           "min": None, "avg": None, "max": None, "error": ""}
    r = _PING_RTT.search(out)
    if r:
        res["min"], res["avg"], res["max"] = (float(x) for x in r.groups())
    return res


# ====================================================================== DNS
def _skip_name(data, off):
    while True:
        n = data[off]
        if n == 0:
            return off + 1
        if n & 0xC0 == 0xC0:
            return off + 2
        off += n + 1


def dns_query(server, name, iface=IFACE, timeout=2.0):
    """Query A diretta al server, uscendo da iface. Ritorna {ok, ips, ms, error}."""
    tid = random.randint(0, 0xFFFF)
    q = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    q += b"".join(bytes([len(p)]) + p.encode() for p in name.strip(".").split(".")) + b"\0"
    q += struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if iface:
            try:
                s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, iface.encode() + b"\0")
            except OSError:
                pass
        s.settimeout(timeout)
        t0 = time.time()
        s.sendto(q, (server, 53))
        while True:
            data, _ = s.recvfrom(2048)
            if len(data) >= 12 and struct.unpack(">H", data[:2])[0] == tid:
                break
        ms = (time.time() - t0) * 1000
    except socket.timeout:
        return {"ok": False, "ips": [], "ms": None, "error": "Nessuna risposta"}
    except OSError as e:
        return {"ok": False, "ips": [], "ms": None, "error": str(e)}
    finally:
        s.close()
    flags, qd, an = struct.unpack(">HHH", data[2:8])
    rcode = flags & 0xF
    if rcode:
        err = {2: "Errore del server", 3: "Nome inesistente", 5: "Richiesta rifiutata"}.get(rcode, f"Errore {rcode}")
        return {"ok": False, "ips": [], "ms": ms, "error": err}
    off = 12
    try:
        for _ in range(qd):
            off = _skip_name(data, off) + 4
        ips = []
        for _ in range(an):
            off = _skip_name(data, off)
            typ, _cls, _ttl, ln = struct.unpack(">HHIH", data[off:off + 10])
            off += 10
            if typ == 1 and ln == 4:
                ips.append(socket.inet_ntoa(data[off:off + 4]))
            off += ln
    except (IndexError, struct.error):
        return {"ok": False, "ips": [], "ms": ms, "error": "Risposta non valida"}
    return {"ok": bool(ips), "ips": ips, "ms": ms, "error": "" if ips else "Nessun indirizzo"}


# ================================================================= Internet
def http_check(url, iface=IFACE, timeout=6):
    """Ritorna {code, ms, error}. code 0 = nessuna risposta."""
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{time_total}", "-m", str(timeout)]
    if iface:
        cmd += ["--interface", iface]
    rc, out, err = run(cmd + [url], timeout + 4)
    try:
        code, t = out.split()
        code, ms = int(code), float(t) * 1000
    except ValueError:
        code, ms = 0, None
    errors = {6: "Nome non risolto", 7: "Connessione rifiutata", 28: "Tempo scaduto", 35: "Errore TLS",
              60: "Certificato non valido (ispezione SSL?)", 127: "curl non installato"}
    return {"code": code, "ms": ms, "error": "" if code else errors.get(rc, f"Errore curl {rc}")}


# ============================================================== test cavo
_PAIR_CODE = re.compile(r"Pair ([A-D]) code (.+)")
_PAIR_LEN = re.compile(r"Pair ([A-D]), fault length: ([\d.]+)m")
PAIR_IT = {"OK": "OK", "Open Circuit": "Aperta", "Short within Pair": "In corto",
           "Short to another pair": "In corto con un'altra", "Unknown": "Sconosciuto"}


def cable_test(iface=IFACE):
    """Test TDR del PHY (ethtool --cable-test). Interrompe il link per qualche secondo."""
    rc, out, err = run(["ethtool", "--cable-test", iface], 30)
    txt = out + err
    if rc != 0:
        if "not supported" in txt.lower() or "operation not supported" in txt.lower():
            return {"ok": False, "error": "Il chip di rete non supporta il test del cavo"}
        return {"ok": False, "error": txt.strip().splitlines()[-1][:140] if txt.strip() else f"Errore {rc}"}
    pairs = {}
    for m in _PAIR_CODE.finditer(txt):
        pairs[m.group(1)] = {"code": PAIR_IT.get(m.group(2).strip(), m.group(2).strip()), "len": None}
    for m in _PAIR_LEN.finditer(txt):
        pairs.setdefault(m.group(1), {"code": "?", "len": None})["len"] = float(m.group(2))
    if not pairs:
        return {"ok": False, "error": "Nessun risultato dal test"}
    return {"ok": True, "pairs": pairs, "error": ""}


# ============================================================ lampeggio porta
def blink_port(stop, cycles=10, period=3.0, iface=IFACE, progress=None):
    """Spegne e riaccende il link per far lampeggiare il LED della porta sullo switch."""
    try:
        for i in range(cycles):
            if stop.is_set():
                break
            run(["ip", "link", "set", "dev", iface, "down"], 5)
            if progress:
                progress(i + 1, cycles, False)
            if stop.wait(period / 2):
                break
            run(["ip", "link", "set", "dev", iface, "up"], 5)
            if progress:
                progress(i + 1, cycles, True)
            if stop.wait(period / 2):
                break
    finally:
        run(["ip", "link", "set", "dev", iface, "up"], 5)
        run(["nmcli", "device", "connect", iface], 20)


# ===================================================== LLDP / CDP / 802.1X
ETH_P_802_2 = 0x0004
ETH_P_LLDP = 0x88CC
ETH_P_PAE = 0x888E
SOL_PACKET = 263
PACKET_ADD_MEMBERSHIP = 1
PACKET_MR_MULTICAST = 0
MAC_LLDP = bytes.fromhex("0180c200000e")
MAC_CDP = bytes.fromhex("01000ccccccc")
MAC_PAE = bytes.fromhex("0180c2000003")


def _mac(b):
    return ":".join(f"{x:02x}" for x in b)


def _txt(b):
    return b.decode("utf-8", "replace").strip("\x00 ").strip()


def parse_lldp(payload):
    """Payload LLDP (dopo l'header Ethernet) -> dict."""
    info = {"proto": "LLDP"}
    off = 0
    while off + 2 <= len(payload):
        hdr = struct.unpack(">H", payload[off:off + 2])[0]
        t, ln = hdr >> 9, hdr & 0x1FF
        v = payload[off + 2:off + 2 + ln]
        off += 2 + ln
        if t == 0:
            break
        if t == 1 and v:
            info["chassis"] = _mac(v[1:7]) if v[0] == 4 and len(v) >= 7 else _txt(v[1:])
        elif t == 2 and v:
            info["port"] = _mac(v[1:7]) if v[0] == 3 and len(v) >= 7 else _txt(v[1:])
        elif t == 4:
            info["port_desc"] = _txt(v)
        elif t == 5:
            info["name"] = _txt(v)
        elif t == 6:
            info["desc"] = _txt(v)
        elif t == 8 and len(v) >= 6 and v[1] == 1:
            info.setdefault("mgmt", socket.inet_ntoa(v[2:6]))
        elif t == 127 and len(v) >= 4:
            oui, sub, d = v[:3], v[3], v[4:]
            if oui == b"\x00\x80\xc2" and sub == 1 and len(d) >= 2:
                vid = struct.unpack(">H", d[:2])[0]
                if vid:
                    info["vlan"] = vid
            elif oui == b"\x00\x80\xc2" and sub == 3 and len(d) >= 3:
                vid, nl = struct.unpack(">H", d[:2])[0], d[2]
                info.setdefault("vlan_names", {})[vid] = _txt(d[3:3 + nl])
            elif oui == b"\x00\x12\xbb" and sub == 2 and len(d) >= 4:
                app, pol = d[0], struct.unpack(">I", b"\0" + d[1:4])[0]
                vid = (pol >> 9) & 0xFFF
                if app == 1 and vid:
                    info["voice_vlan"] = vid
    return info


def _cdp_addrs(v):
    out = []
    try:
        n, off = struct.unpack(">I", v[:4])[0], 4
        for _ in range(n):
            pl = v[off + 1]
            proto = v[off + 2:off + 2 + pl]
            off += 2 + pl
            al = struct.unpack(">H", v[off:off + 2])[0]
            addr = v[off + 2:off + 2 + al]
            off += 2 + al
            if proto == b"\xcc" and al == 4:
                out.append(socket.inet_ntoa(addr))
    except (IndexError, struct.error):
        pass
    return out


def parse_cdp(payload):
    """Payload CDP (dopo LLC/SNAP) -> dict."""
    info = {"proto": "CDP"}
    off = 4  # versione, ttl, checksum
    while off + 4 <= len(payload):
        t, ln = struct.unpack(">HH", payload[off:off + 4])
        if ln < 4:
            break
        v = payload[off + 4:off + ln]
        off += ln
        if t == 0x01:
            info["name"] = _txt(v)
        elif t == 0x02:
            a = _cdp_addrs(v)
            if a:
                info.setdefault("mgmt", a[0])
        elif t == 0x03:
            info["port"] = _txt(v)
        elif t == 0x05:
            info["desc"] = _txt(v)
        elif t == 0x06:
            info["platform"] = _txt(v)
        elif t == 0x0A and len(v) >= 2:
            info["vlan"] = struct.unpack(">H", v[:2])[0]
        elif t == 0x0B and v:
            info["duplex"] = "full" if v[0] else "half"
        elif t == 0x0E and len(v) >= 3:
            info["voice_vlan"] = struct.unpack(">H", v[1:3])[0]
        elif t == 0x16:
            a = _cdp_addrs(v)
            if a:
                info["mgmt"] = a[0]
    return info


def parse_frame(frame):
    """Frame Ethernet completo -> ('lldp'|'cdp'|'eapol', dict) oppure None."""
    if len(frame) < 18:
        return None
    dst, et, off = frame[:6], struct.unpack(">H", frame[12:14])[0], 14
    if et == 0x8100:  # tag VLAN
        et, off = struct.unpack(">H", frame[16:18])[0], 18
    if et == ETH_P_LLDP:
        return "lldp", parse_lldp(frame[off:])
    if et == ETH_P_PAE:
        d = frame[off:]
        res = {"src": _mac(frame[6:12])}
        if len(d) >= 9 and d[1] == 0 and d[4] == 1 and d[8] == 1:
            res["identity_request"] = True
        return "eapol", res
    if et <= 1500 and dst == MAC_CDP and frame[off:off + 8] == b"\xaa\xaa\x03\x00\x00\x0c\x20\x00":
        return "cdp", parse_cdp(frame[off + 8:])
    return None


class NeighborListener:
    """Ascolta in background gli annunci dello switch (LLDP ogni ~30 s, CDP ogni ~60 s) e l'802.1X."""

    def __init__(self, iface=IFACE, on_change=None):
        self.iface, self.on_change = iface, on_change
        self.lldp = self.cdp = self.eapol = None
        self.started = time.time()
        self.error = ""
        self._stop = threading.Event()
        self._socks = []

    def start(self):
        try:
            idx = socket.if_nametoindex(self.iface)
            for proto, macs in ((ETH_P_LLDP, [MAC_LLDP]), (ETH_P_PAE, [MAC_PAE]), (ETH_P_802_2, [MAC_CDP])):
                s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(proto))
                s.bind((self.iface, 0))
                for mac in macs:
                    mreq = struct.pack("iHH8s", idx, PACKET_MR_MULTICAST, 6, mac)
                    try:
                        s.setsockopt(SOL_PACKET, PACKET_ADD_MEMBERSHIP, mreq)
                    except OSError:
                        pass
                s.settimeout(0.5)
                self._socks.append(s)
        except (OSError, AttributeError) as e:
            self.error = f"Ascolto non disponibile: {e}"
            self.close()
            return self
        for s in self._socks:
            threading.Thread(target=self._loop, args=(s,), daemon=True).start()
        return self

    def reset(self):
        self.lldp = self.cdp = self.eapol = None
        self.started = time.time()

    def _loop(self, s):
        while not self._stop.is_set():
            try:
                frame = s.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.wait(1):
                    break
                continue
            res = parse_frame(frame)
            if not res:
                continue
            kind, data = res
            data["at"] = time.time()
            setattr(self, kind, data)
            if self.on_change:
                self.on_change()

    def close(self):
        self._stop.set()
        for s in self._socks:
            try:
                s.close()
            except OSError:
                pass
        self._socks = []

    @property
    def neighbor(self):
        """L'annuncio più completo ricevuto (LLDP preferito, completato coi dati CDP)."""
        if not (self.lldp or self.cdp):
            return None
        merged = dict(self.cdp or {})
        merged.update({k: v for k, v in (self.lldp or {}).items() if v})
        if self.lldp and self.cdp:
            merged["proto"] = "LLDP + CDP"
        return merged
