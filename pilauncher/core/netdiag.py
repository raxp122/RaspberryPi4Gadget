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


# ============================================================ prova DHCP
def _csum(b):
    if len(b) % 2:
        b += b"\0"
    t = sum(struct.unpack(f">{len(b) // 2}H", b))
    t = (t >> 16) + (t & 0xFFFF)
    t += t >> 16
    return ~t & 0xFFFF


def _dhcp_discover(mac, xid):
    want = [1, 3, 6, 15, 42, 51, 54, 66, 150, 252]
    opts = bytes([53, 1, 1]) + bytes([61, 7, 1]) + mac + bytes([55, len(want)] + want) + b"\xff"
    bootp = struct.pack(">BBBBIHH4s4s4s4s16s64s128s", 1, 1, 6, 0, xid, 0, 0x8000, bytes(4), bytes(4), bytes(4),
                        bytes(4), mac + bytes(10), bytes(64), bytes(128)) + b"\x63\x82\x53\x63" + opts
    udp = struct.pack(">HHHH", 68, 67, 8 + len(bootp), 0) + bootp
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), random.randint(0, 0xFFFF), 0, 64, 17, 0,
                     bytes(4), b"\xff" * 4)
    ip = ip[:10] + struct.pack(">H", _csum(ip)) + ip[12:]
    return b"\xff" * 6 + mac + b"\x08\x00" + ip + udp


def _dhcp_parse(frame, xid):
    off = 14
    if frame[12:14] == b"\x81\x00":
        off = 18
    if frame[off - 2:off] != b"\x08\x00" or len(frame) < off + 28:
        return None
    ihl = (frame[off] & 0x0F) * 4
    if frame[off + 9] != 17:
        return None
    src_ip = socket.inet_ntoa(frame[off + 12:off + 16])
    u = off + ihl
    if struct.unpack(">H", frame[u + 2:u + 4])[0] != 68:
        return None
    b = frame[u + 8:]
    if len(b) < 240 or b[0] != 2 or struct.unpack(">I", b[4:8])[0] != xid or b[236:240] != b"\x63\x82\x53\x63":
        return None
    res = {"yiaddr": socket.inet_ntoa(b[16:20]), "giaddr": socket.inet_ntoa(b[24:28]), "src_ip": src_ip,
           "src_mac": _mac(frame[6:12]), "type": None, "server": None, "mask": None, "router": None,
           "dns": [], "lease": None, "opt82": False, "domain": None, "ntp": [], "tftp": None, "tftp_ips": [],
           "wpad": None}
    i = 240
    while i < len(b) and b[i] != 255:
        if b[i] == 0:
            i += 1
            continue
        t, ln = b[i], b[i + 1]
        v = b[i + 2:i + 2 + ln]
        i += 2 + ln
        if t == 53 and v:
            res["type"] = {2: "OFFER", 5: "ACK", 6: "NAK"}.get(v[0], str(v[0]))
        elif t == 54 and ln == 4:
            res["server"] = socket.inet_ntoa(v)
        elif t == 1 and ln == 4:
            res["mask"] = socket.inet_ntoa(v)
        elif t == 3 and ln >= 4:
            res["router"] = socket.inet_ntoa(v[:4])
        elif t == 6:
            res["dns"] = [socket.inet_ntoa(v[j:j + 4]) for j in range(0, ln - 3, 4)]
        elif t == 51 and ln == 4:
            res["lease"] = struct.unpack(">I", v)[0]
        elif t == 82:
            res["opt82"] = True
        elif t == 15:
            res["domain"] = _txt(v)
        elif t == 42:
            res["ntp"] = [socket.inet_ntoa(v[j:j + 4]) for j in range(0, ln - 3, 4)]
        elif t == 66:
            res["tftp"] = _txt(v)
        elif t == 150:
            res["tftp_ips"] = [socket.inet_ntoa(v[j:j + 4]) for j in range(0, ln - 3, 4)]
        elif t == 252:
            res["wpad"] = _txt(v)
    return res


