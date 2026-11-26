"""Diagnostica Wi-Fi (wlan0): scansione degli AP con `iw`, collegamento attuale, statistiche, analisi.

Funzioni bloccanti: chiamarle da un thread. Richiedono root per la scansione completa.
"""
import re
import shutil
import time

from .system import run, split_terse

IFACE = "wlan0"


# ================================================================== utilità
def channel_of(freq):
    f = int(round(freq))
    if f == 2484:
        return 14
    if 2412 <= f <= 2472:
        return (f - 2407) // 5
    if 5150 <= f <= 5925:
        return (f - 5000) // 5
    if 5955 <= f <= 7115:
        return (f - 5950) // 5
    return 0


def band_of(freq):
    return "2,4 GHz" if freq < 3000 else "5 GHz" if freq < 5930 else "6 GHz"


def quality(dbm):
    """(etichetta, livello 0..4) per un segnale in dBm."""
    if dbm is None:
        return "?", 0
    if dbm >= -55:
        return "ottimo", 4
    if dbm >= -67:
        return "buono", 3
    if dbm >= -75:
        return "sufficiente", 2
    if dbm >= -85:
        return "scarso", 1
    return "inutilizzabile", 0


# =============================================================== scansione
def parse_iw_scan(out):
    """Output di `iw dev wlan0 scan` -> lista di AP (dict)."""
    aps = []
    for block in re.split(r"\n(?=BSS [0-9a-f]{2}:)", "\n" + out.strip()):
        block = block.strip()
        m = re.match(r"BSS ([0-9a-f:]{17})", block)
        if not m:
            continue
        ap = {"bssid": m.group(1), "ssid": "", "freq": 0.0, "signal": None, "channel": 0, "width": 20,
              "security": "Aperta", "stations": None, "util": None, "std": "", "k": False, "v": False, "r": False,
              "associated": "-- associated" in block.split("\n", 1)[0], "age_ms": None}
        g = re.search(r"^\s*freq: ([\d.]+)", block, re.M)
        if g:
            ap["freq"] = float(g.group(1))
            ap["channel"] = channel_of(ap["freq"])
        g = re.search(r"^\s*signal: (-?[\d.]+) dBm", block, re.M)
        if g:
            ap["signal"] = float(g.group(1))
        g = re.search(r"^\s*SSID: ?(.*)$", block, re.M)
        if g:
            ssid = g.group(1).strip()
            ap["ssid"] = "" if not ssid or set(ssid.replace("\\x00", "")) == set() else ssid
        g = re.search(r"last seen: (\d+) ms ago", block)
        if g:
            ap["age_ms"] = int(g.group(1))
        g = re.search(r"station count: (\d+)", block)
        if g:
            ap["stations"] = int(g.group(1))
        g = re.search(r"channel utili[sz]ation: (\d+)/255", block)
        if g:
            ap["util"] = round(int(g.group(1)) * 100 / 255)
        g = re.search(r"secondary channel offset: (\w+)", block)
        if g and g.group(1) in ("above", "below"):
            ap["width"] = 40
        g = re.search(r"VHT operation:.*?channel width: (\d)", block, re.S)
        if g and g.group(1) in ("1", "2", "3"):
            ap["width"] = 80 if g.group(1) == "1" else 160
        std = []
        if "HT capabilities" in block or "HT operation" in block:
            std.append("n")
        if "VHT capabilities" in block or "VHT operation" in block:
            std.append("ac")
        if "HE capabilities" in block or "HE operation" in block:
            std.append("ax")
        ap["std"] = "/".join(std)
        ap["k"] = "RM enabled capabilities" in block
        ap["v"] = "BSS Transition" in block
        ap["r"] = "Mobility Domain" in block or "FT/PSK" in block or "FT/IEEE 802.1X" in block or "FT/SAE" in block
        ap["security"] = _security(block)
        aps.append(ap)
    return aps


def _security(block):
    rsn = re.search(r"RSN:(.*?)(?:\n\t\S|\Z)", block, re.S)
    auth = ""
    if rsn:
        a = re.search(r"Authentication suites: (.*)", rsn.group(1))
        auth = a.group(1) if a else ""
        if "SAE" in auth and "PSK" in auth:
            return "WPA2/WPA3-Personal"
        if "SAE" in auth:
            return "WPA3-Personal"
        if "802.1X" in auth:
            return "WPA3-Enterprise" if "SHA-256" in auth or "SUITE-B" in auth else "WPA2-Enterprise"
        if "OWE" in auth:
            return "Enhanced Open (OWE)"
        return "WPA2-Personal"
    if re.search(r"^\s*WPA:", block, re.M):
        return "WPA (obsoleto)"
    cap = re.search(r"capability: ([^\n]*)", block)
    if cap and "Privacy" in cap.group(1):
        return "WEP (obsoleto)"
    return "Aperta"


