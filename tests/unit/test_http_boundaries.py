"""Kontrakty adapterów rejestru pakietów i GitHuba na lokalnych połączeniach (#341)."""

import http.client
import socketserver
import ssl
import subprocess
import threading
import urllib.error
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def local_registry(statuses: list[int], tls: ssl.SSLContext | None = None) -> Iterator[tuple[str, list[str]]]:
    """Serve a scripted response series on loopback and record paths seen on the wire."""
    paths: list[str] = []

    def respond(conn, _address, _server):
        conn.settimeout(3)
        with tls.wrap_socket(conn, server_side=True) if tls else conn as stream, stream.makefile("rb") as request:
            _, path, _ = request.readline().decode().split()
            http.client.parse_headers(request)
            status = statuses[min(len(paths), len(statuses) - 1)]
            paths.append(path)
            body = b'{"id":17}'
            stream.sendall(f"HTTP/1.0 {status} reply\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)

    with socketserver.TCPServer(("127.0.0.1", 0), respond) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
        thread.start()
        try:
            scheme = "https" if tls else "http"
            yield f"{scheme}://127.0.0.1:{server.server_address[1]}", paths
        finally:
            server.shutdown()
            thread.join()


def test_license_fetch_retries_verified_https(tmp_path: Path, monkeypatch):
    import license_check as lc

    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(  # noqa: S603
        [  # noqa: S607 - openssl z pakietu systemowego CI
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    with local_registry([503, 200], tls) as (url, paths):
        try:
            result = lc.fetch(f"{url}/metadata")
        except urllib.error.HTTPError as exc:
            result = exc.code
    assert (result, paths) == (b'{"id":17}', ["/metadata", "/metadata"]), "contract:retry"


@pytest.mark.parametrize("transport", ["callable", "http"])
def test_github_run_request(transport: str, monkeypatch):
    import ci_telemetry as telemetry

    if transport == "http":
        monkeypatch.setenv("no_proxy", "127.0.0.1")
        with local_registry([200]) as (url, paths):
            monkeypatch.setattr(telemetry, "API", url)
            result = telemetry.GitHub("lab/image", None).run(17)
    else:
        paths = []

        def fetch(url: str, token: str | None) -> dict:
            paths.append(url.removeprefix("https://api.github.com"))
            return {"id": 17}

        result = telemetry.GitHub("lab/image", None, fetch=fetch).run(17)
    assert (result, paths) == ({"id": 17}, ["/repos/lab/image/actions/runs/17"]), "contract:run-path"
