"""Testo -> rapporti di una tastiera USB (8 byte), con layout italiano o americano.

Il PC interpreta i tasti secondo il proprio layout: per scrivere "@" su un PC con tastiera italiana bisogna premere
AltGr+ò, su uno americano Shift+2. Le cifre della riga in alto sono uguali in entrambi i layout.
"""
import os
import re
import select
import time

LCTRL, LSHIFT, LALT, RALT = 0x01, 0x02, 0x04, 0x40
ENTER, TAB, SPACE = 0x28, 0x2B, 0x2C

_LETTERS = {chr(ord("a") + i): 0x04 + i for i in range(26)}
_DIGITS = {"1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22, "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26,
           "0": 0x27}


def _base():
    m = {" ": (0, SPACE), "\t": (0, TAB), "\n": (0, ENTER)}
    for c, k in _LETTERS.items():
        m[c] = (0, k)
        m[c.upper()] = (LSHIFT, k)
    for c, k in _DIGITS.items():
        m[c] = (0, k)
    return m


US = _base()
US.update({
    "!": (LSHIFT, 0x1E), "@": (LSHIFT, 0x1F), "#": (LSHIFT, 0x20), "$": (LSHIFT, 0x21), "%": (LSHIFT, 0x22),
    "^": (LSHIFT, 0x23), "&": (LSHIFT, 0x24), "*": (LSHIFT, 0x25), "(": (LSHIFT, 0x26), ")": (LSHIFT, 0x27),
    "-": (0, 0x2D), "_": (LSHIFT, 0x2D), "=": (0, 0x2E), "+": (LSHIFT, 0x2E), "[": (0, 0x2F), "{": (LSHIFT, 0x2F),
    "]": (0, 0x30), "}": (LSHIFT, 0x30), "\\": (0, 0x31), "|": (LSHIFT, 0x31), ";": (0, 0x33), ":": (LSHIFT, 0x33),
    "'": (0, 0x34), '"': (LSHIFT, 0x34), "`": (0, 0x35), "~": (LSHIFT, 0x35), ",": (0, 0x36), "<": (LSHIFT, 0x36),
    ".": (0, 0x37), ">": (LSHIFT, 0x37), "/": (0, 0x38), "?": (LSHIFT, 0x38),
})

IT = _base()
IT.update({
    "!": (LSHIFT, 0x1E), '"': (LSHIFT, 0x1F), "£": (LSHIFT, 0x20), "$": (LSHIFT, 0x21), "%": (LSHIFT, 0x22),
    "&": (LSHIFT, 0x23), "/": (LSHIFT, 0x24), "(": (LSHIFT, 0x25), ")": (LSHIFT, 0x26), "=": (LSHIFT, 0x27),
    "'": (0, 0x2D), "?": (LSHIFT, 0x2D), "ì": (0, 0x2E), "^": (LSHIFT, 0x2E),
    "è": (0, 0x2F), "é": (LSHIFT, 0x2F), "[": (RALT, 0x2F), "{": (RALT | LSHIFT, 0x2F),
    "+": (0, 0x30), "*": (LSHIFT, 0x30), "]": (RALT, 0x30), "}": (RALT | LSHIFT, 0x30),
    "ò": (0, 0x33), "ç": (LSHIFT, 0x33), "@": (RALT, 0x33),
    "à": (0, 0x34), "°": (LSHIFT, 0x34), "#": (RALT, 0x34),
    "ù": (0, 0x31), "§": (LSHIFT, 0x31), "\\": (0, 0x35), "|": (LSHIFT, 0x35),
    ",": (0, 0x36), ";": (LSHIFT, 0x36), ".": (0, 0x37), ":": (LSHIFT, 0x37), "-": (0, 0x38), "_": (LSHIFT, 0x38),
    "<": (0, 0x64), ">": (LSHIFT, 0x64), "€": (RALT, 0x08),
})

LAYOUTS = {"IT": IT, "US": US}

_BITLOCKER = re.compile(r"^\s*(\d{6}\s*-?\s*){7}\d{6}\s*$")


def is_bitlocker(text):
    """Chiave di ripristino BitLocker: 48 cifre in 8 gruppi da 6."""
    return bool(_BITLOCKER.match(text.strip()))


def prepare(text, layout="IT", final_enter=False):
    """Ritorna (sequenza di (modificatori, tasto), caratteri non digitabili)."""
    if is_bitlocker(text):
        digits = re.sub(r"\D", "", text)
        seq = [(0, _DIGITS[d]) for d in digits]
        return seq + ([(0, ENTER)] if final_enter else []), []
    m = LAYOUTS[layout]
    text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    seq, bad = [], []
    for ch in text:
        if ch in m:
            seq.append(m[ch])
        elif ch not in bad:
            bad.append(ch)
    if final_enter:
        seq.append((0, ENTER))
    return seq, bad


def _report(mod, key):
    return bytes([mod, 0, key, 0, 0, 0, 0, 0])


def type_sequence(seq, dev="/dev/hidg0", delay=0.02, progress=None, stop=None):
    """Invia la sequenza al PC. delay di 20 ms: abbastanza lento anche per il firmware UEFI."""
    fd = os.open(dev, os.O_WRONLY | os.O_NONBLOCK)
    try:
        def send(data):
            for _ in range(200):
                try:
                    os.write(fd, data)
                    return
                except BlockingIOError:
                    select.select([], [fd], [], 0.05)
            raise RuntimeError("Il PC non legge la tastiera (cavo staccato?)")
        prev = None
        for i, (mod, key) in enumerate(seq):
            if stop is not None and stop.is_set():
                break
            if prev == (mod, key):  # stesso tasto due volte: serve un rilascio netto in mezzo
                time.sleep(delay)
            send(_report(mod, key))
            time.sleep(delay)
            send(_report(0, 0))
            time.sleep(delay)
            prev = (mod, key)
            if progress and i % 4 == 0:
                progress(i + 1, len(seq))
        if progress:
            progress(len(seq), len(seq))
    finally:
        os.close(fd)
