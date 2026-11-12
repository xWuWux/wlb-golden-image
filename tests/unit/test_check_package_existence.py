"""Testy ci/check_package_existence.py (#288/anty-halucynacja). Offline — fetch zamockowany.

Weryfikuje parsowanie manifestów WLB, semantykę istnienia (200/404/fail-closed), fallback GitHub
dla pakietów HADES oraz wykrycie zmyślonej nazwy. Żadnych zapytań sieciowych.
"""

import lzma
import urllib.error

import pytest

from ci import check_package_existence as cpe
from ci.check_package_existence import (
    Pkg,
    exists,
    linux_fetch,
    load_linux_index,
    parse_linux,
    parse_packages_index,
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
    assert by_name["IRkernel"].url == "https://crandb.r-pkg.org/IRkernel"
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


def test_default_fetch_slow_anaconda_api_gets_longer_timeout(monkeypatch):
    # pyarrow na api.anaconda.org odpowiada ~20-30 s; 10 s dawało fałszywy fail-closed.
    seen = {}

    def fake(_req, timeout):
        seen["timeout"] = timeout
        return _Resp(200)

    monkeypatch.setattr(cpe.urllib.request, "urlopen", fake)
    assert cpe.default_fetch("https://api.anaconda.org/package/conda-forge/pyarrow") == 200
    assert seen["timeout"] == 45.0

    assert cpe.default_fetch("https://pypi.org/pypi/pandas/json") == 200
    assert seen["timeout"] == 10.0


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


APT_TASKS = """\
- name: Pakiety bazowe
  ansible.builtin.apt:
    update_cache: true
    name:
      - nginx=1.24.0-1
      - python3:any
      - g++=4:13.2
    state: present
- name: Pojedynczy pakiet
  apt:
    name: git
- name: Literalna pętla
  ansible.builtin.apt:
    name: "{{ item }}"
  loop:
    - curl
    - jq
- name: Pętla po słownikach
  apt:
    name: "{{ item.name }}"
  loop:
    - { name: python3-venv }
    - { name: sqlite3 }
- name: Pętla po słownikach bez pola
  apt:
    name: "{{ item.name }}"
  loop:
    - { other: x }
- name: Pętla po złym typie
  apt:
    name: "{{ item.name }}"
  loop:
    - nginx
- name: with_items
  apt:
    name: "{{ item }}"
  with_items: [wget, unzip]
- name: Jinja bez pętli
  apt:
    name: "{{ apt_packages }}"
- name: Pętla ze zmiennej
  apt:
    name: "{{ item }}"
  loop: "{{ extra_packages }}"
- name: Aktualizacja bez nazw
  apt:
    update_cache: true
    upgrade: dist
- name: Deb poza archiwum
  apt:
    deb: "{{ rstudio_server_deb_url }}"
"""


def test_parse_linux_string_list_loop_pins_and_jinja_skip(tmp_path):
    _write(tmp_path, "ansible/roles/base/tasks/main.yml", APT_TASKS)
    skipped = []
    pkgs = parse_linux(tmp_path, skipped)
    names = [p.name for p in pkgs]
    assert names == [
        "nginx",
        "python3",
        "g++",
        "git",
        "curl",
        "jq",
        "python3-venv",
        "sqlite3",
        "wget",
        "unzip",
    ]
    assert all(p.ecosystem == "apt" for p in pkgs)
    assert all(p.source == "ansible/roles/base/tasks/main.yml" for p in pkgs)
    by_name = {p.name: p for p in pkgs}
    assert by_name["nginx"].url == "https://launchpad.net/ubuntu/noble/amd64/nginx"
    assert "g%2B%2B" in by_name["g++"].url  # '+' w nazwie nie może rozjechać ścieżki
    assert len(skipped) == 4
    assert any("apt_packages" in s for s in skipped)
    assert any("extra_packages" in s for s in skipped)
    assert any("item.name" in s for s in skipped)


def test_parse_linux_scans_playbooks_and_handlers(tmp_path):
    _write(
        tmp_path,
        "ansible/site.yml",
        """\
- hosts: all
  tasks:
    - apt: { name: nginx }
  handlers:
    - name: restart
      apt: { name: curl }
""",
    )
    assert [p.name for p in parse_linux(tmp_path)] == ["nginx", "curl"]


def test_parse_linux_allowlist_skips_out_of_archive(tmp_path):
    _write(
        tmp_path,
        "ci/linux-package-allowlist.txt",
        "# pakiety poza archiwum\n\ndbeaver-ce  # .deb producenta (#271)\n",
    )
    _write(tmp_path, "ansible/roles/x/tasks/main.yml", "- apt: { name: [nginx, dbeaver-ce] }\n")
    skipped = []
    pkgs = parse_linux(tmp_path, skipped)
    assert [p.name for p in pkgs] == ["nginx"]
    assert skipped == ["ansible/roles/x/tasks/main.yml: dbeaver-ce (allowlista)"]


def test_parse_linux_non_string_and_invalid_names_are_skipped(tmp_path):
    _write(
        tmp_path,
        "ansible/site.yml",
        "- apt:\n    name: [nginx, 42, 'nginx; rm -rf /']\n",
    )
    skipped = []
    assert [p.name for p in parse_linux(tmp_path, skipped)] == ["nginx"]
    assert any("nie-string" in s for s in skipped)
    assert any("nieprawidłowa nazwa" in s for s in skipped)


def test_parse_linux_invalid_yaml_is_fail_closed(tmp_path):
    _write(tmp_path, "ansible/site.yml", "- apt: [nie-domknięte\n")
    with pytest.raises(ValueError, match="niepoprawny YAML"):
        parse_linux(tmp_path)


def test_parse_linux_no_tasks(tmp_path):
    assert parse_linux(tmp_path) == []


def test_verify_flags_fake_apt_package():
    good = Pkg("apt", "nginx", "a", "LP/nginx")
    fake = Pkg("apt", "zmyslony", "a", "LP/zmyslony")
    findings = verify([good, fake], lambda u: 200 if u == "LP/nginx" else 404)
    assert [f.pkg.name for f in findings] == ["zmyslony"]
    assert "halucynacja" in findings[0].reason


def test_main_linux_detects_hallucination(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "ansible/roles/base/tasks/main.yml", "- apt:\n    name: zmyslony-pakiet-xyz\n")
    monkeypatch.setattr(cpe, "load_linux_index", lambda: set())
    rc = cpe.main(["--root", str(tmp_path), "--ecosystems", "linux"])
    assert rc == 1
    assert "zmyslony-pakiet-xyz" in capsys.readouterr().err


def test_main_linux_index_failure_is_fail_closed(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "ansible/roles/base/tasks/main.yml", "- apt:\n    name: nginx\n")

    def boom():
        raise cpe.LinuxIndexError("testowy timeout")

    monkeypatch.setattr(cpe, "load_linux_index", boom)
    rc = cpe.main(["--root", str(tmp_path), "--ecosystems", "linux"])
    assert rc == 1
    assert "indeksu Ubuntu" in capsys.readouterr().err


def test_parse_packages_index_package_and_virtual_provides():
    text = """\
Package: nginx
Version: 1.24.0-2ubuntu7

Package: exim4-daemon-light
Provides: mail-transport-agent,
 default-mta,
 exim4-localscanapi-6.0

Package: g++
"""
    assert parse_packages_index(text) == {
        "nginx",
        "exim4-daemon-light",
        "mail-transport-agent",
        "default-mta",
        "exim4-localscanapi-6.0",
        "g++",
    }


def test_load_linux_index_downloads_every_pocket_and_component():
    seen = []

    def fetch_bytes(url):
        seen.append(url)
        return lzma.compress(f"Package: pkg-{len(seen)}\n".encode())

    names = load_linux_index(fetch_bytes)
    assert len(seen) == len(cpe.LINUX_INDEXES) == 12
    assert names == {f"pkg-{index}" for index in range(1, 13)}


def test_load_linux_index_is_fail_closed_on_bad_archive():
    with pytest.raises(cpe.LinuxIndexError, match=r"Packages\.xz"):
        load_linux_index(lambda _url: b"to nie jest xz")


def test_linux_fetch_maps_index_and_delegates_other_registries():
    fetch = linux_fetch({"nginx", "g++"}, lambda url: 200 if url == "https://pypi.org/x" else 404)
    assert fetch("https://launchpad.net/ubuntu/noble/amd64/nginx") == 200
    assert fetch("https://launchpad.net/ubuntu/noble/amd64/g%2B%2B") == 200
    assert fetch("https://launchpad.net/ubuntu/noble/amd64/zmyslony") == 404
    assert fetch("https://pypi.org/x") == 200
    assert fetch("https://pypi.org/y") == 404


def test_main_reports_skipped_jinja(tmp_path, monkeypatch, capsys):
    _write(
        tmp_path,
        "ansible/roles/base/tasks/main.yml",
        '- apt:\n    name: "{{ apt_packages }}"\n',
    )
    monkeypatch.setattr(cpe, "default_fetch", lambda _u: 200)
    rc = cpe.main(["--root", str(tmp_path), "--ecosystems", "linux"])
    assert rc == 1  # brak deterministycznych nazw -> fail-closed
    err = capsys.readouterr().err
    assert "Pominięto 1 nazw" in err
    assert "apt_packages" in err


def test_main_invalid_yaml_returns_error(tmp_path, capsys):
    _write(tmp_path, "ansible/site.yml", "- apt: [\n")
    rc = cpe.main(["--root", str(tmp_path), "--ecosystems", "linux"])
    assert rc == 1
    assert "BŁĄD:" in capsys.readouterr().err
