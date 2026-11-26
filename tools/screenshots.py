#!/usr/bin/env python3
"""Regenerates the README screenshots by rendering the real launcher screens off-screen with sample data.

    python3 tools/screenshots.py            # writes docs/screenshots/*.png

Needs pygame and the DejaVu fonts. No Raspberry Pi, touch screen or network is required: every system call
used by the screens is replaced with fixed sample values below.
"""
import os
import sys
import tempfile
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "pilauncher")
OUT = os.path.join(ROOT, "docs", "screenshots")
sys.path.insert(0, APP_DIR)

import pygame  # noqa: E402

pygame.display.init()
pygame.font.init()

from core import netdiag as nd  # noqa: E402
from core import system as sysm  # noqa: E402
from core import wifidiag as wd  # noqa: E402
from core import framework  # noqa: E402

# ------------------------------------------------------------------ sample data
nd.carrier = lambda iface="eth0": True
nd.iface_present = lambda iface="eth0": True
nd.link_info = lambda iface="eth0": {
    "present": True, "carrier": True, "mac": "dc:a6:32:00:00:01", "speed": 1000, "duplex": "full", "flaps": 1,
    "rx_crc": 0, "rx_err": 0, "tx_err": 0, "our_max": 1000, "partner_max": 1000, "autoneg": "on"}
nd.ip_info = lambda iface="eth0": {
    "addr": "10.20.4.37", "prefix": 24, "dynamic": True, "lease_left": 80000, "gateway": "10.20.4.1",
    "dns": ["10.20.1.10", "10.20.1.11"], "domain": "example.local", "dhcp_server": "10.20.1.5",
    "lease_time": 86400, "nm_state": "100 (connected)"}
nd.arp_duplicate = lambda *a, **k: None
nd.dhcp_probe = lambda *a, **k: {"sent": 2, "frames": 40, "senders": 5, "link_lost": False, "offers": [{
    "server": "10.20.1.5", "src_ip": "10.20.4.1", "yiaddr": "10.20.4.37", "giaddr": "10.20.4.1", "opt82": True,
    "ntp": ["10.20.1.10"], "tftp": None, "tftp_ips": ["10.20.9.9"], "wpad": None, "domain": "example.local",
    "router": "10.20.4.1", "dns": [], "type": "OFFER"}]}


def _dns(server, name, qtype="A", *a, **k):
    if qtype == "PTR":
        return {"ok": True, "answers": ["tester.example.local"], "ms": 3, "error": ""}
    if qtype == "SRV":
        return {"ok": True, "answers": ["dc1.example.local:389", "dc2.example.local:389"], "ms": 3, "error": ""}
    if name.startswith("wpad"):
        return {"ok": False, "answers": [], "ms": 3, "error": "Nome inesistente"}
    return {"ok": True, "answers": ["10.20.1.20"], "ms": 4, "error": ""}


nd.dns_lookup = _dns
nd.dns_query = lambda *a, **k: {"ok": True, "ips": ["142.250.1.1"], "ms": 12, "error": ""}
nd.ipv6_info = lambda *a, **k: {"addrs": [], "router": None}
nd.ping = lambda host, count=5, *a, **k: {"ok": True, "sent": count, "recv": count, "loss": 0, "min": 0.9,
                                          "avg": 1.2, "max": 2.0, "error": ""}
nd.neighbor_mac = lambda *a, **k: "00:00:0c:9f:f0:01"
nd.path_mtu = lambda *a, **k: 1500
nd.http_check = lambda *a, **k: {"code": 204, "ms": 40, "error": ""}
nd.traceroute = lambda *a, **k: ([(1, "10.20.4.1"), (2, "10.20.0.1"), (3, None), (4, "8.8.8.8")], True)
nd.tcp_check = lambda ip, port, *a, **k: {"ok": port != 3389, "ms": 2,
                                          "error": "" if port != 3389 else "Nessuna risposta (filtrata?)"}
nd.ntp_offset = lambda *a, **k: 1.4

