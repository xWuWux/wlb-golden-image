"""Testy bramki wydania E2E (#277-S3).

Kontrakt: obraz/artefakt z którąkolwiek z czterech ścieżek fixture E2E musi zostać
odrzucony (kod 3), a czysty artefakt musi przejść (kod 0). Testy drzewa nie wymagają
libguestfs; tryb obrazu jest sprawdzany przez podstawiony virt-ls.
"""

import subprocess

import pytest
from conftest import REPO_ROOT, load_script

CONTRACT_FILE = REPO_ROOT / "ci/e2e-fixture-paths.txt"
CONTRACT_PATHS = tuple(
    line.strip()
    for line in CONTRACT_FILE.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
)


@pytest.fixture(scope="module")
def gate():
    return load_script("wlb_e2e_release_gate", REPO_ROOT / "ci/e2e_release_gate.py")


def make_path(root, contract):
    path = root / contract.lstrip("/")
    path.parent.mkdir(parents=True, exist_ok=True)
    if contract == "/opt/wlb/e2e":
        path.mkdir()
    else:
        path.write_text("fixture\n", encoding="utf-8")
    return path


# --- kontrakt ------------------------------------------------------------------


def test_kontrakt_sciezek_jest_zamrozony(gate):
    assert gate.CONTRACT_PATHS == CONTRACT_PATHS


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("wzgledna/sciezka\n", "musi być bezwzględna"),
        ("/a\n/a/\n", "duplikat"),
        ("/a/../b\n", "nieprawidłowa"),
        ("# tylko komentarz\n\n", "pusty"),
    ],
)
def test_kontrakt_odrzuca_niepoprawne_wpisy(gate, tmp_path, content, message):
    path = tmp_path / "kontrakt.txt"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(gate.GateError, match=message):
        gate.load_contract(path)


def test_brak_pliku_kontraktu_jest_bledem(gate, tmp_path):
    with pytest.raises(gate.GateError, match="nie można odczytać kontraktu"):
        gate.load_contract(tmp_path / "brak.txt")


def test_brak_kontraktu_zatrzymuje_bramke(gate, tmp_path, monkeypatch, capsys):
    """Brak kontraktu to fail-closed (kod 2), nie ciche „czysto” (#277)."""
    monkeypatch.setattr(gate, "CONTRACT_PATHS", ())
    monkeypatch.setattr(gate, "CONTRACT_ERROR", gate.GateError("brak kontraktu"))
    assert gate.main(["--tree", str(tmp_path)]) == gate.EXIT_ERROR
    assert "brak kontraktu" in capsys.readouterr().err


# --- drzewo artefaktów ---------------------------------------------------------


@pytest.mark.parametrize("contract", CONTRACT_PATHS)
def test_drzewo_z_kazda_sciezka_e2e_pada(gate, tmp_path, capsys, contract):
    make_path(tmp_path, contract)
    assert gate.main(["--tree", str(tmp_path)]) == gate.EXIT_E2E_FOUND
    err = capsys.readouterr().err
    assert contract in err
    assert "fixture E2E" in err


def test_drzewo_bez_e2e_przechodzi(gate, tmp_path, capsys):
    (tmp_path / "opt/wlb/bin").mkdir(parents=True)
    (tmp_path / "etc/xdg/autostart/other.desktop").parent.mkdir(parents=True)
    (tmp_path / "etc/xdg/autostart/other.desktop").write_text("x\n", encoding="utf-8")
    assert gate.main(["--tree", str(tmp_path)]) == gate.EXIT_OK
    assert "czysto" in capsys.readouterr().out


def test_symlink_liczy_sie_jako_artefakt(gate, tmp_path, capsys):
    target = tmp_path / "poza-drzewem"
    target.write_text("x\n", encoding="utf-8")
    link = tmp_path / "etc/tmpfiles.d/wlb-e2e.conf"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    assert gate.main(["--tree", str(tmp_path)]) == gate.EXIT_E2E_FOUND
    assert "/etc/tmpfiles.d/wlb-e2e.conf" in capsys.readouterr().err


def test_brak_argumentow_to_blad_konfiguracji(gate, capsys):
    assert gate.main([]) == gate.EXIT_ERROR
    assert "--tree" in capsys.readouterr().err


def test_nieistniejace_drzewo_to_blad_konfiguracji(gate, tmp_path, capsys):
    assert gate.main(["--tree", str(tmp_path / "nie-ma")]) == gate.EXIT_ERROR
    assert "nie istnieje" in capsys.readouterr().err


# --- obraz qcow2 (virt-ls) -----------------------------------------------------


def fake_virt_ls(monkeypatch, gate, *, stdout="", stderr="", returncode=0):
    """Podstawia virt-ls i pilnuje kształtu argv w KAŻDYM teście trybu obrazu.

    Regresja #360: `-i` to opcja guestfish, nie virt-ls — produkcyjne wydanie
    kończyło się kodem 2, a mock tego nie widział.
    """
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        assert "-i" not in cmd, "virt-ls nie ma opcji -i (to składnia guestfish)"
        assert cmd[:3] == ["virt-ls", "--format=qcow2", "-a"], f"zły początek argv: {cmd}"
        assert cmd[-2:] == ["-R", "/"], f"zły koniec argv: {cmd}"
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(gate.subprocess, "run", run)
    return calls


