"""Disco FAT in un file immagine, senza mount né comandi esterni.

Serve alla Tastiera Rapida: il PC vede l'immagine come una chiavetta (USB mass storage) e ci copia i file;
il Pi poi li legge e li cancella direttamente dall'immagine, quando il PC non la sta usando.

- format_fat16(path, mb, label): crea un'immagine FAT16 senza tabella delle partizioni ("superfloppy").
- list_files(path): file nella cartella principale (con i nomi lunghi), per FAT16 e FAT32.
- read_file(path, entry) / delete_file(path, entry).
"""
import os
import random
import struct

SECTOR = 512


# ================================================================ formattazione
def format_fat16(path, mb=64, label="TASTIERA"):
    total = mb * 1024 * 1024 // SECTOR
    spc = 4 if mb <= 128 else 8 if mb <= 256 else 16
    reserved, nfats, root_entries = 1, 2, 512
    root_sectors = root_entries * 32 // SECTOR
    fat = 1
    for _ in range(10):
        data = total - reserved - nfats * fat - root_sectors
        clusters = data // spc
        need = ((clusters + 2) * 2 + SECTOR - 1) // SECTOR
        if need == fat:
            break
        fat = need
    if not 4085 <= clusters < 65525:
        raise ValueError("Dimensione non adatta a FAT16")
    lab = label.upper().encode("ascii", "replace")[:11].ljust(11)
    bs = bytearray(SECTOR)
    bs[0:3] = b"\xEB\x3C\x90"
    bs[3:11] = b"MSWIN4.1"
    struct.pack_into("<HBHBHHBHHHII", bs, 11, SECTOR, spc, reserved, nfats, root_entries,
                     0 if total > 0xFFFF else total, 0xF8, fat, 32, 64, 0, total if total > 0xFFFF else 0)
    struct.pack_into("<BBBI", bs, 36, 0x80, 0, 0x29, random.randint(0, 0xFFFFFFFF))
    bs[43:54] = lab
    bs[54:62] = b"FAT16   "
    bs[510:512] = b"\x55\xAA"
    with open(path, "wb") as f:
        f.truncate(total * SECTOR)
        f.write(bs)
        fat_sec = bytearray(fat * SECTOR)
        struct.pack_into("<HH", fat_sec, 0, 0xFFF8, 0xFFFF)
        for i in range(nfats):
            f.seek((reserved + i * fat) * SECTOR)
            f.write(fat_sec)
        root = bytearray(root_sectors * SECTOR)
        root[0:11] = lab
        root[11] = 0x08  # etichetta del volume
        f.seek((reserved + nfats * fat) * SECTOR)
        f.write(root)
    os.chmod(path, 0o600)


