"""USB-C del Pi 4 in modalità dispositivo (gadget) tramite configfs: chiavetta oppure tastiera.

Serve l'overlay dwc2 in config.txt (enable_overlay) e un riavvio. Solo la porta USB-C può fare da dispositivo:
le quattro USB-A del Pi 4 sono solo host.
"""
import os
import shutil
import time

from .system import CONFIG_TXT, run

CFG = "/sys/kernel/config"
G = CFG + "/usb_gadget/pilauncher"
UDC_DIR = "/sys/class/udc"
HIDG = "/dev/hidg0"
OVERLAY = "dtoverlay=dwc2,dr_mode=peripheral"

# descrittore standard di una tastiera "boot protocol": funziona anche nel BIOS/UEFI e nella schermata di BitLocker
BOOT_KEYBOARD = bytes.fromhex(
    "05010906a101050719e029e715002501750195088102950175088103950575010508190129059102"
    "95017503910395067508150025650507190029658100c0")


# ================================================================ abilitazione
def overlay_enabled():
    try:
        txt = open(CONFIG_TXT).read()
    except OSError:
        return False
    return any(line.strip().startswith("dtoverlay=dwc2") for line in txt.splitlines()
               if not line.strip().startswith("#"))


def enable_overlay():
    """Aggiunge l'overlay dwc2 in fondo a config.txt (sotto [all]). Serve un riavvio."""
    if overlay_enabled():
        return True, ""
    try:
        shutil.copy2(CONFIG_TXT, CONFIG_TXT + ".pilauncher.bak")
        with open(CONFIG_TXT, "a") as f:
            f.write(f"\n# Tastiera Rapida: USB-C in modalità dispositivo\n[all]\n{OVERLAY}\n")
        return True, ""
    except OSError as e:
        return False, str(e)


def disable_overlay():
    try:
        lines = open(CONFIG_TXT).read().splitlines()
        out = [ln for ln in lines if not ln.strip().startswith("dtoverlay=dwc2")
               and ln.strip() != "# Tastiera Rapida: USB-C in modalità dispositivo"]
        shutil.copy2(CONFIG_TXT, CONFIG_TXT + ".pilauncher.bak")
        with open(CONFIG_TXT, "w") as f:
            f.write("\n".join(out) + "\n")
        return True, ""
    except OSError as e:
        return False, str(e)


def udc_name():
    try:
        names = os.listdir(UDC_DIR)
    except OSError:
        return None
    return names[0] if names else None


def status():
    """'ok' se si può usare, altrimenti il motivo: 'overlay' (manca in config.txt), 'reboot' (serve riavviare)."""
    if udc_name():
        return "ok"
    if not overlay_enabled():
        return "overlay"
    run(["modprobe", "dwc2"], 10)
    time.sleep(0.5)
    return "ok" if udc_name() else "reboot"


def host_state():
    """'configured' quando un PC ha riconosciuto il gadget, 'not attached' / 'default' / ... altrimenti."""
    u = udc_name()
    if not u:
        return "none"
    try:
        return open(f"{UDC_DIR}/{u}/state").read().strip()
    except OSError:
        return "?"


# ===================================================================== configfs
def _w(path, value):
    with open(path, "wb" if isinstance(value, bytes) else "w") as f:
        f.write(value)


def _prepare():
    run(["modprobe", "libcomposite"], 10)
    if not os.path.isdir(CFG + "/usb_gadget"):
        run(["mount", "-t", "configfs", "none", CFG], 10)
    if not os.path.isdir(CFG + "/usb_gadget"):
        raise RuntimeError("configfs non disponibile (manca libcomposite?)")


def stop():
    """Scollega e smonta il gadget (il PC lo vede sparire)."""
    if not os.path.isdir(G):
        return
    try:
        _w(G + "/UDC", "\n")
    except OSError:
        pass
    cdir = G + "/configs/c.1"
    if os.path.isdir(cdir):
        for name in os.listdir(cdir):
            p = os.path.join(cdir, name)
            if os.path.islink(p):
                os.unlink(p)
        for sub in ("strings/0x409",):
            if os.path.isdir(os.path.join(cdir, sub)):
                os.rmdir(os.path.join(cdir, sub))
        os.rmdir(cdir)
    fdir = G + "/functions"
    if os.path.isdir(fdir):
        for name in os.listdir(fdir):
            os.rmdir(os.path.join(fdir, name))
    if os.path.isdir(G + "/strings/0x409"):
        os.rmdir(G + "/strings/0x409")
    os.rmdir(G)


def start(mode, image=None):
    """mode 'storage' (chiavetta con l'immagine) o 'keyboard' (tastiera)."""
    _prepare()
    stop()
    udc = udc_name()
    if not udc:
        raise RuntimeError("Porta USB-C non in modalità dispositivo: abilita e riavvia")
    os.makedirs(G)
    _w(G + "/idVendor", "0x1d6b")       # Linux Foundation
    _w(G + "/idProduct", "0x0104")      # Multifunction Composite Gadget
    _w(G + "/bcdDevice", "0x0100")
    _w(G + "/bcdUSB", "0x0200")
    os.makedirs(G + "/strings/0x409")
    _w(G + "/strings/0x409/manufacturer", "PiLauncher")
    _w(G + "/strings/0x409/product", "Tastiera Rapida" if mode == "keyboard" else "Chiavetta Tastiera Rapida")
    _w(G + "/strings/0x409/serialnumber", "pilauncher-" + mode)
    os.makedirs(G + "/configs/c.1/strings/0x409")
    _w(G + "/configs/c.1/strings/0x409/configuration", mode)
    _w(G + "/configs/c.1/MaxPower", "250")
    if mode == "keyboard":
        fn = G + "/functions/hid.usb0"
        os.makedirs(fn)
        _w(fn + "/protocol", "1")
        _w(fn + "/subclass", "1")
        _w(fn + "/report_length", "8")
        _w(fn + "/report_desc", BOOT_KEYBOARD)
    else:
        fn = G + "/functions/mass_storage.usb0"
        os.makedirs(fn)
        _w(fn + "/stall", "1")
        _w(fn + "/lun.0/removable", "1")
        _w(fn + "/lun.0/ro", "0")
        _w(fn + "/lun.0/file", image)
    os.symlink(fn, G + "/configs/c.1/" + os.path.basename(fn))
    _w(G + "/UDC", udc)


def active_mode():
    try:
        funcs = os.listdir(G + "/functions")
    except OSError:
        return None
    if any(f.startswith("hid") for f in funcs):
        return "keyboard"
    if any(f.startswith("mass_storage") for f in funcs):
        return "storage"
    return None

