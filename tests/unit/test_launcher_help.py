"""Walidacja treści pomocy Launchera w ŹRÓDLE (#54/#84).

Treść `pomoc.md` i kafelek pomocy w `jp_app_launcher.yaml` były dotąd sprawdzane tylko w akceptacji
na KVM (etap 5, `tests/acceptance-remote.sh` 5b). Po #84 zmiana samej treści tych plików tekstowych NIE
wyzwala etapu 5 (allowlista `ci/changes.sh`), więc pokrycie #54 przenosimy tu — do szybkiego etapu 4,
sprawdzając plik źródłowy wgrywany do obrazu przez rolę `tljh`. Akceptacja dalej sprawdza WDROŻONY plik,
gdy etap 5 i tak biegnie.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "ansible/roles/tljh/files/launcher"


def test_pomoc_ma_kontakt_helpdesku():
    # Dokładnie ten sam kontakt, którego grepuje akceptacja 5b (#54).
    pomoc = (LAUNCHER / "pomoc.md").read_text(encoding="utf-8")
    assert "helpdesk@gumed.edu.pl" in pomoc


def test_launcher_ma_kafelek_pomocy():
    # Kafelek "Pomoc i zgłoszenia" w konfiguracji Launchera (#54) — jak w akceptacji 5b.
    cfg = (LAUNCHER / "jp_app_launcher.yaml").read_text(encoding="utf-8")
    assert "Pomoc i zgłoszenia" in cfg
