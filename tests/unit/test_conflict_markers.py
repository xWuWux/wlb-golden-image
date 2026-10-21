import subprocess
from pathlib import Path

import conflict_markers as cm

# --- Bramka znacznikow konfliktu (#123) ---


def _git(root: Path, *args: str) -> str:
    # stale arg (test pomocniczy), git z PATH bez wejscia uzytkownika
    cmd = ["git", "-C", str(root), *args]
    done = subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
    return done.stdout.decode()


def test_wykrywa_wszystkie_znaczniki_gita():
    text = "\n".join(
        [
            "<<<<<<< HEAD",
            "nasza wersja",
            "=======",
            "ich wersja",
            ">>>>>>> feature/x",
        ]
    )
    assert [n for n, _ in cm.marker_lines(text)] == [1, 3, 5]


def test_wykrywa_sekcje_przodka_diff3_i_szerokie_znaczniki():
    # merge.conflictStyle=diff3 dokłada |||||||; merge.conflictSize poszerza wszystkie.
    text = "\n".join(["||||||| bazowy commit", "<<<<<<<< głowa", "========", ">>>>>>>> nowa"])
    assert [line for _, line in cm.marker_lines(text)] == [
        "||||||| bazowy commit",
        "<<<<<<<< głowa",
        "========",
        ">>>>>>>> nowa",
    ]


def test_nie_myli_z_typowym_tekstem():
    text = "\n".join(
        [
            "Tytuł",
            "=====",  # podkreślenie Setext/RST krótsze niż 7 znaków
            "a === b === c",  # środkowe „===" nie jest na początku wiersza
            "| lewo | prawo |",  # tabele markdown z pionowymi kreskami
            "git log <<-1 --oneline",  # „<<" za mało znaków
            "````````",  # 8 backtików (fence) to nie znacznik
        ]
    )
    assert cm.marker_lines(text) == []


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("# Bez konfliktu\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return root


def test_czyste_drzewo_robocze_brak_trafien(tmp_path):
    assert cm.scan(_repo(tmp_path)) == []


def test_wykrywa_znacznik_w_drzewie_roboczym(tmp_path):
    root = _repo(tmp_path)
    (root / "README.md").write_text("# Konflikt\n<<<<<<< HEAD\nnasz\n=======\nich\n>>>>>>> feat/x\n")
    assert len(cm.scan(root)) == 3


def test_staged_wykrywa_to_co_w_indeksie_nie_na_dysku(tmp_path):
    """Regresja (f0b4b5a): znacznik zacommitowany mimo czystego drzewa roboczego.

    Znacznik trafiał do repo, bo na dysku plik był już „czysty" po ręcznym
    rozwiązywaniu, a w indeksie została jego wersja sprzed poprawki.
    """
    root = _repo(tmp_path)
    (root / "docs.txt").write_text("x\n=======\ny\n")
    _git(root, "add", "docs.txt")
    (root / "docs.txt").write_text("x\ny\n")  # dysk posprzątany, indeks brudny
    assert cm.scan(root) == []
    assert cm.scan(root, staged=True) == ["docs.txt:2:======="]


def test_binaria_nie_da_trafien(tmp_path):
    root = _repo(tmp_path)
    (root / "obraz.bin").write_bytes(b"<<<<<<< HEAD\x00\x01\x02")
    _git(root, "add", ".")
    assert cm.scan(root) == []


def test_main_kod_wyjscia(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    monkeypatch.chdir(root)
    assert cm.main([]) == 0
    (root / "README.md").write_text("<<<<<<< HEAD\n")
    assert cm.main([]) == 1
    assert "BŁĄD" in capsys.readouterr().out
