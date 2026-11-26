"""Aggiornamenti OTA dalle release GitHub.

Struttura sul Pi (creata da install.sh):
    /opt/pilauncher/
        current -> releases/v1.0.3     (link simbolico alla versione in uso)
        releases/v1.0.2, v1.0.3        (si tengono la versione attuale e la precedente)
        data/                          (config.json, calib.json: sopravvivono agli aggiornamenti)
        guard.sh                       (lanciato da systemd prima di ogni avvio: fa il rollback)

Dopo un aggiornamento viene scritto data/pending con la versione precedente. Se la nuova
versione resta avviata per CONFIRM_AFTER secondi il file viene cancellato; se invece si
blocca e systemd la riavvia più di 3 volte, guard.sh torna alla versione precedente.
"""
import hashlib
import json
import os
import py_compile
import shutil
import tarfile
import tempfile
import time
import urllib.request

REPO = "raxp122/RaspberryPi4Gadget"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
CONFIRM_AFTER = 30
UA = "PiLauncher-updater"


def parse_version(v):
    """'v1.2.3' -> (1, 2, 3). Versioni di sviluppo ('dev', '1.0') -> (0,)."""
    v = (v or "").strip()
    if not v.startswith("v"):
        return (0,)
    try:
        return tuple(int(x) for x in v[1:].split("."))
    except ValueError:
        return (0,)


class Updater:
    def __init__(self, app_dir, data_dir):
        self.app_dir, self.data_dir = app_dir, data_dir
        real = os.path.realpath(app_dir)
        parent = os.path.dirname(real)
        # aggiornamenti possibili solo nell'installazione OTA (…/releases/<versione>)
        self.base = os.path.dirname(parent) if os.path.basename(parent) == "releases" else None
        self.version = self._read(os.path.join(app_dir, "VERSION")) or "dev"
        if self.base is None and not self.version.startswith("v"):
            self.version = "dev"
        self.latest = None      # dict della release più recente (dopo check)
        self.checked_at = 0
        self.error = ""
        self.confirmed = False

    @property
    def enabled(self):
        return self.base is not None

    @staticmethod
    def _read(path):
        try:
            with open(path) as f:
                return f.read().strip()
        except OSError:
            return ""

    # ------------------------------------------------------------ controllo
    def check(self):
        """Interroga GitHub. Ritorna la release (dict) se più nuova di quella in uso, altrimenti None."""
        req = urllib.request.Request(API_LATEST, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.load(r)
        except Exception as e:  # noqa: BLE001
            self.error = _net_error(e)
            raise RuntimeError(self.error) from e
        tag = data.get("tag_name", "")
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
        tar_name = f"pilauncher-{tag}.tar.gz"
        if tar_name not in assets or tar_name + ".sha256" not in assets:
            raise RuntimeError(f"La release {tag} non contiene il pacchetto")
        self.latest = {"tag": tag, "notes": (data.get("body") or "").strip(),
                       "tar": assets[tar_name], "sha": assets[tar_name + ".sha256"]}
        self.checked_at, self.error = time.time(), ""
        return self.latest if self.newer_available() else None

    def newer_available(self):
        return bool(self.latest) and parse_version(self.latest["tag"]) > parse_version(self.version)

    def rolled_back(self):
        """Versione scartata da guard.sh perché non partiva, se c'è."""
        return self._read(os.path.join(self.data_dir, "rolled_back"))

    # ---------------------------------------------------------- installazione
    def install(self, progress=None):
        """Scarica, verifica e attiva self.latest. Dopo serve riavviare il launcher."""
        if not self.enabled:
            raise RuntimeError("Installazione di sviluppo: aggiornamenti disattivati")
        rel = self.latest
        tag = rel["tag"]
        releases = os.path.join(self.base, "releases")
        os.makedirs(releases, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=".dl-", dir=releases)
        try:
            tar_path = os.path.join(tmp, "pkg.tar.gz")
            _download(rel["tar"], tar_path, progress)
            expected = _fetch_text(rel["sha"]).split()[0].lower()
            if _sha256(tar_path) != expected:
                raise RuntimeError("Pacchetto corrotto (checksum diverso)")
            if progress:
                progress("Estrazione…")
            out = os.path.join(tmp, "pkg")
            os.makedirs(out)
            with tarfile.open(tar_path) as tf:
                _safe_extract(tf, out)
            if not os.path.isfile(os.path.join(out, "main.py")):
                raise RuntimeError("Pacchetto non valido (manca main.py)")
            for root, _, files in os.walk(out):
                for f in files:
                    if f.endswith(".py"):
                        py_compile.compile(os.path.join(root, f), doraise=True)
            dest = os.path.join(releases, tag)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            os.rename(out, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        prev = os.path.basename(os.path.realpath(os.path.join(self.base, "current")))
        _write(os.path.join(self.data_dir, "pending"), prev)
        for f in ("pending_tries", "rolled_back"):
            _remove(os.path.join(self.data_dir, f))
        _symlink_atomic(os.path.join("releases", tag), os.path.join(self.base, "current"))
        self._cleanup(keep={tag, prev})
        return tag

    def _cleanup(self, keep):
        releases = os.path.join(self.base, "releases")
        for name in os.listdir(releases):
            if name not in keep and not name.startswith("."):
                shutil.rmtree(os.path.join(releases, name), ignore_errors=True)

    # ---------------------------------------------------------- conferma
    def confirm(self):
        """Chiamato dopo CONFIRM_AFTER secondi di funzionamento: la versione in uso è buona."""
        self.confirmed = True
        if not self.enabled:
            return
        pending = os.path.join(self.data_dir, "pending")
        if os.path.exists(pending):
            _remove(pending)
            _remove(os.path.join(self.data_dir, "pending_tries"))
            print(f"[updater] versione {self.version} confermata", flush=True)
        # aggiorna guard.sh con quello della versione appena confermata
        src, dst = os.path.join(self.app_dir, "guard.sh"), os.path.join(self.base, "guard.sh")
        if os.path.isfile(src) and self._read(src) != self._read(dst):
            shutil.copyfile(src, dst + ".tmp")
            os.replace(dst + ".tmp", dst)


# ---------------------------------------------------------------- helper
def _net_error(e):
    msg = str(getattr(e, "reason", e))
    if "Name or service" in msg or "Temporary failure" in msg or "Network is unreachable" in msg:
        return "Nessuna connessione a Internet"
    if getattr(e, "code", None) == 404:
        return "Nessuna release pubblicata"
    if getattr(e, "code", None) == 403:
        return "GitHub ha limitato le richieste, riprova più tardi"
    return f"Controllo non riuscito: {msg}"


def _fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def _download(url, path, progress=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -1
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                pct = done * 100 // total
                if pct != last:
                    last = pct
                    progress(f"Download… {pct}%")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_extract(tf, out):
    if hasattr(tarfile, "data_filter"):
        tf.extractall(out, filter="data")
        return
    root = os.path.realpath(out)
    for m in tf.getmembers():
        target = os.path.realpath(os.path.join(out, m.name))
        if not (target == root or target.startswith(root + os.sep)) or m.issym() or m.islnk() or m.isdev():
            raise RuntimeError(f"Percorso non valido nel pacchetto: {m.name}")
    tf.extractall(out)


def _symlink_atomic(target, link):
    tmp = link + ".new"
    _remove(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, link)


def _write(path, s):
    with open(path + ".tmp", "w") as f:
        f.write(s + "\n")
    os.replace(path + ".tmp", path)


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