IW_SCAN = """BSS 00:11:22:33:44:01(on wlan0) -- associated
\tfreq: 2437.0
\tcapability: ESS Privacy ShortSlotTime (0x0411)
\tsignal: -71.00 dBm
\tSSID: Corp
\tBSS Load:
\t\t * station count: 12
\t\t * channel utilisation: 140/255
\tHT operation:
\t\t * primary channel: 6
\t\t * secondary channel offset: no secondary
\tRSN:\t * Version: 1
\t\t * Authentication suites: IEEE 802.1X FT/IEEE 802.1X
\tExtended capabilities:
\t\t * BSS Transition
\tRM enabled capabilities:
\t\tCapabilities: 0x73
BSS 00:11:22:33:44:02(on wlan0)
\tfreq: 5180.0
\tcapability: ESS Privacy (0x0111)
\tsignal: -52.00 dBm
\tSSID: Corp
\tBSS Load:
\t\t * station count: 3
\t\t * channel utilisation: 20/255
\tHT operation:
\t\t * secondary channel offset: above
\tVHT operation:
\t\t * channel width: 1 (80 MHz)
\tHE capabilities:
\tRSN:\t * Version: 1
\t\t * Authentication suites: IEEE 802.1X
BSS 00:11:22:33:44:03(on wlan0)
\tfreq: 5500.0
\tcapability: ESS Privacy (0x0111)
\tsignal: -66.00 dBm
\tSSID: Corp
\tVHT operation:
\t\t * channel width: 1 (80 MHz)
\tRSN:\t * Version: 1
\t\t * Authentication suites: IEEE 802.1X
BSS aa:bb:cc:00:00:01(on wlan0)
\tfreq: 2412.0
\tcapability: ESS Privacy (0x0011)
\tsignal: -63.00 dBm
\tSSID: Guest
\tRSN:\t * Version: 1
\t\t * Authentication suites: PSK SAE
BSS aa:bb:cc:00:00:02(on wlan0)
\tfreq: 5240.0
\tcapability: ESS Privacy (0x0011)
\tsignal: -58.00 dBm
\tSSID: Guest
\tRSN:\t * Version: 1
\t\t * Authentication suites: PSK SAE
BSS aa:bb:cc:00:00:03(on wlan0)
\tfreq: 2462.0
\tcapability: ESS Privacy (0x0011)
\tsignal: -77.00 dBm
\tSSID: Terminals
\tRSN:\t * Version: 1
\t\t * Authentication suites: PSK
"""
APS = wd.parse_iw_scan(IW_SCAN)
LINK = {"connected": True, "ssid": "Corp", "bssid": "00:11:22:33:44:01", "freq": 2437.0, "channel": 6,
        "signal": -71.0, "rx_rate": "72.2 MBit/s MCS 7 short GI", "tx_rate": "65.0 MBit/s MCS 7", "tx_retries": 120,
        "tx_failed": 3, "beacon_loss": 0, "connected_time": 300, "signal_avg": -70}
wd.scan = lambda iface="wlan0": (APS, "iw", "")
wd.link_info = lambda iface="wlan0": dict(LINK)
sysm.tz_current = lambda: "Europe/Rome"
framework.Manager._status_loop = lambda self: None   # no system polling


class _Display:
    size = (480, 320)


class _Updater:
    enabled, version, checked_at, error, confirmed = True, "v1.0.1", 1e12, "", True
    latest = {"tag": "v1.0.2", "notes": "* Tester rete: report, server aziendali\n* Nuovo Tester Wi-Fi",
              "tar": "", "sha": ""}

    def newer_available(self):
        return True

    def rolled_back(self):
        return ""