def parse_nmcli(out):
    """Ripiego senza iw: meno dettagli (niente client per AP né occupazione del canale)."""
    aps = []
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 7:
            continue
        inuse, bssid, ssid, chan, freq, sig, sec = f[:7]
        try:
            pct = int(sig)
        except ValueError:
            continue
        fr = float(re.sub(r"[^\d.]", "", freq) or 0)
        aps.append({"bssid": bssid.lower(), "ssid": ssid, "freq": fr, "signal": round(pct / 2 - 100),
                    "channel": int(chan) if chan.isdigit() else channel_of(fr), "width": 20,
                    "security": (sec or "Aperta").replace("WPA2", "WPA2-Personal") if sec and sec != "--" else "Aperta",
                    "stations": None, "util": None, "std": "", "k": False, "v": False, "r": False,
                    "associated": inuse == "*", "age_ms": None})
    return aps


def scan(iface=IFACE):
    """Scansione degli AP visibili. Ritorna (lista AP, fonte, errore)."""
    if shutil.which("iw"):
        out, err = "", ""
        for _ in range(4):
            rc, out, err = run(["iw", "dev", iface, "scan"], 25)
            if rc == 0 and out.strip():
                return parse_iw_scan(out), "iw", ""
            if "busy" not in (err or "").lower():
                break
            time.sleep(1.5)
        rc, out, _ = run(["iw", "dev", iface, "scan", "dump"], 10)  # risultati della scansione più recente
        if rc == 0 and out.strip():
            return parse_iw_scan(out), "iw (cache)", ""
        if err and "down" in err.lower():
            return [], "iw", "Wi-Fi spento"
    rc, out, err = run(["nmcli", "-t", "-f", "IN-USE,BSSID,SSID,CHAN,FREQ,SIGNAL,SECURITY", "device", "wifi",
                        "list", "ifname", iface, "--rescan", "yes"], 35)
    if rc != 0:
        return [], "nmcli", (err or out).strip()[:120] or "Scansione non riuscita"
    return parse_nmcli(out), "nmcli", ""


def group_by_ssid(aps):
    nets = {}
    for ap in aps:
        nets.setdefault(ap["ssid"], []).append(ap)
    out = []
    for ssid, lst in nets.items():
        lst.sort(key=lambda a: -(a["signal"] if a["signal"] is not None else -200))
        out.append({"ssid": ssid, "aps": lst, "best": lst[0]["signal"], "bands": sorted({band_of(a["freq"]) for a in lst}),
                    "security": lst[0]["security"], "associated": any(a["associated"] for a in lst)})
    out.sort(key=lambda n: (not n["associated"], -(n["best"] if n["best"] is not None else -200)))
    return out


def channel_usage(aps):
    """{banda: {canale: [ap...]}} per il grafico di occupazione."""
    use = {}
    for ap in aps:
        use.setdefault(band_of(ap["freq"]), {}).setdefault(ap["channel"], []).append(ap)
    return use


