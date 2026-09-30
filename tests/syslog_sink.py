#!/usr/bin/env python3
"""Testowy odbiornik SIEM: przyjmuje syslog po TCP (ramki zakończone LF, jak omfwd z rsyslog)
i dopisuje każdą linię do pliku. VM testowa (sieć QEMU user) widzi hosta jako 10.0.2.2.
Z --tls-cert/--tls-key przyjmuje wyłącznie TLS (jak produkcyjny SIEM, #6) — certyfikat z
tests/lib/test-pki.sh, wystawiony na nazwę, którą VM weryfikuje (SIEM_TLS_NAME).

    python3 tests/syslog_sink.py --port 5514 --out build/ci-logs/siem.log \\
        --tls-cert build/test/siem.pem --tls-key build/test/siem.key
"""

import argparse
import asyncio
import signal
import ssl


async def serve(host: str, port: int, out: str, tls: ssl.SSLContext | None = None) -> None:
    log = open(out, "a", buffering=1)  # noqa: SIM115 - otwarty do końca działania odbiornika

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while line := await reader.readline():
            log.write(line.decode(errors="replace").rstrip("\r\n") + "\n")
        writer.close()

    server = await asyncio.start_server(handle, host, port, ssl=tls)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    async with server:
        await stop.wait()
    log.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5514)
    parser.add_argument("--out", required=True)
    parser.add_argument("--tls-cert", help="certyfikat serwera (PEM) — odbiornik tylko po TLS")
    parser.add_argument("--tls-key", help="klucz prywatny certyfikatu serwera")
    args = parser.parse_args()
    tls = None
    if args.tls_cert:
        tls = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(args.tls_cert, args.tls_key)
    asyncio.run(serve(args.host, args.port, args.out, tls))


if __name__ == "__main__":
    main()
