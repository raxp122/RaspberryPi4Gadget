"""Comandi di sistema: Wi-Fi (nmcli), Bluetooth (bluetoothctl), info, data/ora, alimentazione."""
import os
import re
import shutil
import subprocess

WIFI_IF = "wlan0"
CONFIG_TXT = "/boot/firmware/config.txt"


def run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"comando non trovato: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def split_terse(line):
    """Divide una riga di `nmcli -t` sui ':' non preceduti da '\\'."""
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


# ------------------------------------------------------------------ Wi-Fi
def wifi_radio():
    _, out, _ = run(["nmcli", "radio", "wifi"], 5)
    return out.strip() == "enabled"


def wifi_set_radio(on):
    rc, _, err = run(["nmcli", "radio", "wifi", "on" if on else "off"], 10)
    return rc == 0, err.strip()


def wifi_status():
    _, out, _ = run(["nmcli", "-g", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS", "device", "show", WIFI_IF], 5)
    lines = out.splitlines() + ["", "", ""]
    state, conn, ip = lines[0], lines[1], lines[2].split(" | ")[0].split("/")[0]
    return {"connected": state.startswith("100"), "connection": conn, "ip": ip}


def wifi_saved():
    """{ssid: nome_connessione} per le reti salvate."""
    _, out, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], 5)
    saved = {}
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) >= 2 and f[1] == "802-11-wireless":
            _, ssid, _ = run(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", f[0]], 5)
            ssid = split_terse(ssid.strip())[0] if ssid.strip() else f[0]
            saved[ssid] = f[0]
    return saved


def wifi_scan(rescan=True):
    rc, out, err = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                        "--rescan", "yes" if rescan else "no"], 35)
    nets = {}
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 4 or not f[1]:
            continue
        try:
            sig = int(f[2])
        except ValueError:
            sig = 0
        sec = "" if f[3] in ("", "--") else f[3]
        n = nets.setdefault(f[1], {"ssid": f[1], "signal": 0, "security": sec, "inuse": False})
        n["inuse"] |= f[0] == "*"
        if sig > n["signal"]:
            n["signal"], n["security"] = sig, sec
    nets = sorted(nets.values(), key=lambda n: (not n["inuse"], -n["signal"]))
    return nets, (err.strip() if rc else "")


def _nm_error(text):
    t = text.lower()
    if "secrets were required" in t or "802-1x" in t or "password" in t and "invalid" in t:
        return "Password errata o rete non raggiungibile"
    if "no network with ssid" in t:
        return "Rete non trovata"
    if "timeout" in t:
        return "Tempo scaduto"
    return text.strip().replace("Error: ", "")[:160] or "Errore sconosciuto"


def wifi_connect(ssid, password=None, already_saved=False):
    cmd = ["nmcli", "--wait", "30", "device", "wifi", "connect", ssid, "ifname", WIFI_IF]
    if password:
        cmd += ["password", password]
    rc, out, err = run(cmd, 45)
    if rc != 0 and not already_saved:
        run(["nmcli", "connection", "delete", "id", ssid], 10)  # non lasciare profili rotti
    return rc == 0, "" if rc == 0 else _nm_error(err or out)


def wifi_up(name):
    rc, out, err = run(["nmcli", "--wait", "30", "connection", "up", "id", name], 45)
    return rc == 0, "" if rc == 0 else _nm_error(err or out)


def wifi_disconnect():
    rc, _, err = run(["nmcli", "device", "disconnect", WIFI_IF], 15)
    return rc == 0, err.strip()


def wifi_forget(name):
    rc, _, err = run(["nmcli", "connection", "delete", "id", name], 15)
    return rc == 0, err.strip()


def wifi_quick():
    """Livello 0..4 del segnale se connesso, None se non connesso. Economico: niente nmcli."""
    try:
        if open(f"/sys/class/net/{WIFI_IF}/operstate").read().strip() != "up":
            return None
        for line in open("/proc/net/wireless"):
            if line.strip().startswith(WIFI_IF + ":"):
                q = float(line.split()[2].rstrip("."))
                pct = q * 100 / 70
                return 1 if pct < 30 else 2 if pct < 55 else 3 if pct < 75 else 4
        return 3
    except (OSError, ValueError, IndexError):
        return None


# -------------------------------------------------------------- Bluetooth
_DEV_RE = re.compile(r"^Device ([0-9A-F:]{17})\s?(.*)$", re.I)


def bt_powered():
    rc, out, _ = run(["bluetoothctl", "show"], 6)
    return "Powered: yes" in out, rc == 0 and "Controller" in out


def bt_set_power(on):
    if on:
        run(["rfkill", "unblock", "bluetooth"], 5)
    rc, out, err = run(["bluetoothctl", "power", "on" if on else "off"], 10)
    ok = "succeeded" in out or rc == 0
    return ok, (err or out).strip()


def _bt_devices(kind=None):
    _, out, _ = run(["bluetoothctl", "devices"] + ([kind] if kind else []), 6)
    res = {}
    for line in out.splitlines():
        m = _DEV_RE.match(line.strip())
        if m:
            res[m.group(1).upper()] = m.group(2).strip()
    return res


