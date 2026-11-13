"""Testy parsera raportu Lynis do podsumowania etapu 5 (#11) i bramki regresji (#288), bez VM."""

from pathlib import Path

import lynis_report as lr

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "lynis-report.dat"

SAMPLE = """\
# Lynis report
lynis_version=3.0.9
hardening_index=67
warning[]=Found some information in dmesg|KRNL-5788|-|-
warning[]=iptables module loaded but no rules active|FIRE-4512|-|-
suggestion[]=Consider hardening SSH configuration|SSH-7408|Details here|text:Run tool
suggestion[]=Install a file integrity tool|FINT-4350|-|-
suggestion[]=Harden compilers|HRDN-7222|-|-
plugin_firewall=ok
"""


def test_parsuje_hardening_index_i_liczby():
    data = lr.parse_report(SAMPLE)
    assert data["hardening_index"] == 67
    assert len(data["warnings"]) == 2
    assert len(data["suggestions"]) == 3


def test_wyciaga_komunikat_i_identyfikator_testu():
    data = lr.parse_report(SAMPLE)
    w = data["warnings"][1]
    assert w["msg"] == "iptables module loaded but no rules active"
    assert w["test"] == "FIRE-4512"
    s = data["suggestions"][0]
    assert s["msg"] == "Consider hardening SSH configuration"
    assert s["test"] == "SSH-7408"


def test_brak_hardening_index_nie_wywala():
    data = lr.parse_report("warning[]=coś|XXX-1234|-|-\n")
    assert data["hardening_index"] is None
    assert len(data["warnings"]) == 1


def test_puste_wejscie():
    data = lr.parse_report("")
    assert data == {"hardening_index": None, "warnings": [], "suggestions": []}


def test_markdown_zawiera_index_i_sekcje():
    md = lr.render_markdown(lr.parse_report(SAMPLE))
    assert "Hardening index: **67 / 100**" in md
    assert "ostrzeżenia: **2**" in md
    assert "sugestie: **3**" in md
    assert "Consider hardening SSH configuration [SSH-7408]" in md
    assert "### Utwardzenie systemu — Lynis" in md


def test_markdown_ogranicza_liczbe_sugestii():
    data = {"hardening_index": 50, "warnings": [], "suggestions": [{"msg": f"s{i}", "test": ""} for i in range(30)]}
    md = lr.render_markdown(data, max_suggestions=25)
    assert "pokazano 25 z 30" in md
    assert "- s24" in md
    assert "- s25" not in md


def test_brak_pliku_to_nie_blad(tmp_path):
    rc = lr.main(["lynis_report.py", str(tmp_path / "nie-ma.dat")])
    assert rc == 0


def test_fixture_baseline_przechodzi_bramke():
    data = lr.parse_report(FIXTURE.read_text(encoding="utf-8"))
    assert data["hardening_index"] == lr.DEFAULT_BASELINE
    assert data["warnings"] == []
    assert lr.gate_failures(data) == []
    assert lr.main(["lynis_report.py", "--gate", str(FIXTURE)]) == 0


def test_bramka_wykrywa_regresje_indexu(tmp_path):
    report = tmp_path / "lynis-report.dat"
    report.write_text("hardening_index=71\n", encoding="utf-8")
    data = lr.parse_report(report.read_text(encoding="utf-8"))
    assert lr.gate_failures(data) == ["hardening index 71 < baseline 72"]
    assert lr.main(["lynis_report.py", "--gate", str(report)]) == 1


def test_bramka_wykrywa_kazde_ostrzezenie(tmp_path):
    report = tmp_path / "lynis-report.dat"
    report.write_text(
        "hardening_index=80\nwarning[]=iptables bez reguł|FIRE-4512|-|-\n",
        encoding="utf-8",
    )
    failures = lr.gate_failures(lr.parse_report(report.read_text(encoding="utf-8")))
    assert failures == ["ostrzeżenie Lynis: iptables bez reguł [FIRE-4512]"]
    assert lr.main(["lynis_report.py", "--gate", str(report)]) == 1


def test_bramka_brak_indexu_i_brak_raportu(tmp_path):
    assert lr.gate_failures({"hardening_index": None, "warnings": [], "suggestions": []}) == [
        "brak hardening_index w raporcie (raport niekompletny)"
    ]
    # fail-closed: przy włączonej bramce brak artefaktu nie może po cichu przejść
    assert lr.main(["lynis_report.py", "--gate", str(tmp_path / "nie-ma.dat")]) == 1


def test_bramka_baseline_z_cli(tmp_path):
    report = tmp_path / "lynis-report.dat"
    report.write_text("hardening_index=72\n", encoding="utf-8")
    assert lr.main(["lynis_report.py", "--gate", "--baseline", "70", str(report)]) == 0
    assert lr.main(["lynis_report.py", "--gate", "--baseline", "80", str(report)]) == 1


def test_bramka_odrzuca_bledne_argumenty(tmp_path):
    report = tmp_path / "lynis-report.dat"
    report.write_text("hardening_index=72\n", encoding="utf-8")
    assert lr.main(["lynis_report.py", "--baseline"]) == 2
    assert lr.main(["lynis_report.py", "--baseline", "abc", str(report)]) == 2
    assert lr.main(["lynis_report.py", "--nieznana", str(report)]) == 2
    assert lr.main(["lynis_report.py", str(report), str(report)]) == 2
    assert lr.main(["lynis_report.py"]) == 2


def test_markdown_tryb_bramki():
    md = lr.render_markdown(lr.parse_report("hardening_index=72\n"), gating=True)
    assert "Bramka regresji" in md
    assert "Raport przeglądowy" not in md
