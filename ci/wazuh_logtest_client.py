#!/usr/bin/env python3
"""Przepuszcza wiersze logu przez wazuh-logtest (gniazdo analysisd) i wypisuje wynik jako JSON Lines.

    python3 ci/wazuh_logtest_client.py [--socket ŚCIEŻKA] < siem.log > wyniki.jsonl

Uruchamiany WEWNĄTRZ kontenera menedżera Wazuh (ci/wazuh-logtest.sh) jego własnym Pythonem,
więc korzysta wyłącznie z biblioteki standardowej. Cały plik idzie w jednej sesji logtest
(ten sam token), dzięki czemu reguły z frequency/timeframe widzą wcześniejsze zdarzenia.

Wiersze puste i zaczynające się od '#' (komentarze w próbkach testowych) są pomijane.
Każdy wiersz wyjścia: {"line": <wejście>, "output": <data.output z logtest>}.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys

DEFAULT_SOCKET = "/var/ossec/queue/sockets/logtest"
TIMEOUT = 30
ORIGIN = {"name": "wlb-ci", "module": "wlb"}


class LogtestError(RuntimeError):
    pass


def request(path: str, payload: dict) -> dict:
    """Jedno zapytanie protokołu logtest: 4 bajty długości (little-endian) + JSON, w obie strony."""
    data = json.dumps(payload).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(TIMEOUT)
        s.connect(path)
        s.sendall(struct.pack("<I", len(data)) + data)
        header = _recv_exact(s, 4)
        return json.loads(_recv_exact(s, struct.unpack("<I", header)[0]))


def _recv_exact(s: socket.socket, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = s.recv(size - len(buf))
        if not chunk:
            raise LogtestError("analysisd zamknął połączenie przed końcem odpowiedzi")
        buf += chunk
    return buf


def process(lines, path: str, out) -> int:
    token, count = None, 0
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        params = {"event": line, "log_format": "syslog", "location": "wlb-ci"}
        if token:
            params["token"] = token
        payload = {"version": 1, "origin": ORIGIN, "command": "log_processing", "parameters": params}
        reply = request(path, payload)
        if reply.get("error") != 0:
            raise LogtestError(f"logtest: {reply.get('message') or reply}")
        token = reply["data"].get("token", token)
        out.write(json.dumps({"line": line, "output": reply["data"]["output"]}, ensure_ascii=False) + "\n")
        count += 1
    return count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--socket", default=DEFAULT_SOCKET)
    args = parser.parse_args(argv)
    try:
        count = process(sys.stdin, args.socket, sys.stdout)
    except (OSError, LogtestError) as exc:
        print(f"wazuh-logtest: {exc}", file=sys.stderr)
        return 1
    print(f"wazuh-logtest: przetworzono {count} wierszy", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
