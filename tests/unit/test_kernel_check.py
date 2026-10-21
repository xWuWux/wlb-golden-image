"""Testy kryterium „jedno jądro w obrazie" (#9) — parsowanie dpkg-status, bez VM."""

import kernel_check as kc


def stanza(pkg, status="install ok installed"):
    return f"Package: {pkg}\nStatus: {status}\nVersion: 1\n"


def dpkg(*pkgs):
    # realistyczny fragment /var/lib/dpkg/status: stanzy oddzielone pustą linią
    return "\n".join(stanza(p) for p in pkgs)


ONE = (
    "linux-image-6.8.0-142-generic",
    "linux-modules-6.8.0-142-generic",
    "linux-headers-6.8.0-142-generic",
    "linux-tools-6.8.0-142",
    "linux-tools-6.8.0-142-generic",
    # meta-pakiety bez wersji — muszą być ignorowane
    "linux-image-virtual",
    "linux-tools-common",
    "linux-generic",
)

TWO = (*ONE, "linux-image-6.8.0-139-generic", "linux-modules-6.8.0-139-generic")


def test_jedno_jadro_ok():
    vers, problems = kc.check(dpkg(*ONE))
    assert problems == []
    assert vers["linux-image"] == {"6.8.0-142"}
    assert vers["linux-tools"] == {"6.8.0-142"}


def test_meta_pakiety_ignorowane():
    vers, _ = kc.check(dpkg(*ONE))
    # linux-image-virtual / linux-tools-common / linux-generic nie dokładają wersji
    assert all(len(v) <= 1 for v in vers.values())


def test_dwa_jadra_wykryte():
    _vers, problems = kc.check(dpkg(*TWO))
    rodziny = dict(problems)
    assert rodziny["linux-image"] == ["6.8.0-139", "6.8.0-142"]
    assert rodziny["linux-modules"] == ["6.8.0-139", "6.8.0-142"]


def test_pakiet_niezainstalowany_nie_liczy_sie():
    text = (
        stanza("linux-image-6.8.0-142-generic")
        + "\n"
        + stanza("linux-image-6.8.0-139-generic", status="deinstall ok config-files")
    )
    vers, problems = kc.check(text)
    assert problems == []
    assert vers["linux-image"] == {"6.8.0-142"}


def test_modules_extra_rozpoznane_odrebnie():
    vers, _ = kc.check(dpkg("linux-modules-extra-6.8.0-142-generic"))
    assert vers["linux-modules-extra"] == {"6.8.0-142"}
    assert vers["linux-modules"] == set()


def test_main_kod_wyjscia(tmp_path):
    good = tmp_path / "good"
    good.write_text(dpkg(*ONE), encoding="utf-8")
    assert kc.main(["kernel_check.py", str(good)]) == 0
    bad = tmp_path / "bad"
    bad.write_text(dpkg(*TWO), encoding="utf-8")
    assert kc.main(["kernel_check.py", str(bad)]) == 1


def test_brak_pliku_to_nie_blad(tmp_path):
    assert kc.main(["kernel_check.py", str(tmp_path / "nie-ma")]) == 0
