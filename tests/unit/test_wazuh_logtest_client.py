"""Klient protokołu wazuh-logtest na atrapie gniazda analysisd (#17) — bez dockera."""

import io
import json
import socket
import struct
import threading

import pytest

import wazuh_logtest_client as client

# --- protokół logtest: długość + JSON, jedna sesja na plik (#17) ---


class FakeAnalysisd:
    """Gniazdo UNIX odpowiadające jak wazuh-analysisd; zapamiętuje otrzymane zapytania."""

    def __init__(self, path, reply=None, close_early=False):
        self.path, self.requests = str(path), []
        self.reply, self.close_early = reply, close_early
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                size = struct.unpack("<I", conn.recv(4, socket.MSG_WAITALL))[0]
                req = json.loads(conn.recv(size, socket.MSG_WAITALL))
                self.requests.append(req)
                if self.close_early:
                    conn.sendall(struct.pack("<I", 100) + b"{}")
                    continue
                body = self.reply or {
                    "error": 0,
                    "data": {"token": "t1", "output": {"full_log": req["parameters"]["event"]}},
                }
                data = json.dumps(body).encode()
                conn.sendall(struct.pack("<I", len(data)) + data)

    def close(self):
        self.server.close()


@pytest.fixture
def sock_path(tmp_path):
    return tmp_path / "logtest"


def test_przetwarza_wiersze_w_jednej_sesji(sock_path):
    fake = FakeAnalysisd(sock_path)
    out = io.StringIO()
    count = client.process(["# komentarz\n", "\n", "pierwszy\n", "drugi\n"], str(sock_path), out)
    fake.close()
    assert count == 2
    results = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["line"] for r in results] == ["pierwszy", "drugi"]
    assert results[0]["output"]["full_log"] == "pierwszy"
    assert "token" not in fake.requests[0]["parameters"]
    assert fake.requests[1]["parameters"]["token"] == "t1"  # frequency/timeframe widzą poprzednie wiersze
    assert fake.requests[0]["command"] == "log_processing"


def test_blad_logtest_przerywa(sock_path, monkeypatch, capsys):
    fake = FakeAnalysisd(sock_path, reply={"error": 7, "message": "zły token"})
    monkeypatch.setattr("sys.stdin", io.StringIO("wiersz\n"))
    assert client.main(["--socket", str(sock_path)]) == 1
    fake.close()
    assert "zły token" in capsys.readouterr().err


def test_zerwane_polaczenie(sock_path):
    fake = FakeAnalysisd(sock_path, close_early=True)
    with pytest.raises(client.LogtestError, match="zamknął połączenie"):
        client.process(["wiersz\n"], str(sock_path), io.StringIO())
    fake.close()


def test_brak_gniazda(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("wiersz\n"))
    assert client.main(["--socket", str(tmp_path / "brak")]) == 1
    assert "wazuh-logtest:" in capsys.readouterr().err


def test_main_sukces(sock_path, monkeypatch, capsys):
    fake = FakeAnalysisd(sock_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("a\nb\n"))
    assert client.main(["--socket", str(sock_path)]) == 0
    fake.close()
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 2
    assert "przetworzono 2 wierszy" in captured.err
