"""Ocena wyrażeń licencyjnych i zbieranie pakietów (bez sieci — atrapa fetchera)."""

import json
import shutil
import urllib.error
from pathlib import Path

import pytest
import yaml

import license_check as lc

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY = yaml.safe_load((REPO_ROOT / "ci/license-policy.yml").read_text())


@pytest.mark.parametrize(
    "expr, verdict",
    [
        ("MIT", "allowed"),
        ("MIT + file LICENSE", "allowed"),
        ("GPL (>= 2)", "allowed"),
        ("GPL-2 | GPL-3", "allowed"),
        ("Apache License 2.0", "allowed"),
        ("Apache License (== 2.0) | file LICENSE", "allowed"),
        ("BSD_3_clause + file LICENSE", "allowed"),
        ("LGPL-2.1-or-later", "allowed"),
        ("GPL-3.0-only WITH GCC-exception-3.1", "allowed"),
        ("(MIT OR Apache-2.0)", "allowed"),
        ("MIT AND BSD-3-Clause", "allowed"),
        ("Python Software Foundation License", "allowed"),
        ("GNU Affero General Public License v3", "review"),
        ("AGPL-3.0-or-later OR MIT", "allowed"),  # wystarczy jedna dozwolona alternatywa
        ("MIT AND AGPL-3.0", "review"),
        ("SSPL-1.0", "denied"),
        ("CC-BY-NC-4.0", "denied"),
        ("CC-BY-4.0", "allowed"),
        ("file LICENSE", "unknown"),
        ("Proprietary", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
        ("WTFPL", "unknown"),
        ("0BSD AND LGPL-2.1-or-later AND GPL-2.0-or-later", "allowed"),
        ("X11 AND BSD-3-Clause", "allowed"),
        ("IJG AND BSD-3-Clause AND Zlib", "allowed"),
        ("LicenseRef-libglvnd", "allowed"),
        ("LicenseRef-Ubuntu-Font-Licence-Version-1.0", "allowed"),
        ("LicenseRef-Nieznana", "unknown"),
    ],
)
def test_evaluate(expr, verdict):
    assert lc.evaluate(expr, POLICY)[0] == verdict


def test_rodzina_poza_polityka():
    policy = {"allowed": ["MIT"]}
    assert lc.evaluate("Apache-2.0", policy) == ("unknown", "poza polityką: Apache-2.0")


def test_split_expression():
    assert lc.split_expression("MIT + file LICENSE | GPL-2") == [["MIT"], ["GPL-2"]]
    assert lc.split_expression("(MIT AND BSD-3-Clause) OR GPL-3.0") == [["MIT", "BSD-3-Clause"], ["GPL-3.0"]]


def test_wyjatki_z_polityki():
    pkgs = [
        lc.Package("pypi", "inspectomop", "0.2.3", "GNU Affero General Public License v3"),
        lc.Package("cran", "stringi", "1.8", "file LICENSE"),
        lc.Package("cran", "Rcpp", "1.0", "GPL (>= 2)"),
        lc.Package("pypi", "cos-takiego", "1.0", "SSPL-1.0"),
    ]
    lc.apply_policy(pkgs, POLICY)
    assert [p.verdict for p in pkgs] == ["exception", "exception", "allowed", "denied"]
    text, violations = lc.report(pkgs, locked=False)
    assert violations == 1
    assert "| pypi | cos-takiego | 1.0 | SSPL-1.0 | denied |" in text
    assert "brak locków" in text


def test_parse_dcf_z_kontynuacja_linii():
    records = lc.parse_dcf("Package: a\nImports: b,\n    c (>= 1.0)\nLicense: MIT\n\nPackage: b\nLicense: GPL-2\n")
    assert records[0]["Imports"] == "b, c (>= 1.0)"
    assert lc.dependency_names(records[0]["Imports"]) == ["b", "c"]
    assert records[1] == {"Package": "b", "License": "GPL-2"}


PACKAGES = """Package: TopPkg
Version: 1.0
Imports: DepA (>= 1.0), methods
License: Apache License 2.0

Package: DepA
Version: 2.0
LinkingTo: DepB
License: MIT + file LICENSE

Package: DepB
Version: 3.0
License: GPL-3
"""


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        for key, value in self.responses.items():
            if key in url:
                return value if isinstance(value, bytes) else json.dumps(value).encode()
        raise AssertionError(f"nieoczekiwany URL: {url}")


@pytest.fixture
def repo(tmp_path):
    for rel in ("envs/r/renv.lock", "envs/r/hades-packages.txt", "envs/python/environment.yml"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, tmp_path / rel)
    return tmp_path


def test_r_z_plikow_intencji_z_zaleznosciami_i_fallbackiem_github(repo):
    # ścieżka "przed make freeze": pusty renv.lock -> pakiety z hades-packages.txt i ich zależności
    (repo / "envs/r/renv.lock").write_text(json.dumps({"R": {}, "Packages": {}}))
    (repo / "envs/r/hades-packages.txt").write_text("TopPkg\nOhdsiOnly  OHDSI/OhdsiOnly@*release  # spoza CRAN\n")
    fetcher = FakeFetcher({
        "src/contrib/PACKAGES": PACKAGES.encode(),
        "OHDSI/OhdsiOnly/HEAD/DESCRIPTION": b"Package: OhdsiOnly\nVersion: 0.9\nLicense: Apache License 2.0\n",
    })  # fmt: skip
    pkgs = {p.name: p for p in lc.r_packages(repo, "https://ppm/cran/2026-09-01", fetcher)}
    assert set(pkgs) == {"TopPkg", "DepA", "DepB", "OhdsiOnly"}  # bez pakietów bazowych R
    assert pkgs["DepB"].license == "GPL-3"
    assert pkgs["OhdsiOnly"].version == "0.9"


def test_r_z_renv_lock(repo):
    lock = {"R": {}, "Packages": {
        "DepA": {"Package": "DepA", "Version": "2.0", "Source": "Repository"},
        "Gh": {"Package": "Gh", "Version": "1.1", "RemoteType": "github", "RemoteUsername": "OHDSI",
               "RemoteRepo": "Gh", "RemoteSha": "abc123"},
    }}  # fmt: skip
    (repo / "envs/r/renv.lock").write_text(json.dumps(lock))
    fetcher = FakeFetcher({
        "src/contrib/PACKAGES": PACKAGES.encode(),
        "OHDSI/Gh/abc123/DESCRIPTION": b"Package: Gh\nVersion: 1.1\nLicense: MIT\n",
    })  # fmt: skip
    pkgs = {p.name: p for p in lc.r_packages(repo, "https://ppm/cran/x", fetcher)}
    assert set(pkgs) == {"DepA", "Gh"}  # tylko zamrożone pakiety, bez rozwijania zależności
    assert pkgs["DepA"].license == "MIT + file LICENSE"


def test_python_z_locka_conda_i_pip(repo):
    (repo / "envs/python/environment.lock.yml").write_text(
        "name: x\ndependencies:\n  - pandas=2.2.3\n  - pip=24.0\n"
        "  - pip:\n      - inspectomop==0.2.3\n      - other[extra]>=1\n"
    )
    fetcher = FakeFetcher({
        "anaconda.org/package/conda-forge/pandas": {"license": "BSD-3-Clause"},
        "pypi.org/pypi/inspectomop/0.2.3/json": {"info": {"classifiers": [
            "License :: OSI Approved :: GNU Affero General Public License v3"]}},
        "pypi.org/pypi/other/json": {"info": {"version": "1.5", "license": "Apache 2.0\nfull text..."}},
    })  # fmt: skip
    pkgs = {p.name: p for p in lc.python_packages(repo, fetcher)}
    assert pkgs["pandas"].license == "BSD-3-Clause"
    assert pkgs["pip"].license == "MIT"
    assert pkgs["inspectomop"].license == "GNU Affero General Public License v3"
    assert (pkgs["other"].version, pkgs["other"].license) == ("1.5", "Apache 2.0")


def test_conda_brak_w_api_to_licencja_nieznana(repo):

    (repo / "envs/python/environment.lock.yml").write_text(
        "dependencies:\n  - pakiet-spoza-api=0.1\n  - pandas=2.2.3\n"
    )

    def fetcher(url):
        if "pakiet-spoza-api" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if "pandas" in url:
            return json.dumps({"license": "BSD-3-Clause"}).encode()
        raise urllib.error.HTTPError(url, 500, "boom", {}, None)

    pkgs = {p.name: p for p in lc.python_packages(repo, fetcher)}
    assert pkgs["pakiet-spoza-api"].license is None and pkgs["pakiet-spoza-api"].note == "brak w api.anaconda.org"
    lc.apply_policy(list(pkgs.values()), POLICY)
    assert pkgs["pakiet-spoza-api"].verdict == "unknown"
    assert "brak w api.anaconda.org" in pkgs["pakiet-spoza-api"].note

    (repo / "envs/python/environment.lock.yml").write_text("dependencies:\n  - inny=1\n")
    with pytest.raises(urllib.error.HTTPError):  # inne błędy HTTP nie są maskowane
        lc.python_packages(repo, fetcher)


def test_main_konczy_sie_bledem_przy_naruszeniach(repo, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)  # nie zaśmiecaj podsumowania CI
    (repo / "ci").mkdir()
    (repo / "ansible/group_vars").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "ci/license-policy.yml", repo / "ci/license-policy.yml")
    (repo / "ansible/group_vars/all.yml").write_text("r_cran_snapshot_date: '2026-09-01'\n")
    monkeypatch.setattr(lc, "r_packages", lambda root, cran: [lc.Package("cran", "zly", "1", "SSPL-1.0")])
    monkeypatch.setattr(lc, "python_packages", lambda root: [lc.Package("pypi", "ok", "1", "MIT")])
    assert lc.main(["--repo-root", str(repo)]) == 1
    assert "Naruszenia: **1**" in capsys.readouterr().out

    monkeypatch.setattr(lc, "r_packages", lambda root, cran: [])
    assert lc.main(["--repo-root", str(repo)]) == 0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (urllib.error.HTTPError("https://pypi.org/x", 503, "Backend is unhealthy", {}, None), True),
        (urllib.error.HTTPError("https://pypi.org/x", 429, "Too Many Requests", {}, None), True),
        (urllib.error.HTTPError("https://pypi.org/x", 404, "Not Found", {}, None), False),
        (urllib.error.HTTPError("https://pypi.org/x", 403, "Forbidden", {}, None), False),
        (urllib.error.URLError("timed out"), True),
        (TimeoutError("read timed out"), True),
        (ValueError("dozwolone tylko https"), False),
    ],
)
def test_bledy_przejsciowe_rejestru(error, expected):
    assert lc.transient(error) is expected


def test_main_awaria_rejestru_to_infra_a_nie_naruszenie(repo, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    (repo / "ci").mkdir()
    (repo / "ansible/group_vars").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "ci/license-policy.yml", repo / "ci/license-policy.yml")
    (repo / "ansible/group_vars/all.yml").write_text("r_cran_snapshot_date: '2026-09-01'\n")

    def pypi_down(root, cran):
        raise urllib.error.HTTPError("https://pypi.org/pypi/x/json", 503, "Backend is unhealthy", {}, None)

    monkeypatch.setattr(lc, "r_packages", pypi_down)
    assert lc.main(["--repo-root", str(repo)]) == 1
    assert "::error title=INFRA: rejestr pakietów niedostępny::" in capsys.readouterr().out

    def forbidden(root, cran):
        raise urllib.error.HTTPError("https://pypi.org/pypi/x/json", 403, "Forbidden", {}, None)

    monkeypatch.setattr(lc, "r_packages", forbidden)
    with pytest.raises(urllib.error.HTTPError):  # błąd trwały nie jest maskowany jako INFRA
        lc.main(["--repo-root", str(repo)])
