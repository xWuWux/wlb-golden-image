"""Kontrakt zmiennych wdrożeniowych: /etc/wlb/lab.env ↔ wlb-firstboot ↔ przykłady cloud-init.

Obraz buduje się raz, a stawia wiele razy — parametry per Laboratorium idą przez `lab.env`.
Rozjazd między kodem a przykładami jest cichy: VM wstanie, tylko z innym zachowaniem niż
opisuje dokumentacja. Dlatego kontrakt jest testem, a nie konwencją.
"""

import shutil
from pathlib import Path

import pytest

import deployment_vars as dv

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- kontrakt zmiennych wdrożeniowych (#180) ---


@pytest.fixture
def repo(tmp_path):
    """Minimalny obraz: firstboot + oba pliki przykładów, które testy mogą psuć."""
    shutil.copytree(REPO_ROOT / "ansible", tmp_path / "ansible")
    (tmp_path / "cloud-init").mkdir()
    shutil.copy(REPO_ROOT / dv.ENV_EXAMPLE, tmp_path / dv.ENV_EXAMPLE)
    shutil.copy(REPO_ROOT / dv.USERDATA_EXAMPLE, tmp_path / dv.USERDATA_EXAMPLE)
    return tmp_path


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def errors(repo: Path) -> list[str]:
    return dv.check(repo)


def test_repozytorium_jest_zgodne_z_kontraktem():
    assert errors(REPO_ROOT) == []


def test_nowa_zmienna_w_kodzie_bez_dokumentacji(repo):
    edit(
        repo / dv.FIRSTBOOT,
        "SIEM_TLS=${SIEM_TLS:-1}",
        "SIEM_TLS=${SIEM_TLS:-1}\nNOWA_ZMIENNA=${NOWA_ZMIENNA:-7}",
    )
    assert any(
        "NOWA_ZMIENNA: czytana przez wlb-firstboot (domyślnie '7'), brak we cloud-init/lab.env.example" in e
        for e in errors(repo)
    )


def test_zmienna_opisana_ale_nie_czytana(repo):
    edit(repo / dv.ENV_EXAMPLE, "LOCAL_TEST_MODE=0", "LOCAL_TEST_MODE=0\nZNIKNIK=1")
    assert any(
        "ZNIKNIK: opisana we cloud-init/lab.env.example, ale wlb-firstboot nigdy jej nie czyta" in e
        for e in errors(repo)
    )


def test_wymagana_zmienna_bez_dokumentacji_jest_zglaszana_jako_wymagana(repo):
    edit(repo / dv.ENV_EXAMPLE, "LAB_NAME=lab-example01", "")
    assert any("LAB_NAME: czytana przez wlb-firstboot (wymagana)" in e for e in errors(repo))


def test_przekazywana_zmienna_bez_dzialajacego_przykladu(repo):
    edit(repo / dv.USERDATA_EXAMPLE, "      AUTH_MODE=native\n", "")
    assert any(
        "AUTH_MODE: przekazywana we cloud-init/lab.env.example, ale brak w przykładzie /etc/wlb/lab.env" in e
        for e in errors(repo)
    )


def test_przyklad_uzywa_nieudokumentowanej_zmiennej(repo):
    edit(repo / dv.USERDATA_EXAMPLE, "      AUTH_MODE=native\n", "      AUTH_MODE=native\n      DZIWNA=1\n")
    assert any("DZIWNA: użyta w cloud-init/lab-user-data.example.yaml, nieznana we" in e for e in errors(repo))


def test_wzorzec_opcjonalny_nie_musi_byc_przekazany(repo):
    """`#RESEARCHER_MEM_LIMIT=16G` dokumentuje domyślną — brak wpisu w write_files jest OK."""
    assert not any("RESEARCHER_MEM_LIMIT" in e for e in errors(repo))


def test_rozna_wartosc_domyslna_w_wzorze_i_w_kodzie(repo):
    edit(repo / dv.ENV_EXAMPLE, "SIEM_TLS=1", "#SIEM_TLS=0")
    edit(repo / dv.ENV_EXAMPLE, "HUB_TLS=1", "SIEM_TLS=0\nHUB_TLS=1")
    assert any(
        "SIEM_TLS: inna wartość domyślna w kodzie i w dokumentacji (wlb-firstboot: '1'" in e for e in errors(repo)
    )


def test_aktywny_wpis_wygywa_zakomentowany_wzor(repo):
    """Komentarz prozą opisujący wyjątek nie może udawać wartości dokumentacji."""
    edit(
        repo / dv.ENV_EXAMPLE,
        "SIEM_TLS=1",
        "# Uwaga: #SIEM_TLS=0 wyłącznie na jawną decyzję administratora\nSIEM_TLS=1",
    )
    assert errors(repo) == []


def test_pusta_wartosc_domyslna_nie_jest_porownywana(repo):
    """`${EGRESS_ALLOW:-}` = puste znaczy „wyłączone”, więc wartość przykładowa jest dowolna."""
    edit(repo / dv.ENV_EXAMPLE, 'EGRESS_ALLOW="10.20.0.10:3128 10.30.0.5:5432"', "EGRESS_ALLOW=")
    assert not any("EGRESS_ALLOW" in e for e in errors(repo))


def test_wspolne_zmienne_obrazu_sa_poza_kontraktem():
    """`WLB_*` z image.conf nie są parametrami wdrożenia — kontrakt ich nie zgłasza."""
    text = "HUB_URL=${WLB_HUB_URL:-http://127.0.0.1}\nENV_FILE=${WLB_ENV_FILE:-/etc/wlb/lab.env}\n"
    assert dv.firstboot_vars(text) == {}


def test_wartosc_z_komentarzem_i_cudzyslowem():
    assert dv._strip_comment("6514                      # domyślnie przy TLS") == "6514"
    assert dv._strip_comment('"localhost,127.0.0.1"') == "localhost,127.0.0.1"
    assert dv._strip_comment("1 only") == "1 only"


def test_warianty_opcjonalne_z_katalogu_examples(repo):
    """Przykłady są rozdzielone: OIDC żyje w `cloud-init/examples/*.yaml`, nie w user-data."""
    (repo / "cloud-init/examples").mkdir()
    (repo / "cloud-init/examples/lab-user-data-oidc.yaml").write_text(
        "#cloud-config\n"
        "write_files:\n"
        "  - path: /etc/wlb/lab.env\n"
        "    content: |\n"
        "      AUTH_MODE=oidc\n"
        "      OIDC_CLIENT_ID=wlb\n"
        "      #OIDC_CLIENT_SECRET=\n",
        encoding="utf-8",
    )
    found = dv.userdata_labenv(repo)
    assert found["OIDC_CLIENT_ID"].value == "wlb"
    assert "OIDC_CLIENT_SECRET" not in found  # zakomentowany wzór to nie wartość


def test_brak_przykladu_wdrozenia_to_brak_zmiennych(tmp_path):
    assert dv.userdata_labenv(tmp_path) == {}


def test_main_zwraca_jeden_przy_rozbieznosci(repo, capsys):
    edit(repo / dv.ENV_EXAMPLE, "LOCAL_TEST_MODE=0", "LOCAL_TEST_MODE=0\nZNIKNIK=1")
    assert dv.main(["--root", str(repo)]) == 1
    assert "ZNIKNIK" in capsys.readouterr().out


def test_main_zwraca_zero_przy_zgodnosci(capsys):
    assert dv.main(["--root", str(REPO_ROOT)]) == 0
    assert "zgodne" in capsys.readouterr().out
