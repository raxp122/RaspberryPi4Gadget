"""Storico locale dei test (un file JSON Lines per tipo in data/). Resta solo sul Pi."""
import json
import os
import time

MAX = 2000


def _path(data_dir, kind):
    return os.path.join(data_dir, f"history-{kind}.jsonl")


def add(data_dir, kind, entry):
    entry = dict(entry, t=entry.get("t") or time.time())
    p = _path(data_dir, kind)
    os.makedirs(data_dir, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    try:
        if os.path.getsize(p) > 2_000_000:  # tiene solo gli ultimi MAX
            items = load(data_dir, kind)[:MAX]
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                for e in reversed(items):
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            os.replace(p + ".tmp", p)
    except OSError:
        pass
    return entry


def load(data_dir, kind):
    """Voci dalla più recente."""
    out = []
    try:
        with open(_path(data_dir, kind), encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return sorted(out, key=lambda e: e.get("t") or 0, reverse=True)


def remove(data_dir, kind, t):
    items = [e for e in load(data_dir, kind) if e.get("t") != t]
    p = _path(data_dir, kind)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        for e in reversed(items):
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(p + ".tmp", p)


def update(data_dir, kind, t, patch):
    items = load(data_dir, kind)
    for e in items:
        if e.get("t") == t:
            e.update(patch)
    p = _path(data_dir, kind)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        for e in reversed(items):
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(p + ".tmp", p)


def clear(data_dir, kind):
    try:
        os.remove(_path(data_dir, kind))
    except OSError:
        pass


def when(t):
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(t))