# ------------------------------------------------------------------ rendering
def main():
    from core.framework import Context, Manager
    from core.home import Home, discover_apps

    os.makedirs(OUT, exist_ok=True)
    data = tempfile.mkdtemp()
    ctx = Context(APP_DIR, data, _Display(), None, _Updater())
    ctx.config = {"rot": 90, "nettest": {"targets": [
        {"name": "File server", "host": "fs01.example.local", "ports": [445]},
        {"name": "ERP", "host": "10.20.1.30", "ports": [443, 3389]}]}}
    ctx.save_config = lambda: None
    mgr = Manager((480, 320), ctx)
    mgr.status = {"wifi": 3, "bt": True, "temp": 48.0, "update": True}
    mgr.apps = discover_apps(APP_DIR)
    surf = pygame.Surface((480, 320))

    def shot(name, screen, build=True):
        mgr.stack = [screen]
        if build:
            screen.build()
        mgr.toast_msg = None
        mgr.draw(surf)
        pygame.image.save(pygame.transform.scale(surf, (960, 640)), os.path.join(OUT, name + ".png"))
        print("  ", name)

    print("Screenshots in", OUT)
    shot("home", Home(mgr))

    from apps.settings import SettingsMain, UpdateScreen
    sm = SettingsMain(mgr)
    sm.wifi_sub, sm.bt_sub = "Connesso a Corp", "Acceso"
    shot("settings", sm)
    shot("updates", UpdateScreen(mgr))

    # Network tester: run the real check sequence on the sample data
    from apps.nettest.main import NetTest
    from apps.nettest.common import Detail
    from apps.nettest.ipconf import IpScreen
    from apps.nettest.tools import Tools
    from apps.nettest.targets import TargetsScreen
    from apps.nettest import report as rp
    nt = NetTest(mgr)
    mgr.stack = [nt]
    nt.enter()
    nt.diag.listener.close()
    nt.diag.listener.lldp = {"proto": "LLDP", "name": "SW-FLOOR2", "port": "Gi1/0/12", "port_desc": "Office 2 socket 14",
                             "vlan": 20, "voice_vlan": 30, "mgmt": "10.20.0.2", "desc": "Cisco IOS 15.2"}
    nt.diag.listener.stp = {"proto": "Rapid PVST+", "root_prio": 24576, "root_ext": 20, "root_mac": "00:11:22:aa:bb:cc",
                            "cost": 4, "bridge_prio": 32768, "bridge_mac": "00:11:22:33:44:ff", "port_id": "0x800c",
                            "tc": False, "is_root_port": False}
    for _ in range(100):
        time.sleep(0.1)
        if not nt.diag.running and nt.diag.get("svc")["st"] not in ("wait", "run"):
            break
    shot("nettest", nt)
    sw = nt.diag.get("switch")
    shot("nettest-switch", Detail(mgr, "Switch e porta", sw["rows"], sw["hints"]))
    ips = IpScreen(mgr, nt)
    ips.build()
    ips.widgets[0].offset = ips.widgets[0].max_offset()
    shot("nettest-ip", ips, build=False)
    shot("nettest-tools", Tools(mgr, nt))
    shot("nettest-servers", TargetsScreen(mgr, nt))
    short = rp.summary(mgr, nt.diag, "Office 2 socket 14")
    shot("nettest-qr", rp.QrScreen(mgr, rp.pages(short)), build=False)
    nt.diag.close()

    # Wi-Fi tester
    from apps.wifitest.main import WifiTest, Aps, Channels, Monitor
    wt = WifiTest(mgr)
    wt.aps, wt.link, wt.src = APS, dict(LINK), "iw"
    wt.hints = wd.analyze(APS, LINK)
    wt.scanned_at = time.time()
    shot("wifitest", wt)
    shot("wifitest-aps", Aps(mgr, wd.group_by_ssid(APS)[0], LINK))
    shot("wifitest-channels", Channels(mgr, APS))
    mon = Monitor(mgr, wt)
    t0 = time.time() - 140
    sig = [-58 - (i % 20) // 2 for i in range(60)] + [-70 - (i % 6) for i in range(40)] + \
          [-55 + (i % 5) for i in range(40)]
    for i, v in enumerate(sig):
        bssid = "00:11:22:33:44:01" if 60 <= i < 100 else "00:11:22:33:44:02"
        mon.samples.append((t0 + i, v, bssid, False if i in (97, 98) else 1.5))
    mon.events = [(t0 + 60, "Roaming 33:44:02 → 33:44:01 (canale 6, -70 dBm)"),
                  (t0 + 100, "Roaming 33:44:01 → 33:44:02 (canale 36, -55 dBm)")]
    shot("wifitest-monitor", mon)


if __name__ == "__main__":
    main()
