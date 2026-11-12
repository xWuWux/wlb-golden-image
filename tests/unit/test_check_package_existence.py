"""Testy ci/check_package_existence.py (#288/anty-halucynacja). Offline — fetch zamockowany.

Weryfikuje parsowanie manifestów WLB, semantykę istnienia (200/404/fail-closed), fallback GitHub
dla pakietów HADES oraz wykrycie zmyślonej nazwy. Żadnych zapytań sieciowych.
"""

import urllib.error

import pytest

from ci import check_package_existence as cpe
from ci.check_package_existence import (
    Pkg,
    exists,
    parse_python,
    parse_r,
    read_snapshot,
    verify,
)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # retry/backoff nie może spowalniać testów
    monkeypatch.setattr("ci.check_package_existence.time.sleep", lambda *_: None)


def _write(root, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


ENV_YML = """\
name: wlb-python
channels:
  - conda-forge
dependencies:
  - pandas
  - urllib3>=2.7.0
  - python-gdcm
  - pip
  - pip:
      - inspectomop
      - aiohttp>=3.14.4
      - inspectomop
"""

HADES = """\
# pakiety R
IRkernel
renv

DatabaseConnector       OHDSI/DatabaseConnector@*release
oro.dicom
"""


def test_parse_python_strips_versions_dedups_and_skips_pip(tmp_path):
    _write(tmp_path, "envs/python/environment.yml", ENV_YML)
    names = [(p.ecosystem, p.name) for p in parse_python(tmp_path)]
    assert ("conda-forge", "pandas") in names
    assert ("conda-forge", "urllib3") in names  # ograniczenie wersji odcięte
    assert ("conda-forge", "python-gdcm") in names
    assert ("PyPI", "inspectomop") in names
    assert ("PyPI", "aiohttp") in names
    assert ("conda-forge", "pip") not in names  # meta-pakiet pominięty
    assert sum(1 for _, n in names if n == "inspectomop") == 1  # deduplikacja


def test_parse_r_cran_url_and_github_fallback(tmp_path):
    _write(tmp_path, "envs/r/hades-packages.txt", HADES)
    by_name = {p.name: p for p in parse_r(tmp_path, "2026-09-01")}
    assert set(by_name) == {"IRkernel", "renv", "DatabaseConnector", "oro.dicom"}
    assert by_name["IRkernel"].fallback_url is None
    assert "2026-09-01" in by_name["IRkernel"].url
    assert by_name["DatabaseConnector"].fallback_url == "https://api.github.com/repos/OHDSI/DatabaseConnector"


def test_exists_present_absent_and_failclosed():
    assert exists("u", lambda _u: 200) is True
    assert exists("u", lambda _u: 404) is False
    assert exists("u", lambda _u: 503, retries=2) is None  # przejściowy -> fail-closed
    assert exists("u", lambda _u: 403) is None  # nieoczekiwany kod -> fail-closed (nie zgadujemy)


def test_exists_retries_then_resolves():
    seq = iter([503, 0, 200])
    assert exists("u", lambda _u: next(seq), retries=3) is True


def test_verify_flags_hallucination_and_respects_github_fallback():
    good = Pkg("PyPI", "pandas", "env", "R/pandas")
    halluc = Pkg("PyPI", "pandaz", "env", "R/pandaz")
    hades_gh = Pkg("CRAN", "DatabaseConnector", "h", "CRAN/DatabaseConnector", "GH/OHDSI/DatabaseConnector")
    hades_bad = Pkg("CRAN", "Zmyslone", "h", "CRAN/Zmyslone", "GH/OHDSI/Zmyslone")

    def fetch(url):
        return {
            "R/pandas": 200,
            "R/pandaz": 404,
            "CRAN/DatabaseConnector": 404,  # brak w snapshocie CRAN...
            "GH/OHDSI/DatabaseConnector": 200,  # ...ale jest na GitHub -> OK
            "CRAN/Zmyslone": 404,
            "GH/OHDSI/Zmyslone": 404,  # ani CRAN, ani GitHub -> halucynacja
        }.get(url, 404)

    findings = verify([good, halluc, hades_gh, hades_bad], fetch)
    assert {f.pkg.name for f in findings} == {"pandaz", "Zmyslone"}
    assert all("halucynacja" in f.reason for f in findings)


def test_verify_failclosed_on_unreachable_registry():
    findings = verify([Pkg("PyPI", "x", "env", "R/x")], lambda _u: 503)
    assert len(findings) == 1
    assert "fail-closed" in findings[0].reason


def test_read_snapshot_from_group_vars(tmp_path):
    _write(tmp_path, "ansible/group_vars/all.yml", 'r_cran_snapshot_date: "2026-09-01"\nfoo: bar\n')
    assert read_snapshot(tmp_path) == "2026-09-01"
    assert read_snapshot(tmp_path / "brak") == "latest"


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_default_fetch_status_and_transport_error(monkeypatch):
    monkeypatch.setattr(cpe.urllib.request, "urlopen", lambda *a, **k: _Resp(200))
    assert cpe.default_fetch("https://x") == 200

    def raise_http(*_a, **_k):
        raise urllib.error.HTTPError("u", 404, "nf", None, None)

    monkeypatch.setattr(cpe.urllib.request, "urlopen", raise_http)
    assert cpe.default_fetch("https://x") == 404

    def raise_url(*_a, **_k):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(cpe.urllib.request, "urlopen", raise_url)
    assert cpe.default_fetch("https://x") == 0


def test_default_fetch_head_405_falls_back_to_get(monkeypatch):
    calls = []

    def fake(req, *_a, **_k):
        calls.append(req.method)
        if req.method == "HEAD":
            raise urllib.error.HTTPError("u", 405, "no head", None, None)
        return _Resp(200)

    monkeypatch.setattr(cpe.urllib.request, "urlopen", fake)
    assert cpe.default_fetch("https://x") == 200
    assert calls == ["HEAD", "GET"]


def test_verify_failclosed_on_unreachable_fallback():
    pkg = Pkg("CRAN", "x", "h", "CRAN/x", "GH/x")
    findings = verify([pkg], lambda u: 404 if u == "CRAN/x" else 503)
    assert len(findings) == 1
    assert "fallback" in findings[0].reason


def test_main_all_exist(tmp_path, monkeypatch):
    _write(tmp_path, "envs/python/environment.yml", "dependencies:\n  - pandas\n  - pip:\n      - inspectomop\n")
    _write(tmp_path, "envs/r/hades-packages.txt", "IRkernel\n")
    _write(tmp_path, "ansible/group_vars/all.yml", 'r_cran_snapshot_date: "2026-09-01"\n')
    monkeypatch.setattr(cpe, "default_fetch", lambda _u: 200)
    assert cpe.main(["--root", str(tmp_path)]) == 0


def test_main_detects_hallucination(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "envs/python/environment.yml", "dependencies:\n  - pip:\n      - zmyslony_pakiet_xyz\n")
    monkeypatch.setattr(cpe, "default_fetch", lambda _u: 404)
    rc = cpe.main(["--root", str(tmp_path), "--ecosystems", "python", "--snapshot-date", "2026-09-01"])
    assert rc == 1
    assert "zmyslony_pakiet_xyz" in capsys.readouterr().err


def test_main_no_packages_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(cpe, "default_fetch", lambda _u: 200)
    assert cpe.main(["--root", str(tmp_path)]) == 1
