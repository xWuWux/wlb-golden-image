#!/usr/bin/env python3
"""Sondy sieciowe etapu 5 dla badacza (#323).

Ten plik jest testowym helperem, nie częścią obrazu produkcyjnego. Klasyfikuje wynik próby
jako `response`/`connected`, `refused`, `timeout`, `denied`, `absent` albo `error`, żeby
harness nie uznawał awarii środowiska (brak trasy, DNS, timeout) za skuteczną blokadę.

Kody wyjścia CLI:
  udp-dns:      response=0, refused/timeout=2, error=3
  tcp/tcp6:     connected=0, refused=2, timeout=3, error=4
  kernel-read:  denied=0, readable=1, error=2, absent=3

Harness akceptacyjny wymaga dodatkowo korelacji z wpisem `wlb-egress-deny` dla unikalnego
celu/portu; sam timeout lub sam brak odpowiedzi nie jest dowodem odmowy.
"""

from __future__ import annotations

import socket
import sys

DNS_QUERY = b"\x00\x00\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01"

UDP_EXIT = {"response": 0, "refused": 2, "timeout": 2, "error": 3}
TCP_EXIT = {"connected": 0, "refused": 2, "timeout": 3, "error": 4}
KERNEL_EXIT = {"denied": 0, "readable": 1, "error": 2, "absent": 3}


def udp_dns(host: str, port: int, source_port: int, timeout: float = 3.0) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("", source_port))
        sock.settimeout(timeout)
        sock.sendto(DNS_QUERY, (host, port))
        sock.recvfrom(512)
    except TimeoutError:
        return "timeout"
    except ConnectionRefusedError:
        return "refused"
    except OSError:
        return "error"
    else:
        return "response"
    finally:
        sock.close()


def tcp(host: str, port: int, family: int = socket.AF_INET, timeout: float = 3.0) -> str:
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((host, port))
    except TimeoutError:
        return "timeout"
    except ConnectionRefusedError:
        return "refused"
    except OSError:
        return "error"
    else:
        return "connected"
    finally:
        sock.close()


def kernel_read(path: str) -> str:
    try:
        with open(path, "rb") as stream:
            stream.read(1)
    except FileNotFoundError:
        return "absent"
    except PermissionError:
        return "denied"
    except OSError:
        return "error"
    else:
        return "readable"


def main(argv: list[str]) -> int:
    if not argv:
        print("użycie: net_probe.py {udp-dns|tcp|tcp6|kernel-read} ...", file=sys.stderr)
        return 64
    command, args = argv[0], argv[1:]
    try:
        if command == "udp-dns":
            status = udp_dns(args[0], int(args[1]), int(args[2]))
            code = UDP_EXIT[status]
        elif command in {"tcp", "tcp6"}:
            family = socket.AF_INET6 if command == "tcp6" else socket.AF_INET
            status = tcp(args[0], int(args[1]), family=family)
            code = TCP_EXIT[status]
        elif command == "kernel-read":
            status = kernel_read(args[0])
            code = KERNEL_EXIT[status]
        else:
            print(f"nieznana sonda: {command}", file=sys.stderr)
            return 64
    except (IndexError, ValueError) as exc:
        print(f"błędne argumenty: {exc}", file=sys.stderr)
        return 64
    print(status)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
