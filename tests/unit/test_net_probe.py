"""Testy klasyfikacji sond egress (#323).

Nie uruchamiają sieci: sprawdzają, że helper odróżnia odpowiedź, odmowę polityki,
timeout i błąd środowiska, zamiast traktować dowolny `OSError` jako sukces.
"""

import errno

from conftest import REPO_ROOT, load_script

probe = load_script("wlb_net_probe", REPO_ROOT / "tests/lib/net_probe.py")


class FakeSocket:
    def __init__(self, *, timeout=False, refused=False):
        self.timeout = timeout
        self.refused = refused
        self.closed = False

    def bind(self, _address):
        return None

    def settimeout(self, _timeout):
        return None

    def sendto(self, _data, _address):
        return len(_data)

    def recvfrom(self, _size):
        if self.timeout:
            raise probe.socket.timeout
        if self.refused:
            raise ConnectionRefusedError(errno.ECONNREFUSED, "refused")
        return b"answer", ("1.1.1.1", 53)

    def connect(self, _address):
        if self.timeout:
            raise probe.socket.timeout
        if self.refused:
            raise ConnectionRefusedError(errno.ECONNREFUSED, "refused")

    def close(self):
        self.closed = True


def test_udp_timeout_is_not_success(monkeypatch):
    fake = FakeSocket(timeout=True)
    monkeypatch.setattr(probe.socket, "socket", lambda *_args: fake)
    assert probe.udp_dns("1.1.1.1", 53, 54321) == "timeout"
    assert fake.closed


def test_udp_refused_is_distinct_from_timeout(monkeypatch):
    fake = FakeSocket(refused=True)
    monkeypatch.setattr(probe.socket, "socket", lambda *_args: fake)
    assert probe.udp_dns("1.1.1.1", 53, 54321) == "refused"


def test_udp_response_is_not_denied(monkeypatch):
    fake = FakeSocket()
    monkeypatch.setattr(probe.socket, "socket", lambda *_args: fake)
    assert probe.udp_dns("1.1.1.1", 53, 54321) == "response"


def test_tcp_timeout_and_refused(monkeypatch):
    for expected, fake in (("timeout", FakeSocket(timeout=True)), ("refused", FakeSocket(refused=True))):
        monkeypatch.setattr(probe.socket, "socket", lambda *_args, _fake=fake: _fake)
        assert probe.tcp("192.0.2.1", 443) == expected


def test_tcp_connected_is_not_denied(monkeypatch):
    monkeypatch.setattr(probe.socket, "socket", lambda *_args: FakeSocket())
    assert probe.tcp("192.0.2.1", 443) == "connected"


def test_kernel_read_classifies_readable_and_absent(tmp_path):
    readable = tmp_path / "readable"
    readable.write_bytes(b"x")
    assert probe.kernel_read(str(readable)) == "readable"
    assert probe.kernel_read(str(tmp_path / "absent")) == "absent"


def test_kernel_read_denied_requires_permission_error(monkeypatch):
    def denied(_path, _mode="rb"):
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr("builtins.open", denied)
    assert probe.kernel_read("/dev/mem") == "denied"


def test_kernel_read_other_oserror_is_error(monkeypatch):
    def broken(_path, _mode="rb"):
        raise OSError(errno.EIO, "I/O")

    monkeypatch.setattr("builtins.open", broken)
    assert probe.kernel_read("/dev/mem") == "error"


def test_cli_exit_codes_are_stable(monkeypatch, capsys):
    monkeypatch.setattr(probe, "udp_dns", lambda *_args: "timeout")
    assert probe.main(["udp-dns", "1.1.1.1", "53", "54321"]) == 2
    assert capsys.readouterr().out.strip() == "timeout"
    assert probe.main([]) == 64
    assert probe.main(["unknown"]) == 64
