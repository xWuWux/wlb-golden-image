#!/usr/bin/env python3
"""Testowy proxy z allowlistą (#16): przepuszcza tylko hosty z allowlisty, resztę (w tym API LLM,
§31.3) odrzuca kodem 403. Jak tests/syslog_sink.py / ntp_sink.py — minimalny serwer na hoście, który
VM (sieć QEMU user) widzi jako 10.0.2.2. NIE forwarduje ruchu (VM jest izolowana): dla hosta z
allowlisty zwraca atrapę 200, co wystarcza do sprawdzenia egzekwowania allowlisty na prawdziwym proxy.

    python3 tests/proxy_sink.py --port 3128 --allow pypi.mirror.local,cran.mirror.local
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ALLOW: set[str] = set()


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _target_host(self) -> str:
        # żądanie proxy: ścieżka to absolutny URI (GET http://host/...) albo CONNECT host:port
        if self.command == "CONNECT":
            return self.path.rsplit(":", 1)[0]
        return urlsplit(self.path).hostname or ""

    def _reply(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _handle(self) -> None:
        if self._target_host() in ALLOW:
            self._reply(200, b"OK (atrapa mirrora z allowlisty)\n")
        else:
            self._reply(403, b"Blocked by allowlist\n")

    do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_CONNECT = _handle

    def log_message(self, *_args) -> None:  # cisza — logi testu prowadzi wywołujący
        pass


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=3128)
    p.add_argument("--allow", default="", help="hosty z allowlisty, po przecinku")
    a = p.parse_args()
    global ALLOW
    ALLOW = {h.strip() for h in a.allow.split(",") if h.strip()}
    ThreadingHTTPServer((a.host, a.port), Proxy).serve_forever()


if __name__ == "__main__":
    main()
