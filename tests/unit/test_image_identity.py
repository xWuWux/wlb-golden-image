"""Testy walidatora tozsamosci OS dla SCA/SBOM (#129).

Strona skanera (HOST_OS_RELEASE) jest w produkcji zawsze /etc/os-release procesu;
testy podmieniaja WYLACZNIE atrybut modulu -- produkcyjne obejscie nie istnieje.
"""

import pytest
from conftest import REPO_ROOT, load_script


@pytest.fixture
def ident():
    return load_script("wlb_image_identity", REPO_ROOT / "ci/image_identity.py")


def osr(tmp_path, body, name="os-release"):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return str(tmp_path / name)


# --- read_os_identity ---------------------------------------------------------


def test_odczyt_cytowany_i_niecytowany(ident, tmp_path):
    p = osr(tmp_path, 'ID="Ubuntu"\nVERSION_ID=24.04\n# komentarz\nVERSION_CODENAME=noble\n')
    got = ident.read_os_identity(p)
    assert (got.id, got.version_id) == ("ubuntu", "24.04")  # casefold normalizuje ID


def test_brak_klucza_lub_wartosci(ident, tmp_path):
    with pytest.raises(ident.IdentityError, match="VERSION_ID"):
        ident.read_os_identity(osr(tmp_path, "ID=ubuntu\n"))
    with pytest.raises(ident.IdentityError, match="ID"):
        ident.read_os_identity(osr(tmp_path, 'ID=""\nVERSION_ID=24.04\n'))


def test_duplikat_wymaganego_klucza_odrzucony(ident, tmp_path):
    with pytest.raises(ident.IdentityError, match="duplikat"):
        ident.read_os_identity(osr(tmp_path, "ID=ubuntu\nID=debian\nVERSION_ID=24.04\n"))


def test_wiersz_bez_rownanosci_i_smieciowa_nazwa_klucza(ident, tmp_path):
    with pytest.raises(ident.IdentityError, match="bez '='"):
        ident.read_os_identity(osr(tmp_path, "ID ubuntu\nVERSION_ID=24.04\n"))
    with pytest.raises(ident.IdentityError, match="nazwa klucza"):
        ident.read_os_identity(osr(tmp_path, "id=ubuntu\nVERSION_ID=24.04\n"))


def test_tekst_przypominajacy_polecenie_nie_jest_wykonywany(ident, tmp_path):
    marker = tmp_path / "PWNED"
    ident.read_os_identity(osr(tmp_path, f"ID=$(touch {marker})\nVERSION_ID=24.04\n"))
    assert not marker.exists()


def test_plik_nieczytal_brak(ident, tmp_path):
    with pytest.raises(ident.IdentityError, match="nie da sie odczytac"):
        ident.read_os_identity(str(tmp_path / "os-release"))


# --- validate_scan_identity ---------------------------------------------------


def test_para_identyczna_wspierana_przechodzi(ident):
    o = ident.OsIdentity(id="ubuntu", version_id="24.04")
    ident.validate_scan_identity(o, o)
    assert o.label() == "ubuntu 24.04"


def test_ten_sam_version_id_inna_dystrybucja_odrzucona(ident):
    other = ident.OsIdentity(id="debian", version_id="24.04")
    with pytest.raises(ident.IdentityError, match="poza wspieranym"):
        ident.validate_scan_identity(other, other)


def test_niezgodnosc_wydania_odrzucona_przed_skanem(ident):
    img = ident.OsIdentity(id="ubuntu", version_id="24.04")
    scan = ident.OsIdentity(id="ubuntu", version_id="26.04")
    with pytest.raises(ident.IdentityError, match="zlym ekosystemie"):
        ident.validate_scan_identity(img, scan)


# --- CLI ----------------------------------------------------------------------


def test_main_za_malo_argumentow(ident):
    assert ident.main(["image_identity.py"]) == 2


def test_main_sciezka_szczesliwa_przez_monkeypatch_scanera(ident, tmp_path, monkeypatch):
    host = tmp_path / "host-os-release"
    host.write_text("ID=ubuntu\nVERSION_ID=24.04\n", encoding="utf-8")
    monkeypatch.setattr(ident, "HOST_OS_RELEASE", str(host))
    art = tmp_path / "art"
    art.mkdir()
    osr(art, "ID=ubuntu\nVERSION_ID=24.04\n")
    assert ident.main(["image_identity.py", str(art)]) == 0
    assert ident.main(["image_identity.py", str(art) + "/"]) == 0  # kosmiczny ukośnik


def test_main_niezgodnosc_wychodzi_2_kodem(ident, tmp_path, monkeypatch, capsys):
    host = tmp_path / "host-os-release"
    host.write_text("ID=ubuntu\nVERSION_ID=26.04\n", encoding="utf-8")
    monkeypatch.setattr(ident, "HOST_OS_RELEASE", str(host))
    art = tmp_path / "art2"
    art.mkdir()
    osr(art, "ID=ubuntu\nVERSION_ID=24.04\n")
    assert ident.main(["image_identity.py", str(art)]) == 2
    assert "#129" in capsys.readouterr().err
