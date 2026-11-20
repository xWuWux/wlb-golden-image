"""Testy jawnej flagi produkcyjnej Packera (#277-S3).

Produkcja nie może polegać na domyślnej wartości roli/group_vars: każdy wariant obrazu
przekazuje do Ansible `wlb_enable_e2e_target` wyliczone z profilu budowy, a profil
produkcyjny (domyślny) wymusza false. Profil testowy ustawia wyłącznie CI.
"""

import re

from conftest import REPO_ROOT

PACKER = REPO_ROOT / "packer"
PRODUCTION_VARIANTS = (
    "wlb-general.pkr.hcl",
    "wlb-memory.pkr.hcl",
    "wlb-radiologia.pkr.hcl",
    "wlb-histologia.pkr.hcl",
)
TEST_FLAVORS = ("wlb-memory", "wlb-radiologia", "wlb-histologia")
GATE = "wlb_enable_e2e_target=${local.wlb_e2e_target_enabled}"


def test_kazdy_wariant_przekazuje_jawna_bramke():
    for name in PRODUCTION_VARIANTS:
        text = (PACKER / name).read_text(encoding="utf-8")
        assert GATE in text, f"{name}: brak jawnej bramki {GATE}"
        assert "wlb_enable_e2e_target=${var.wlb_enable_e2e_target}" not in text, (
            f"{name}: surowa zmienna omija profil production/test"
        )


def test_profil_produkcyjny_jest_domyslny_i_wylacza_e2e():
    text = (PACKER / "variables.pkr.hcl").read_text(encoding="utf-8")
    profile = re.search(r'variable "wlb_build_profile"\s*\{(?P<body>.*?)\n\}', text, re.S)
    assert profile, "brak zmiennej wlb_build_profile"
    assert re.search(r'default\s*=\s*"production"', profile.group("body")), "profil produkcyjny musi być domyślny"
    assert re.search(r'contains\(\["production", "test"\]', profile.group("body")), (
        "profil musi walidować dozwolone wartości"
    )
    assert 'var.wlb_build_profile == "test" ? var.wlb_enable_e2e_target : false' in text, (
        "produkcja musi jawnie wymuszać false, niezależnie od wlb_enable_e2e_target"
    )


def test_produkcyjne_buildy_packera_jawnie_wylaczaja_e2e():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "-var wlb_build_profile=production" in makefile
    assert "-var wlb_enable_e2e_target=false" in makefile

    integration = (REPO_ROOT / "ci/integration.sh").read_text(encoding="utf-8")
    assert integration.count("wlb_build_profile=production") == 1, "baza CI musi być produkcją"
    assert integration.count('-var "wlb_enable_e2e_target=false"') == 1, "baza CI musi jawnie wyłączyć E2E"
    assert integration.count("wlb_build_profile=test") == len(TEST_FLAVORS), (
        "każdy flavor testowy musi jawnie zadeklarować profil test"
    )
