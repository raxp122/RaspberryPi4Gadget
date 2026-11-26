"""Pagina web in sola lettura con i report del Tester rete (porta 8080).

Si accende a mano e si spegne da sola dopo AUTO_OFF secondi. Serve solo i file .txt della cartella dei report.
"""
import html
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

PORT = 8080
AUTO_OFF = 30 * 60


class WebShare:
    def __init__(self, folder):
        self.folder = folder
        self.server = None
        self.until = 0

    @property
    def active(self):
        return self.server is not None

    def start(self):
        if self.server:
            self.until = time.time() + AUTO_OFF
            return
        folder = self.folder

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype):
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                path = unquote(self.path.split("?")[0])
                files = sorted((f for f in os.listdir(folder) if f.endswith(".txt")), reverse=True) \
                    if os.path.isdir(folder) else []
                if path in ("/", "/index.html"):
                    items = "".join(f'<li><a href="/r/{html.escape(f)}">{html.escape(f[:-4])}</a></li>' for f in files)
                    body = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                            "<title>Report Tester rete</title><style>body{font:16px system-ui;margin:16px;"
                            "max-width:900px}li{margin:6px 0}</style><h1>Report Tester rete</h1>"
                            f"<ul>{items or '<li>Nessun report salvato</li>'}</ul>")
                    return self._send(200, body, "text/html")
                if path.startswith("/r/"):
                    name = os.path.basename(path[3:])
                    if name in files:
                        with open(os.path.join(folder, name), encoding="utf-8") as f:
                            return self._send(200, f.read(), "text/plain")
                return self._send(404, "Non trovato", "text/plain")

        self.server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
        self.server.daemon_threads = True
        self.until = time.time() + AUTO_OFF
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self):
        while self.server and time.time() < self.until:
            time.sleep(5)
        self.stop()

    def stop(self):
        srv, self.server = self.server, None
        if srv:
            srv.shutdown()
            srv.server_close()


_instance = {}


def get(folder):
    if folder not in _instance:
        _instance[folder] = WebShare(folder)
    return _instance[folder]
