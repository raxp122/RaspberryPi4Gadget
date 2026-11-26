"""Output su framebuffer (/dev/fb0) con rotazione e aggiornamento differenziale.

Il pannello SPI e' lento: invece di riscrivere tutto il frame a ogni ridisegno,
scriviamo solo le righe che sono cambiate rispetto al frame precedente.
"""
import fcntl
import os

import pygame

KDSETMODE = 0x4B3A
KD_TEXT, KD_GRAPHICS = 0, 1


class Display:
    def __init__(self, rot=90, fbdev="/dev/fb0"):
        base = f"/sys/class/graphics/{os.path.basename(fbdev)}/"
        self.pw, self.ph = map(int, open(base + "virtual_size").read().strip().split(","))
        self.stride = int(open(base + "stride").read())
        bpp = int(open(base + "bits_per_pixel").read())
        if bpp != 16:
            raise RuntimeError(f"Framebuffer a {bpp} bpp non supportato (serve RGB565)")
        self.panel = pygame.Surface((self.pw, self.ph), 0, 16, (0xF800, 0x07E0, 0x001F, 0))
        self.fb = open(fbdev, "r+b", buffering=0)
        self.prev = None
        self.set_rotation(rot)
        # Mette la console in modalita' grafica: fbcon smette di disegnare testo e cursore.
        self.tty = None
        try:
            self.tty = os.open("/dev/tty1", os.O_RDWR)
            fcntl.ioctl(self.tty, KDSETMODE, KD_GRAPHICS)
        except OSError:
            self.tty = None

    def set_rotation(self, rot):
        self.rot = rot
        self.size = (self.ph, self.pw) if rot in (90, 270) else (self.pw, self.ph)
        self.prev = None  # forza un aggiornamento completo

    def show(self, surf):
        self.panel.blit(pygame.transform.rotate(surf, self.rot), (0, 0))
        raw = self.panel.get_buffer().raw
        pitch = self.panel.get_pitch()
        rowlen = self.pw * 2
        prev = self.prev
        y = 0
        while y < self.ph:
            o = y * pitch
            if prev is not None and raw[o:o + rowlen] == prev[o:o + rowlen]:
                y += 1
                continue
            start = y
            while y < self.ph:
                o = y * pitch
                if prev is not None and raw[o:o + rowlen] == prev[o:o + rowlen]:
                    break
                y += 1
            self._write_rows(raw, pitch, start, y)
        self.prev = raw

    def _write_rows(self, raw, pitch, y0, y1):
        if pitch == self.stride:
            self.fb.seek(y0 * self.stride)
            self.fb.write(raw[y0 * pitch:y1 * pitch])
        else:
            for y in range(y0, y1):
                self.fb.seek(y * self.stride)
                self.fb.write(raw[y * pitch:y * pitch + self.pw * 2])

    def close(self):
        try:
            black = pygame.Surface(self.size)
            black.fill((0, 0, 0))
            self.prev = None
            self.show(black)
        except Exception:
            pass
        if self.tty is not None:
            try:
                fcntl.ioctl(self.tty, KDSETMODE, KD_TEXT)
                os.close(self.tty)
            except OSError:
                pass