# ===================================================================== lettura
class _Fs:
    def __init__(self, f):
        self.f = f
        f.seek(0)
        bs = f.read(SECTOR)
        if bs[510:512] != b"\x55\xAA":
            raise ValueError("Immagine non valida")
        (self.bps, self.spc, self.reserved, self.nfats, self.root_entries, t16, _media, f16, _spt, _heads,
         _hidden, t32) = struct.unpack_from("<HBHBHHBHHHII", bs, 11)
        self.fat_size = f16 or struct.unpack_from("<I", bs, 36)[0]
        total = t16 or t32
        self.root_sectors = (self.root_entries * 32 + self.bps - 1) // self.bps
        self.fat_start = self.reserved
        self.root_start = self.reserved + self.nfats * self.fat_size
        self.data_start = self.root_start + self.root_sectors
        clusters = (total - self.data_start) // self.spc
        if clusters < 4085:
            raise ValueError("FAT12 non supportata")
        self.fat32 = clusters >= 65525
        self.root_cluster = struct.unpack_from("<I", bs, 44)[0] if self.fat32 else None
        self.csize = self.spc * self.bps

    def fat_get(self, c):
        if self.fat32:
            self.f.seek(self.fat_start * self.bps + c * 4)
            return struct.unpack("<I", self.f.read(4))[0] & 0x0FFFFFFF
        self.f.seek(self.fat_start * self.bps + c * 2)
        return struct.unpack("<H", self.f.read(2))[0]

    def fat_set(self, c, v):
        for i in range(self.nfats):
            base = (self.fat_start + i * self.fat_size) * self.bps
            if self.fat32:
                self.f.seek(base + c * 4)
                old = struct.unpack("<I", self.f.read(4))[0]
                self.f.seek(base + c * 4)
                self.f.write(struct.pack("<I", (old & 0xF0000000) | v))
            else:
                self.f.seek(base + c * 2)
                self.f.write(struct.pack("<H", v))

    def is_end(self, v):
        return v >= (0x0FFFFFF8 if self.fat32 else 0xFFF8) or v < 2

    def chain(self, c):
        out, seen = [], set()
        while c >= 2 and not self.is_end(c) and c not in seen and len(out) < 1_000_000:
            out.append(c)
            seen.add(c)
            c = self.fat_get(c)
        return out

    def cluster_off(self, c):
        return (self.data_start + (c - 2) * self.spc) * self.bps

    def root_slots(self):
        """Offset assoluti di ogni voce da 32 byte della cartella principale."""
        if not self.fat32:
            start = self.root_start * self.bps
            return [start + i * 32 for i in range(self.root_entries)]
        slots = []
        for c in self.chain(self.root_cluster):
            base = self.cluster_off(c)
            slots += [base + i * 32 for i in range(self.csize // 32)]
        return slots


def _lfn_part(e):
    raw = e[1:11] + e[14:26] + e[28:32]
    s = raw.decode("utf-16-le", "replace")
    return s.split("\x00")[0].replace("￿", "")


def list_files(path):
    """File nella cartella principale: [{name, size, cluster, slots}]."""
    out = []
    with open(path, "rb") as f:
        fs = _Fs(f)
        lfn, lfn_slots = [], []
        for off in fs.root_slots():
            f.seek(off)
            e = f.read(32)
            if e[0] == 0x00:
                break
            if e[0] == 0xE5:
                lfn, lfn_slots = [], []
                continue
            attr = e[11]
            if attr == 0x0F:
                if e[0] & 0x40:
                    lfn, lfn_slots = [], []
                lfn.insert(0, _lfn_part(e))
                lfn_slots.append(off)
                continue
            if attr & 0x18:  # cartella o etichetta del volume
                lfn, lfn_slots = [], []
                continue
            base = e[0:8].decode("ascii", "replace").rstrip()
            ext = e[8:11].decode("ascii", "replace").rstrip()
            short = base + ("." + ext if ext else "")
            name = "".join(lfn) or short
            cl = struct.unpack_from("<H", e, 26)[0] | (struct.unpack_from("<H", e, 20)[0] << 16 if fs.fat32 else 0)
            out.append({"name": name, "size": struct.unpack_from("<I", e, 28)[0], "cluster": cl,
                        "slots": lfn_slots + [off], "hidden": bool(attr & 0x02 or attr & 0x04)})
            lfn, lfn_slots = [], []
    return out


def read_file(path, entry, limit=256 * 1024):
    with open(path, "rb") as f:
        fs = _Fs(f)
        left = min(entry["size"], limit)
        data = bytearray()
        for c in fs.chain(entry["cluster"]):
            if left <= 0:
                break
            f.seek(fs.cluster_off(c))
            chunk = f.read(min(fs.csize, left))
            data += chunk
            left -= len(chunk)
        return bytes(data)


def delete_file(path, entry):
    """Cancella il file: segna le voci come libere, libera i cluster e azzera il contenuto."""
    with open(path, "r+b") as f:
        fs = _Fs(f)
        for c in fs.chain(entry["cluster"]):
            f.seek(fs.cluster_off(c))
            f.write(bytes(fs.csize))  # il testo non resta leggibile nell'immagine
            fs.fat_set(c, 0)
        for off in entry["slots"]:
            f.seek(off)
            f.write(b"\xE5")
        f.flush()
        os.fsync(f.fileno())


def decode_text(data):
    """Testo da file creati con Blocco note & co.: UTF-8 (con o senza BOM), UTF-16, Windows-1252."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")
