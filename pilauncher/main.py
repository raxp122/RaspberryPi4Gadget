#!/usr/bin/env python3
"""PiLauncher - launcher touch per Raspberry Pi con schermo SPI 3.5".

Uso:  sudo python3 main.py [--calibrate]
"""
import os
import select
import signal
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame  # noqa: E402

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from core.calibrate import CalibScreen  # noqa: E402
from core.display import Display  # noqa: E402
from core.framework import Context, Manager, load_json, save_json  # noqa: E402
from core.home import Home, discover_apps  # noqa: E402
from core.touch import Touch, find_device  # noqa: E402

LEGACY_CALIB = "/home/raspberry/pipboy/touch_calib.json"


def main():
    pygame.display.init()
    pygame.font.init()
    cfg = load_json(os.path.join(APP_DIR, "config.json"), {"rot": 90})
    calib_path = os.path.join(APP_DIR, "calib.json")
    if not os.path.exists(calib_path) and os.path.exists(LEGACY_CALIB):
        save_json(calib_path, load_json(LEGACY_CALIB, None))  # riusa la calibrazione fatta prima

    display = Display(cfg.get("rot", 90))
    dev = cfg.get("touch_device") or find_device()
    touch = Touch(dev, display.size, None, display.rot)
    ctx = Context(APP_DIR, display, touch)
    touch.set_calibration(ctx.cal, display.rot)

    mgr = Manager(display.size, ctx)
    mgr.apps = discover_apps(APP_DIR)
    mgr.push(Home(mgr))
    if ctx.cal is None or "--calibrate" in sys.argv:
        mgr.push(CalibScreen(mgr))

    surf = pygame.Surface(display.size)
    last_draw, last_min = 0.0, -1

    def stop(*_):
        mgr.quit = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        while not mgr.quit:
            if touch.fd is not None:
                try:
                    select.select([touch.fd], [], [], 0.03)
                except InterruptedError:
                    pass
            else:
                time.sleep(0.05)
            for ev in touch.poll():
                mgr.dispatch(ev)
            mgr.process()
            now = time.time()
            mgr.update(now)
            minute = time.localtime(now).tm_min
            if minute != last_min:
                last_min, mgr.dirty = minute, True
            if mgr.animating and now - last_draw > 0.25:
                mgr.dirty = True
            if mgr.dirty:
                mgr.dirty = False
                if surf.get_size() != display.size:
                    surf = pygame.Surface(display.size)
                mgr.draw(surf)
                display.show(surf)
                last_draw = now
    finally:
        display.close()


if __name__ == "__main__":
    main()