def test_argv_virt_ls_bez_opcji_inspektora(gate, tmp_path, monkeypatch):
    image = tmp_path / "obraz.qcow2"
    image.write_bytes(b"qcow2")
    calls = fake_virt_ls(monkeypatch, gate, stdout="etc/os-release\n")
    assert gate.list_image_paths(image) == ["etc/os-release"]
    assert calls == [["virt-ls", "--format=qcow2", "-a", str(image), "-R", "/"]]
    assert "-i" not in calls[0]


def test_obraz_z_e2e_pada(gate, tmp_path, monkeypatch, capsys):
    image = tmp_path / "obraz.qcow2"
    image.write_bytes(b"qcow2")
    fake_virt_ls(monkeypatch, gate, stdout="opt/wlb/bin/wlb-health\nopt/wlb/e2e/target.json\n")
    assert gate.check_image(image) == ["/opt/wlb/e2e"]
    assert gate.main(["--image", str(image)]) == gate.EXIT_E2E_FOUND
    assert "/opt/wlb/e2e" in capsys.readouterr().err


def test_obraz_bez_e2e_przechodzi(gate, tmp_path, monkeypatch, capsys):
    image = tmp_path / "obraz.qcow2"
    image.write_bytes(b"qcow2")
    fake_virt_ls(monkeypatch, gate, stdout="etc/os-release\nopt/wlb/bin/wlb-health\n")
    assert gate.check_image(image) == []
    assert gate.main(["--image", str(image)]) == gate.EXIT_OK
    assert "czysto" in capsys.readouterr().out


def test_listing_normalizuje_ukosnik(gate):
    assert gate.find_in_listing(["/opt/wlb/e2e", "etc/os-release"]) == ["/opt/wlb/e2e"]


def test_listing_wykrywa_plik_w_katalogu_kontraktu(gate):
    assert gate.find_in_listing(["opt/wlb/e2e/target.json"]) == ["/opt/wlb/e2e"]


def test_listing_nie_lapie_podciagu_nazwy(gate):
    assert gate.find_in_listing(["opt/wlb/e2e2/target.json"]) == []


def test_listing_pomija_puste_wpisy(gate):
    assert gate.find_in_listing(["", "  \n", "etc/os-release"]) == []


def test_obraz_bez_virt_ls_jest_bledem(gate, tmp_path, monkeypatch, capsys):
    image = tmp_path / "obraz.qcow2"
    image.write_bytes(b"qcow2")

    def run(*args, **kwargs):
        raise FileNotFoundError("virt-ls")

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main(["--image", str(image)]) == gate.EXIT_ERROR
    assert "virt-ls" in capsys.readouterr().err


def test_obraz_z_bledem_virt_ls_jest_bledem(gate, tmp_path, monkeypatch, capsys):
    image = tmp_path / "obraz.qcow2"
    image.write_bytes(b"qcow2")
    fake_virt_ls(monkeypatch, gate, stderr="nie da się zamontować", returncode=1)
    assert gate.main(["--image", str(image)]) == gate.EXIT_ERROR
    assert "nie odczytał" in capsys.readouterr().err


def test_brak_pliku_obrazu_jest_bledem(gate, tmp_path, capsys):
    assert gate.main(["--image", str(tmp_path / "brak.qcow2")]) == gate.EXIT_ERROR
    assert "nie istnieje" in capsys.readouterr().err


def test_timeout_virt_ls_jest_bledem(gate, tmp_path, monkeypatch, capsys):
    image = tmp_path / "obraz.qcow2"
    image.write_bytes(b"qcow2")

    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="virt-ls", timeout=600)

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main(["--image", str(image)]) == gate.EXIT_ERROR
    assert "600 s" in capsys.readouterr().err


def test_oserror_virt_ls_jest_bledem(gate, tmp_path, monkeypatch, capsys):
    image = tmp_path / "obraz.qcow2"
    image.write_bytes(b"qcow2")

    def run(*args, **kwargs):
        raise OSError("brak qemu")

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main(["--image", str(image)]) == gate.EXIT_ERROR
    assert "nie można uruchomić virt-ls" in capsys.readouterr().err


def test_blad_virt_ls_bez_stderr_uzywa_stdout(gate, tmp_path, monkeypatch, capsys):
    image = tmp_path / "obraz.qcow2"
    image.write_bytes(b"qcow2")
    fake_virt_ls(monkeypatch, gate, stdout="qemu: błąd odczytu\n", returncode=1)
    assert gate.main(["--image", str(image)]) == gate.EXIT_ERROR
    assert "qemu: błąd odczytu" in capsys.readouterr().err
