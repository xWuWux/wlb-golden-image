#!/usr/bin/env python3
"""Testowy serwer NTP (SNTPv4): odpowiada bieżącym czasem hosta, żeby chrony w VM miał z czym się
zsynchronizować. Jak tests/syslog_sink.py, ale UDP. VM (sieć QEMU user) widzi hosta jako 10.0.2.2.
Port 123 wymaga uprawnień roota (na runnerze CI przez sudo).

    sudo python3 tests/ntp_sink.py --port 123
"""

import argparse
import socket
import struct
import time

NTP_EPOCH = 2208988800  # sekund między 1900-01-01 (NTP) a 1970-01-01 (Unix)


def to_ntp(t: float) -> tuple[int, int]:
    sec = int(t) + NTP_EPOCH
    frac = int((t - int(t)) * (1 << 32))
    return sec, frac


def serve(host: str, port: int, stratum: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    while True:
        data, addr = sock.recvfrom(1024)
        if len(data) < 48:
            continue
        recv_sec, recv_frac = to_ntp(time.time())
        resp = bytearray(48)
        resp[0] = (0 << 6) | (4 << 3) | 4  # LI=0, VN=4, Mode=4 (serwer)
        resp[1] = stratum
        resp[2] = data[2]  # poll — echo z żądania
        resp[3] = 0xEC  # precision -20 (~1 us) jako bajt ze znakiem
        resp[12:16] = b"LOCL"  # reference id (zegar lokalny)
        struct.pack_into("!II", resp, 16, recv_sec - 1, 0)  # reference timestamp
        resp[24:32] = data[40:48]  # originate = transmit klienta (do wyliczenia opóźnienia)
        struct.pack_into("!II", resp, 32, recv_sec, recv_frac)  # receive timestamp
        tx_sec, tx_frac = to_ntp(time.time())
        struct.pack_into("!II", resp, 40, tx_sec, tx_frac)  # transmit timestamp
        sock.sendto(bytes(resp), addr)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=123)
    p.add_argument("--stratum", type=int, default=8)  # serwer referencyjny, nie z internetu
    a = p.parse_args()
    serve(a.host, a.port, a.stratum)


if __name__ == "__main__":
    main()