def analyze(aps, link):
    """Avvisi leggibili sulla situazione Wi-Fi."""
    hints = []
    if link and link.get("connected"):
        same = [a for a in aps if a["ssid"] == link["ssid"] and a["signal"] is not None]
        cur = next((a for a in same if a["bssid"] == link["bssid"]), None)
        cur_sig = link.get("signal") if link.get("signal") is not None else (cur or {}).get("signal")
        better = [a for a in same if a["bssid"] != link["bssid"] and cur_sig is not None and a["signal"] >= cur_sig + 10]
        if better:
            b = max(better, key=lambda a: a["signal"])
            hints.append(f"Collegato a un AP a {cur_sig:.0f} dBm ma {b['bssid']} (canale {b['channel']}) è a "
                         f"{b['signal']:.0f} dBm: il dispositivo non passa all'AP migliore (roaming)")
        if cur_sig is not None and cur_sig < -70:
            hints.append(f"Segnale debole ({cur_sig:.0f} dBm): sotto -67 dBm voce e video possono avere problemi")
        bands = {band_of(a["freq"]) for a in same}
        if bands == {"2,4 GHz"}:
            hints.append(f"La rete {link['ssid']} è solo a 2,4 GHz: più lenta e più disturbata")
        if cur and cur["util"] is not None and cur["util"] >= 50:
            hints.append(f"Canale dell'AP occupato al {cur['util']}%: rete congestionata")
        if cur and cur["stations"] is not None and cur["stations"] >= 30:
            hints.append(f"L'AP ha {cur['stations']} client collegati")
    odd = sorted({a["channel"] for a in aps if band_of(a["freq"]) == "2,4 GHz" and a["channel"] not in (1, 6, 11)
                  and (a["signal"] or -100) > -80})
    if odd:
        hints.append("A 2,4 GHz ci sono AP sui canali " + ", ".join(map(str, odd)) +
                     ": si sovrappongono a 1/6/11 e creano interferenza")
    for band, chans in channel_usage(aps).items():
        for ch, lst in chans.items():
            strong = [a for a in lst if (a["signal"] or -100) > -75]
            if len(strong) >= 4:
                hints.append(f"Canale {ch} ({band}) affollato: {len(strong)} AP con segnale forte")
    weak_sec = sorted({a["ssid"] or "(nascosta)" for a in aps if a["security"].startswith(("WEP", "WPA ("))})
    if weak_sec:
        hints.append("Reti con sicurezza obsoleta: " + ", ".join(weak_sec[:4]))
    return hints


# ========================================================== collegamento
def link_info(iface=IFACE):
    """Stato del collegamento attuale da `iw dev wlan0 link` e `station dump`."""
    info = {"connected": False, "ssid": "", "bssid": "", "freq": 0.0, "channel": 0, "signal": None,
            "rx_rate": "", "tx_rate": "", "tx_retries": None, "tx_failed": None, "beacon_loss": None,
            "connected_time": None, "signal_avg": None}
    if shutil.which("iw"):
        rc, out, _ = run(["iw", "dev", iface, "link"], 5)
        m = re.search(r"Connected to ([0-9a-f:]{17})", out)
        if rc == 0 and m:
            info["connected"] = True
            info["bssid"] = m.group(1)
            for key, rx in (("ssid", r"SSID: (.*)"), ("rx_rate", r"rx bitrate: (.*)"), ("tx_rate", r"tx bitrate: (.*)")):
                g = re.search(rx, out)
                if g:
                    info[key] = g.group(1).strip()
            g = re.search(r"freq: ([\d.]+)", out)
            if g:
                info["freq"] = float(g.group(1))
                info["channel"] = channel_of(info["freq"])
            g = re.search(r"signal: (-?\d+) dBm", out)
            if g:
                info["signal"] = float(g.group(1))
            rc, out, _ = run(["iw", "dev", iface, "station", "dump"], 5)
            for key, rx in (("tx_retries", r"tx retries:\s*(\d+)"), ("tx_failed", r"tx failed:\s*(\d+)"),
                            ("beacon_loss", r"beacon loss:\s*(\d+)"), ("connected_time", r"connected time:\s*(\d+)"),
                            ("signal_avg", r"signal avg:\s*(-?\d+)")):
                g = re.search(rx, out)
                if g:
                    info[key] = int(g.group(1))
            return info
    rc, out, _ = run(["nmcli", "-t", "-f", "IN-USE,BSSID,SSID,FREQ,SIGNAL,RATE", "device", "wifi", "list",
                      "ifname", iface, "--rescan", "no"], 10)
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) >= 6 and f[0] == "*":
            fr = float(re.sub(r"[^\d.]", "", f[3]) or 0)
            info.update(connected=True, bssid=f[1].lower(), ssid=f[2], freq=fr, channel=channel_of(fr),
                        signal=round(int(f[4]) / 2 - 100) if f[4].isdigit() else None, tx_rate=f[5])
    return info


def short_rate(rate):
    """'433.3 MBit/s VHT-MCS 9 80MHz short GI VHT-NSS 1' -> '433 Mbit/s · 80 MHz · 1 flusso'."""
    if not rate:
        return "—"
    m = re.match(r"([\d.]+) MBit/s", rate)
    parts = [f"{float(m.group(1)):.0f} Mbit/s"] if m else [rate.split()[0]]
    w = re.search(r"(\d+)MHz", rate)
    if w:
        parts.append(f"{w.group(1)} MHz")
    n = re.search(r"NSS (\d)", rate)
    if n:
        parts.append("1 flusso" if n.group(1) == "1" else f"{n.group(1)} flussi")
    return " · ".join(parts)