def dhcp_probe(secs=12, iface=IFACE, progress=None):
    """Invia DHCPDISCOVER ogni 3 s e raccoglie le offerte. Conta anche il traffico che arriva sulla porta.
    Ritorna {sent, offers:[...], frames, senders, link_lost}."""
    mac = bytes.fromhex((_sys("address", iface) or "00:00:00:00:00:00").replace(":", ""))
    xid = random.randint(1, 0xFFFFFFFF)
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
    res = {"sent": 0, "offers": [], "frames": 0, "senders": set(), "link_lost": False}
    try:
        s.bind((iface, 0))
        s.settimeout(0.3)
        t0, next_send = time.time(), 0
        pkt = _dhcp_discover(mac, xid)
        while time.time() - t0 < secs:
            now = time.time()
            if not carrier(iface):
                res["link_lost"] = True
                break
            if now >= next_send:
                s.send(pkt)
                res["sent"] += 1
                next_send = now + 3
                if progress:
                    progress(int(now - t0), secs, res)
            try:
                f, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            if addr[2] == socket.PACKET_OUTGOING:
                continue
            res["frames"] += 1
            res["senders"].add(f[6:12])
            o = _dhcp_parse(f, xid)
            if o and not any(x["server"] == o["server"] and x["yiaddr"] == o["yiaddr"] for x in res["offers"]):
                res["offers"].append(o)
    finally:
        s.close()
    res["senders"] = len(res["senders"])
    return res


def dhcp_probe_report(r):
    """Risultato di dhcp_probe -> (stato, riassunto, righe, avvisi)."""
    rows = [("Richieste inviate", str(r["sent"])), ("Pacchetti ricevuti dalla porta", str(r["frames"])),
            ("Dispositivi che trasmettono", str(r["senders"]))]
    hints = []
    if r["offers"]:
        for i, o in enumerate(r["offers"], 1):
            tag = f"Offerta {i}" if len(r["offers"]) > 1 else "Offerta"
            rows += [(f"{tag}: indirizzo", o["yiaddr"]), (f"{tag}: server DHCP", o["server"] or o["src_ip"]),
                     (f"{tag}: gateway", o["router"] or "—"), (f"{tag}: DNS", ", ".join(o["dns"]) or "—")]
            if o["giaddr"] != "0.0.0.0":
                rows.append((f"{tag}: relay", o["giaddr"]))
            if o["type"] == "NAK":
                hints.append(f"Il server {o['server']} ha rifiutato la richiesta (NAK)")
        if len(r["offers"]) > 1:
            hints.append("Più server DHCP rispondono: possibile DHCP non autorizzato in rete")
        o = r["offers"][0]
        return "ok", f"Offerto {o['yiaddr']} da {o['server'] or o['src_ip']}", rows, hints
    if r["link_lost"]:
        hints.append("Il link è caduto durante la prova: la porta potrebbe essersi bloccata "
                     "(port security / err-disabled). Controlla che il PC funzioni ancora su questa presa")
        return "fail", "Link caduto durante la prova", rows, hints
    if r["frames"] == 0:
        hints.append("Dalla porta non arriva nessun traffico: porta disattivata, VLAN senza dispositivi "
                     "o porta che blocca il tester")
        return "fail", "Nessuna risposta e nessun traffico", rows, hints
    hints.append("La rete arriva alla porta ma nessun DHCP risponde al tester")
    hints.append("Cause tipiche: port security o assegnazione legata al MAC del PC, NAC/802.1X, "
                 "oppure la porta usa davvero un IP fisso")
    return "fail", f"Nessuna offerta · {r['frames']} pacchetti dalla rete", rows, hints


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


