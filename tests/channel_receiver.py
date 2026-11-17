"""Controlled HTTP receiver for synthetic channel probes (#333).

Use on an isolated CI host reachable from the tested VM. The controller reads
receipts in-process. No endpoint accepts commands or exposes receipt history.
"""

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

MAX_PAYLOAD_BYTES = 65536


@dataclass(frozen=True)
class Receipt:
    """Bytes observed for one POST, including an incomplete request."""

    bytes_received: int
    sha256: str
    complete: bool


@dataclass
class Receiver:
    """Controller handle. URL uses the actual bound address and ephemeral port."""

    url: str
    _receipts: list[Receipt]
    _lock: threading.Lock

    def snapshot(self) -> tuple[Receipt, ...]:
        """Return a consistent copy. Take snapshots after the observation window."""
        with self._lock:
            return tuple(self._receipts)


@contextmanager
def receive_canary(
    host: str = "127.0.0.1", *, read_timeout: float = 1.0
) -> Iterator[Receiver]:
    """Serve bounded POST payloads until context exit.

    host is an explicitly chosen test interface, never a production destination.
    The kernel allocates the port. read_timeout bounds each connection, including
    a stalled request header. Receipt content contains length/hash, never payload.
    """
    if not 0 < read_timeout <= 30:
        raise ValueError("read_timeout must be in (0, 30]")
    receipts: list[Receipt] = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            self.request.settimeout(read_timeout)
            super().setup()

        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            if self.path != "/health":
                self.send_error(404)
                return
            self.send_response(204)
            self.end_headers()

        def do_POST(self) -> None:
            lengths = self.headers.get_all("Content-Length", [])
            # Unmeasurable framing must invalidate the observation.
            if (
                len(lengths) != 1
                or self.headers.get("Transfer-Encoding") is not None
                or not lengths[0].isascii()
                or not lengths[0].isdecimal()
                or len(lengths[0]) > 6
            ):
                with lock:
                    receipts.append(Receipt(0, hashlib.sha256(b"").hexdigest(), False))
                self.send_error(400)
                return
            size = int(lengths[0])
            if size > MAX_PAYLOAD_BYTES:
                with lock:
                    receipts.append(Receipt(0, hashlib.sha256(b"").hexdigest(), False))
                self.send_error(413)
                return
            digest = hashlib.sha256()
            received = 0
            try:
                while received < size:
                    chunk = self.rfile.read1(min(4096, size - received))
                    if not chunk:
                        break
                    received += len(chunk)
                    digest.update(chunk)
            except (OSError, TimeoutError):
                pass
            complete = received == size
            with lock:
                receipts.append(Receipt(received, digest.hexdigest(), complete))
            try:
                self.send_response(204 if complete else 400)
                self.end_headers()
            except OSError:
                pass

    server = HTTPServer((host, 0), Handler)
    address, port = server.server_address[:2]
    receiver = Receiver(f"http://{address}:{port}", receipts, lock)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield receiver
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=read_timeout + 1)
        if thread.is_alive():
            raise RuntimeError("receiver did not stop")


def transfer_matches(receipts: tuple[Receipt, ...], payload: bytes) -> bool:
    """Accept exactly one complete transfer of the expected synthetic payload."""
    return len(receipts) == 1 and receipts[0] == Receipt(
        len(payload), hashlib.sha256(payload).hexdigest(), True
    )
