"""Testy testu dryfu zamrożonych wersji Pythona (etap 5).

Regresja z CI: `markupsafe` bywa zainstalowany przez conda (zależność `jinja2`) albo przez pip
(stos Jupyter/TLJH). Dawniej ta sama wersja w innym dziale dawała dwa sprzeczne komunikaty
i czerwony etap; teraz migracja menedżera jest uwagą, a dryf wersji wciąż failuje.
"""

import lock_drift as drift


def lock(conda=(), pip=()):
    deps = list(conda)
    if pip:
        deps.append({"pip": list(pip)})
    return {"dependencies": deps}


def test_migracja_menedżera_ta_sama_wersja_nie_jest_dryfem():
    repo = lock(conda=["jinja2=3.1.6"], pip=["markupsafe==3.0.4"])
    obraz = lock(conda=["jinja2=3.1.6", "markupsafe=3.0.4"])
    problemy, uwagi = drift.compare(repo, obraz)
    assert problemy == []
    assert uwagi == ["Python: markupsafe 3.0.4 — zmienił menedżera pip → conda, wersja bez zmian"]


def test_stary_pin_to_dryf_jedna_linia_z_kierunkiem_menedzera():
    repo = lock(conda=["markupsafe=3.0.3"])
    obraz = lock(pip=["markupsafe==3.0.4"])
    problemy, uwagi = drift.compare(repo, obraz)
    assert uwagi == []
    assert problemy == ["Python: markupsafe — lock 3.0.3, obraz 3.0.4 (conda → pip)"]


def test_rożna_wersja_w_tym_samym_dziale_to_dryf():
    problemy, _ = drift.compare(lock(conda=["numpy=1.26.4"]), lock(conda=["numpy=2.1.0"]))
    assert problemy == ["Python: numpy — lock 1.26.4, obraz 2.1.0"]


def test_pakiet_usunięty_lub_nowy_w_obrazie_to_dryf():
    repo = lock(conda=["pandas=2.2.3", "scipy=1.14.1"])
    obraz = lock(conda=["pandas=2.2.3", "polars=1.9.0"])
    problemy, _ = drift.compare(repo, obraz)
    assert problemy == [
        "Python: polars 1.9.0 tylko w obrazie (conda)",
        "Python: scipy 1.14.1 tylko w locku (conda)",
    ]


def test_wielkosc_znakow_i_podkreślnik_nie_mylą_nazw():
    repo = lock(conda=["Jinja2=3.1.6", "zope_interface=6.4"])
    obraz = lock(conda=["jinja2=3.1.6", "zope-interface=6.4"])
    assert drift.compare(repo, obraz) == ([], [])


def test_ten_sam_pakiet_w_obu_dzialach_to_dryf():
    both = lock(conda=["markupsafe=3.0.4"], pip=["markupsafe==3.0.4"])
    problemy, uwagi = drift.compare(both, both)
    assert problemy == ["Python: markupsafe — ten sam pakiet w działach conda i pip"]
    assert uwagi == []


def test_wersja_nieokreślona_to_uwaga_a_nie_dryf():
    problemy, uwagi = drift.compare(lock(conda=["bez-wersji"]), lock(conda=["bez-wersji=1.0"]))
    assert problemy == []
    assert uwagi == ["Python: bez-wersji — wersja nieokreślona w locku albo w obrazie"]


def test_build_pip_zakresy_i_markery_sredowiska_pominiete():
    conda, pip = drift.sections(lock(pip=["jupyterhub==5.5.2", "pakiet>=1.0", "-e .", "# komentarz"]))
    assert conda == {}
    assert pip == {"jupyterhub": ("jupyterhub", "5.5.2")}


def test_main_wypisuje_dryf_i_zwraca_1(tmp_path, capsys):
    (tmp_path / "repo.yml").write_text("dependencies:\n  - numpy=1.26.4\n")
    (tmp_path / "obraz.yml").write_text("dependencies:\n  - numpy=2.1.0\n")
    assert drift.main([str(tmp_path / "repo.yml"), str(tmp_path / "obraz.yml")]) == 1
    assert "DRYF: Python: numpy — lock 1.26.4, obraz 2.1.0" in capsys.readouterr().out


def test_main_zielony_zwraca_0_i_migracje_jako_uwagę(tmp_path, capsys):
    (tmp_path / "repo.yml").write_text("dependencies:\n  - pip:\n      - markupsafe==3.0.4\n")
    (tmp_path / "obraz.yml").write_text("dependencies:\n  - markupsafe=3.0.4\n")
    assert drift.main([str(tmp_path / "repo.yml"), str(tmp_path / "obraz.yml")]) == 0
    out = capsys.readouterr().out
    assert "uwaga: Python: markupsafe 3.0.4 — zmienił menedżera pip → conda" in out
    assert "DRYF" not in out