def _read_name(data, off, depth=0):
    labels = []
    while depth < 20:
        n = data[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:
            ptr = struct.unpack(">H", data[off:off + 2])[0] & 0x3FFF
            labels.append(_read_name(data, ptr, depth + 1)[0])
            off += 2
            break
        labels.append(data[off + 1:off + 1 + n].decode("ascii", "replace"))
        off += n + 1
    return ".".join(x for x in labels if x), off


QTYPES = {"A": 1, "PTR": 12, "SRV": 33}


def dns_lookup(server, name, qtype="A", iface=IFACE, timeout=2.0):
    """Query DNS generica (A, PTR, SRV). Ritorna {ok, answers:[str], ms, error}."""
    qt = QTYPES[qtype]
    tid = random.randint(0, 0xFFFF)
    q = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    q += b"".join(bytes([len(p)]) + p.encode() for p in name.strip(".").split(".")) + b"\0"
    q += struct.pack(">HH", qt, 1)
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
            data, _ = s.recvfrom(4096)
            if len(data) >= 12 and struct.unpack(">H", data[:2])[0] == tid:
                break
        ms = (time.time() - t0) * 1000
    except socket.timeout:
        return {"ok": False, "answers": [], "ms": None, "error": "Nessuna risposta"}
    except OSError as e:
        return {"ok": False, "answers": [], "ms": None, "error": str(e)}
    finally:
        s.close()
    flags, qd, an = struct.unpack(">HHH", data[2:8])
    if flags & 0xF:
        return {"ok": False, "answers": [], "ms": ms, "error": "Nome inesistente" if flags & 0xF == 3 else
                f"Errore {flags & 0xF}"}
    off, answers = 12, []
    try:
        for _ in range(qd):
            off = _skip_name(data, off) + 4
        for _ in range(an):
            off = _skip_name(data, off)
            typ, _cls, _ttl, ln = struct.unpack(">HHIH", data[off:off + 10])
            off += 10
            rd = data[off:off + ln]
            if typ == qt == 1 and ln == 4:
                answers.append(socket.inet_ntoa(rd))
            elif typ == qt == 12:
                answers.append(_read_name(data, off)[0])
            elif typ == qt == 33 and ln > 6:
                prio, weight, port = struct.unpack(">HHH", rd[:6])
                answers.append(f"{_read_name(data, off + 6)[0]}:{port}")
            off += ln
    except (IndexError, struct.error):
        return {"ok": False, "answers": [], "ms": ms, "error": "Risposta non valida"}
    return {"ok": bool(answers), "answers": answers, "ms": ms, "error": "" if answers else "Nessun record"}


def reverse_name(ip):
    return ".".join(reversed(ip.split("."))) + ".in-addr.arpa"


def resolve(host, servers, iface=IFACE):
    """Nome -> IP usando i DNS della porta (se host è già un IP lo ritorna)."""
    if valid_ip(host):
        return host, ""
    err = "Nessun server DNS"
    for srv in servers[:3]:
        r = dns_lookup(srv, host, "A", iface)
        if r["ok"]:
            return r["answers"][0], ""
        err = r["error"]
    return None, err


# ============================================================ TCP e NTP
def tcp_check(ip, port, iface=IFACE, timeout=2.0):
    """Connessione TCP: {ok, ms, error}."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if iface:
            try:
                s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, iface.encode() + b"\0")
            except OSError:
                pass
        s.settimeout(timeout)
        t0 = time.time()
        s.connect((ip, int(port)))
        return {"ok": True, "ms": (time.time() - t0) * 1000, "error": ""}
    except socket.timeout:
        return {"ok": False, "ms": None, "error": "Nessuna risposta (filtrata?)"}
    except ConnectionRefusedError:
        return {"ok": False, "ms": None, "error": "Rifiutata (servizio spento)"}
    except OSError as e:
        return {"ok": False, "ms": None, "error": e.strerror or str(e)}
    finally:
        s.close()


def ntp_offset(server, iface=IFACE, timeout=2.0):
    """Differenza in secondi tra l'ora del server NTP e quella del Pi (positiva = Pi indietro)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if iface:
            try:
                s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, iface.encode() + b"\0")
            except OSError:
                pass
        s.settimeout(timeout)
        t0 = time.time()
        s.sendto(b"\x1b" + bytes(47), (server, 123))
        data, _ = s.recvfrom(256)
        t1 = time.time()
        if len(data) < 48:
            return None
        sec, frac = struct.unpack(">II", data[40:48])
        srv = sec - 2208988800 + frac / 2 ** 32
        return srv - (t0 + t1) / 2
    except OSError:
        return None
    finally:
        s.close()


# ======================================================== ARP: duplicati e scansione
def _arp_frame(src_mac, src_ip, dst_ip):
    return (b"\xff" * 6 + src_mac + b"\x08\x06" + struct.pack(">HHBBH", 1, 0x0800, 6, 4, 1) + src_mac
            + socket.inet_aton(src_ip) + bytes(6) + socket.inet_aton(dst_ip))


