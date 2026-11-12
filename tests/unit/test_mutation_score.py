"""Testy oceny mutacji dla etapu 4b (ci/mutation_score.py).

Kluczowa decyzja z review: mianownik progu = killed + unlisted. Allowlisted survivory są
równoważne, więc nie zaniżają wyniku; unlisted nadal czerwieni.
"""

from ci import mutation_score as ms


def statuses(**counts: int) -> dict[str, list[str]]:
    return {status: [f"{status}-{i}" for i in range(count)] for status, count in counts.items()}


def test_allowlisted_nie_zbija_progu():
    score = ms.evaluate(
        statuses(killed=1, survived=5), {"survived-0", "survived-1", "survived-2", "survived-3", "survived-4"}, []
    )
    assert score.percent == 100.0
    assert score.failures(85.0) == []


def test_szesnascie_killed_cztery_allowed_to_100_proc():
    allowed = {"survived-0", "survived-1", "survived-2", "survived-3"}
    score = ms.evaluate(statuses(killed=16, survived=4), allowed, [])
    assert score.scored == 16
    assert score.percent == 100.0
    assert score.failures(85.0) == []


def test_unlisted_liczy_sie_do_mianownika_i_czerwieni():
    score = ms.evaluate(statuses(killed=1, survived=1), set(), [])
    assert score.percent == 50.0
    assert any("spoza allowlisty" in f for f in score.failures(85.0))
    assert any("< 85%" in f for f in score.failures(85.0))


def test_no_tests_nie_wchodzi_do_mianownika():
    score = ms.evaluate(statuses(killed=4, survived=0, **{"no tests": 40}), set(), [])
    assert score.scored == 4
    assert score.percent == 100.0
    assert score.no_tests == 40


def test_nieznany_status_to_blad():
    score = ms.evaluate(statuses(killed=1, suspicious=2), set(), [])
    assert score.unknown == {"suspicious": 2}
    assert any("Nieznane statusy" in f for f in score.failures(85.0))


def test_timeout_to_blad():
    score = ms.evaluate(statuses(killed=1, timeout=1), set(), [])
    assert any("timeout" in f for f in score.failures(85.0))


def test_allowlista_bez_uzasadnienia_to_blad():
    score = ms.evaluate(statuses(killed=1), set(), ["allow.txt:2: brak uzasadnienia po #"])
    assert any("bez uzasadnienia" in f for f in score.failures(85.0))


def test_nieaktualna_allowlista_to_ostrzezenie_nie_blad(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text("m-1  # równoważny\n")
    allowed, errors = ms.load_allowlist(path)
    score = ms.evaluate(statuses(killed=2), allowed, errors)
    assert score.stale == ["m-1"]
    assert score.failures(85.0) == []


def test_load_allowlist_pomija_komentarze_i_puste(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text("# nagłówek\n\nm-1  # powód\n")
    allowed, errors = ms.load_allowlist(path)
    assert allowed == {"m-1"}
    assert errors == []


def test_parse_results_radzi_sobie_z_nazwami_i_statusami():
    text = "a.x__mutmut_1: killed\nb.x__mutmut_2: no tests\nc.x__mutmut_3: survived\n"
    assert ms.parse_results(text) == {
        "killed": ["a.x__mutmut_1"],
        "no tests": ["b.x__mutmut_2"],
        "survived": ["c.x__mutmut_3"],
    }


def test_render_zawiera_tabele_i_listy():
    score = ms.evaluate(statuses(killed=1, survived=2), {"survived-0"}, [])
    text = ms.render(score, 85.0)
    assert "| Zabite |" in text
    assert "spoza allowlisty" in text
    assert "`survived-1`" in text


def test_main_zwraca_zero_i_zapisuje_summary(tmp_path):
    results = tmp_path / "results.txt"
    results.write_text("m-1: killed\nm-2: survived\n")
    allow = tmp_path / "allow.txt"
    allow.write_text("m-2  # równoważny\n")
    summary = tmp_path / "summary.md"
    assert (
        ms.main(["--results", str(results), "--allowlist", str(allow), "--minimum", "85", "--summary", str(summary)])
        == 0
    )
    assert "100.0%" in summary.read_text()


def test_main_zwraca_jeden_przy_unlisted(tmp_path, capsys):
    results = tmp_path / "results.txt"
    results.write_text("m-1: killed\nm-2: survived\n")
    allow = tmp_path / "allow.txt"
    allow.write_text("")
    assert ms.main(["--results", str(results), "--allowlist", str(allow), "--minimum", "85"]) == 1
    assert "spoza allowlisty" in capsys.readouterr().err


def test_main_brak_pliku_allowlisty_nie_wysypuje(tmp_path):
    results = tmp_path / "results.txt"
    results.write_text("m-1: killed\n")
    assert ms.main(["--results", str(results), "--allowlist", str(tmp_path / "nie-ma.txt")]) == 0