def bt_list():
    alld, paired, conn = _bt_devices(), _bt_devices("Paired"), _bt_devices("Connected")
    devs = []
    for mac, name in alld.items():
        unnamed = not name or name.replace("-", ":").upper() == mac
        devs.append({"mac": mac, "name": "Senza nome" if unnamed else name, "unnamed": unnamed,
                     "paired": mac in paired, "connected": mac in conn})
    devs.sort(key=lambda d: (not d["connected"], not d["paired"], d["unnamed"], d["name"].lower()))
    return devs


def bt_scan(secs=10):
    run(["bluetoothctl", "--timeout", str(secs), "scan", "on"], secs + 8)
    return bt_list()


def bt_pair_connect(mac):
    _, out, err = run(["bluetoothctl", "--agent", "NoInputNoOutput", "--timeout", "25", "pair", mac], 35)
    txt = out + err
    if "successful" not in txt.lower() and "AlreadyExists" not in txt:
        return False, "Associazione non riuscita (il dispositivo e' in modalita' abbinamento?)"
    run(["bluetoothctl", "trust", mac], 8)
    return bt_connect(mac)


def bt_connect(mac):
    _, out, err = run(["bluetoothctl", "--timeout", "20", "connect", mac], 30)
    ok = "successful" in (out + err).lower()
    return ok, "" if ok else "Connessione non riuscita"


def bt_disconnect(mac):
    rc, out, _ = run(["bluetoothctl", "disconnect", mac], 15)
    return "Successful" in out or rc == 0, ""


def bt_remove(mac):
    rc, out, _ = run(["bluetoothctl", "remove", mac], 15)
    return "removed" in out.lower() or rc == 0, ""


# ------------------------------------------------------------------ Sistema
def cpu_temp():
    try:
        return int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except (OSError, ValueError):
        return None


def mem_info():
    vals = {}
    try:
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            vals[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        return None
    return vals.get("MemTotal", 0), vals.get("MemAvailable", 0)


def disk_info(path="/"):
    try:
        u = shutil.disk_usage(path)
        return u.total, u.used
    except OSError:
        return None


def uptime():
    try:
        return float(open("/proc/uptime").read().split()[0])
    except (OSError, ValueError):
        return None


def os_name():
    try:
        for line in open("/etc/os-release"):
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "?"


def kernel():
    return os.uname().release


def hostname():
    return os.uname().nodename


def ip_addresses():
    _, out, _ = run(["hostname", "-I"], 5)
    return [a for a in out.split() if ":" not in a] or out.split()


def throttled():
    rc, out, _ = run(["vcgencmd", "get_throttled"], 5)
    m = re.search(r"0x([0-9a-fA-F]+)", out)
    if rc != 0 or not m:
        return None
    v = int(m.group(1), 16)
    return {"value": v, "now_undervolt": bool(v & 0x1), "now_throttled": bool(v & 0x4),
            "past_undervolt": bool(v & 0x10000), "past_throttled": bool(v & 0x40000)}


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def human_duration(sec):
    sec = int(sec)
    d, h, m = sec // 86400, sec // 3600 % 24, sec // 60 % 60
    if d:
        return f"{d} g {h} h"
    if h:
        return f"{h} h {m} min"
    return f"{m} min"


# --------------------------------------------------------------- Data e ora
def tz_current():
    _, out, _ = run(["timedatectl", "show", "-p", "Timezone", "--value"], 5)
    return out.strip() or "?"


def tz_list():
    _, out, _ = run(["timedatectl", "list-timezones"], 10)
    return [l for l in out.splitlines() if l.strip()]


def tz_set(tz):
    rc, _, err = run(["timedatectl", "set-timezone", tz], 10)
    os.environ["TZ"] = tz
    try:
        import time
        time.tzset()
    except AttributeError:
        pass
    return rc == 0, err.strip()


def ntp_synced():
    _, out, _ = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], 5)
    return out.strip() == "yes"


# ---------------------------------------------------------- Schermo (SPI)
_SPEED_RE = re.compile(r"^(dtoverlay=piscreen[^\n]*?speed=)(\d+)", re.M)


def spi_speed_get():
    try:
        m = _SPEED_RE.search(open(CONFIG_TXT).read())
        return int(m.group(2)) if m else None
    except OSError:
        return None


def spi_speed_set(hz):
    txt = open(CONFIG_TXT).read()
    if not _SPEED_RE.search(txt):
        return False, "Riga dtoverlay=piscreen non trovata in config.txt"
    shutil.copy2(CONFIG_TXT, CONFIG_TXT + ".pilauncher.bak")
    with open(CONFIG_TXT, "w") as f:
        f.write(_SPEED_RE.sub(lambda m: m.group(1) + str(hz), txt, count=1))
    return True, ""


# ------------------------------------------------------------ Alimentazione
def reboot():
    run(["systemctl", "reboot"], 10)


def poweroff():
    run(["systemctl", "poweroff"], 10)