def _arp_replies(sock, until, mac_self):
    """Raccoglie le risposte ARP fino al tempo 'until': {ip: mac}."""
    out = {}
    while time.time() < until:
        try:
            f = sock.recv(256)
        except socket.timeout:
            continue
        a = f[14:42]
        if len(a) < 28 or a[6:8] != b"\x00\x02" or a[8:14] == mac_self:
            continue
        out.setdefault(socket.inet_ntoa(a[14:18]), _mac(a[8:14]))
    return out


def arp_duplicate(ip, iface=IFACE, wait=2.0):
    """Sonda ARP (RFC 5227) per il proprio IP: ritorna il MAC di chi lo usa già, o None."""
    mac = bytes.fromhex((_sys("address", iface) or "00:00:00:00:00:00").replace(":", ""))
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806))
    try:
        s.bind((iface, 0))
        s.settimeout(0.2)
        frame = _arp_frame(mac, "0.0.0.0", ip)
        until = time.time() + wait
        for _ in range(3):
            s.send(frame)
            r = _arp_replies(s, min(until, time.time() + wait / 3), mac)
            if ip in r:
                return r[ip]
        return None
    finally:
        s.close()


def arp_scan(network, src_ip, iface=IFACE, wait=3.0, progress=None):
    """Scansione attiva: richiesta ARP a ogni indirizzo della rete (max /22). Ritorna [(ip, mac)]."""
    import ipaddress
    net = ipaddress.IPv4Network(network, strict=False)
    if net.prefixlen < 22:
        net = ipaddress.IPv4Network(f"{src_ip}/22", strict=False)
    mac = bytes.fromhex((_sys("address", iface) or "00:00:00:00:00:00").replace(":", ""))
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806))
    found = {}
    try:
        s.bind((iface, 0))
        s.settimeout(0.05)
        hosts = [str(h) for h in net.hosts() if str(h) != src_ip]
        for i, h in enumerate(hosts):
            s.send(_arp_frame(mac, src_ip, h))
            if i % 16 == 15:
                found.update(_arp_replies(s, time.time() + 0.02, mac))
                if progress:
                    progress(i + 1, len(hosts), len(found))
        found.update(_arp_replies(s, time.time() + wait, mac))
    finally:
        s.close()
    return sorted(found.items(), key=lambda kv: tuple(int(x) for x in kv[0].split(".")))


# ========================================================== vicini e MAC
OUI_FILES = ["/usr/share/ieee-data/oui.txt", "/usr/share/arp-scan/ieee-oui.txt"]
_oui_cache = {}


def vendor(mac):
    """Produttore dal MAC, se sul Pi c'è il database OUI (pacchetto ieee-data)."""
    if not mac:
        return ""
    key = mac.upper().replace(":", "")[:6]
    if not _oui_cache:
        _oui_cache["_"] = ""
        for path in OUI_FILES:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if "(base 16)" in line:
                            k, _, name = line.partition("(base 16)")
                            _oui_cache[k.strip()] = name.strip()
                        elif "\t" in line and len(line) > 7 and line[6] == "\t":
                            _oui_cache.setdefault(line[:6].upper(), line[7:].strip())
                break
            except OSError:
                continue
    return _oui_cache.get(key, "")


def neighbor_mac(ip, iface=IFACE):
    rc, out, _ = run(["ip", "-j", "neigh", "show", "dev", iface, ip], 5)
    try:
        for n in json.loads(out) if rc == 0 and out.strip() else []:
            if n.get("lladdr"):
                return n["lladdr"]
    except ValueError:
        pass
    return None


def ipv6_info(iface=IFACE):
    info = {"addrs": [], "router": None}
    rc, out, _ = run(["ip", "-j", "-6", "addr", "show", "dev", iface, "scope", "global"], 5)
    try:
        for a in (json.loads(out)[0].get("addr_info", []) if rc == 0 and out.strip() else []):
            info["addrs"].append(f"{a['local']}/{a['prefixlen']}")
    except (ValueError, IndexError, KeyError):
        pass
    rc, out, _ = run(["ip", "-j", "-6", "route", "show", "default", "dev", iface], 5)
    try:
        r = json.loads(out) if rc == 0 and out.strip() else []
        if r:
            info["router"] = r[0].get("gateway")
    except ValueError:
        pass
    return info


# ====================================================== MTU e traceroute
def path_mtu(host, iface=IFACE):
    """MTU massima senza frammentazione verso host (ricerca binaria con ping DF). None se ICMP bloccato."""
    def ok(size):
        rc, out, _ = run(["ping", "-n", "-q", "-c", "1", "-W", "1", "-M", "do", "-s", str(size), "-I", iface, host], 4)
        return " 1 received" in out or " 1 packets received" in out
    if not ok(548):
        return None
    lo, hi = 548, 1472
    if ok(hi):
        return hi + 28
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo + 28


_HOP = re.compile(r"From ([\d.]+).*(?:Time to live exceeded|ttl)", re.I)
_REPLY = re.compile(r"bytes from ([\d.]+)")


def traceroute(host, max_hops=15, iface=IFACE, progress=None):
    """Percorso verso host con ping a TTL crescente. Ritorna [(ttl, ip|None)] e se è arrivato."""
    hops, misses = [], 0
    for ttl in range(1, max_hops + 1):
        rc, out, _ = run(["ping", "-n", "-c", "1", "-W", "1", "-t", str(ttl), "-I", iface, host], 4)
        m = _REPLY.search(out)
        if m:
            hops.append((ttl, m.group(1)))
            return hops, True
        m = _HOP.search(out)
        hops.append((ttl, m.group(1) if m else None))
        misses = 0 if m else misses + 1
        if progress:
            progress(hops)
        if misses >= 3:
            break
    return hops, False


# ===================================================================== ping
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
MAC_STP = bytes.fromhex("0180c2000000")
MAC_PVST = bytes.fromhex("01000ccccccd")


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


def parse_bpdu(b, pvst=False):
    """BPDU di spanning tree -> dict (None se non valido)."""
    if len(b) < 4 or b[:2] != b"\x00\x00":
        return None
    ver, typ = b[2], b[3]
    if typ == 0x80:
        return {"proto": "STP", "tcn": True}
    if len(b) < 35:
        return None
    flags = b[4]
    rp, rmac = struct.unpack(">H", b[5:7])[0], _mac(b[7:13])
    cost = struct.unpack(">I", b[13:17])[0]
    bp, bmac = struct.unpack(">H", b[17:19])[0], _mac(b[19:25])
    name = {0: "STP", 2: "RSTP", 3: "MSTP"}.get(ver, f"STP v{ver}")
    if pvst:
        name = "PVST+" if ver == 0 else "Rapid PVST+"
    return {"proto": name, "root_prio": rp & 0xF000, "root_ext": rp & 0x0FFF, "root_mac": rmac, "cost": cost,
            "bridge_prio": bp & 0xF000, "bridge_mac": bmac, "port_id": f"{struct.unpack('>H', b[25:27])[0]:#06x}",
            "tc": bool(flags & 1), "is_root_port": cost == 0}


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
    if et <= 1500 and dst == MAC_STP and frame[off:off + 3] == b"\x42\x42\x03":
        r = parse_bpdu(frame[off + 3:])
        return ("stp", r) if r else None
    if et <= 1500 and dst == MAC_PVST and frame[off:off + 8] == b"\xaa\xaa\x03\x00\x00\x0c\x01\x0b":
        r = parse_bpdu(frame[off + 8:], pvst=True)
        return ("stp", r) if r else None
    return None


class NeighborListener:
    """Ascolta in background gli annunci dello switch (LLDP ogni ~30 s, CDP ogni ~60 s) e l'802.1X."""

    def __init__(self, iface=IFACE, on_change=None):
        self.iface, self.on_change = iface, on_change
        self.lldp = self.cdp = self.eapol = self.stp = None
        self.started = time.time()
        self.error = ""
        self._stop = threading.Event()
        self._socks = []

    def start(self):
        try:
            idx = socket.if_nametoindex(self.iface)
            for proto, macs in ((ETH_P_LLDP, [MAC_LLDP]), (ETH_P_PAE, [MAC_PAE]), (ETH_P_802_2, [MAC_CDP, MAC_STP, MAC_PVST])):
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
        self.lldp = self.cdp = self.eapol = self.stp = None
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
            if kind == "stp" and data.get("tcn"):
                continue
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
