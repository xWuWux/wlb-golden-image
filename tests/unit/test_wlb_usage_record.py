"""Pokrycie gałęzi writera rekordu użycia (#98). Kontrakt: null+powod zamiast zera,
walidacja tozsamosci probki (boot/okno), JSON zawsze caly do sparsowania."""

import json

import pytest
from conftest import REPO_ROOT, load_script


@pytest.fixture
def writer():
    return load_script("wlb_usage_record", REPO_ROOT / "ansible/roles/tljh/files/wlb-usage-record")


# --- nonneg_int ---------------------------------------------------------------


def test_nonneg_int_poprawna(writer):
    assert writer.nonneg_int("42") == 42


@pytest.mark.parametrize("zle", ["", " x", "[not set]", "1.5", "-3", "18446744073709551615"])
def test_nonneg_int_odrzucenia(writer, zle):
    assert writer.nonneg_int(zle) is None


# --- iso / boot_id ------------------------------------------------------------


def test_iso_zero_to_none(writer):
    assert writer.iso(None) is None
    assert writer.iso(0).endswith("Z")


def test_boot_id_z_pliku_i_brak_pliku(writer, tmp_path, monkeypatch):
    f = tmp_path / "boot_id"
    f.write_text(" abcd \n", encoding="utf-8")
    monkeypatch.setenv("WLB_BOOT_ID_FILE", str(f))
    assert writer.current_boot_id() == "abcd"
    monkeypatch.setenv("WLB_BOOT_ID_FILE", str(tmp_path / "nie-ma"))
    assert writer.current_boot_id() == ""


# --- read_sample --------------------------------------------------------------


def test_read_sample_brak_pliku(writer, tmp_path):
    assert writer.read_sample(tmp_path, "jupyter-x.service") == {}


def test_read_sample_pomija_wiersze_bez_equal(writer, tmp_path):
    (tmp_path / "jupyter-x.service.kv").write_text("BootID=b1\nbez-znaku\nMemoryPeak=7\n", encoding="utf-8")
    assert writer.read_sample(tmp_path, "jupyter-x.service") == {"BootID": "b1", "MemoryPeak": "7"}


# --- match_sample -------------------------------------------------------------


@pytest.fixture
def ok_sample(writer, tmp_path, monkeypatch):
    monkeypatch.setenv("WLB_BOOT_ID_FILE", str(tmp_path / "b"))
    (tmp_path / "b").write_text("b1\n", encoding="utf-8")
    return {"BootID": "b1", "SampledAtEpoch": "1000"}


def test_match_ok_i_powody(writer, ok_sample, tmp_path):
    ok, why = writer.match_sample(ok_sample, 900, 1100)
    assert ok and why == []
    assert writer.match_sample({}, 900, 1100) == (False, ["sample_missing"])
    other = {"BootID": "INNY", "SampledAtEpoch": "1000"}
    assert writer.match_sample(other, 900, 1100) == (False, ["sample_from_other_boot"])
    assert writer.match_sample(ok_sample, None, None)[1] == ["sample_window_unknown"]
    assert "sample_untimestamped" in writer.match_sample({"BootID": "b1"}, 900, 1100)[1]
    assert "sample_outside_session_window" in writer.match_sample(ok_sample, 5000, 6000)[1]


# --- build_record -------------------------------------------------------------


@pytest.fixture
def z_sandboxem(writer, tmp_path, monkeypatch):
    run, out, boot = tmp_path / "run", tmp_path / "out", tmp_path / "b"
    boot.write_text("b1\n", encoding="utf-8")
    monkeypatch.setenv("WLB_BOOT_ID_FILE", str(boot))
    monkeypatch.setenv("WLB_USAGE_RUN_DIR", str(run))
    monkeypatch.setenv("WLB_USAGE_OUT_DIR", str(out))
    return run, out


def test_build_complete(writer, z_sandboxem):
    run, _ = z_sandboxem
    run.mkdir()
    (run / "jupyter-a.service.kv").write_text(
        "BootID=b1\nSampledAtEpoch=1000\nInvocationID=inv\n"
        "MemoryPeak=100\nCPUUsageNSec=2000000000\nCPUIntervalMax=1.250000\n",
        encoding="utf-8",
    )
    rec = writer.build_record("jupyter-a.service", "sid", "lab", "spawner_env", 900, 1100, 200)
    assert rec["status"] == "complete"
    assert rec["cpu_interval_max_cores"] == 1.25
    assert rec["cpu_time_seconds"] == 2.0
    assert rec["user"] == "jupyter-a"
    assert rec["sample"]["invocation_id"] == "inv"


def test_build_bledny_interval_partial(writer, z_sandboxem):
    run, _ = z_sandboxem
    run.mkdir()
    (run / "jupyter-b.service.kv").write_text(
        "BootID=b1\nSampledAtEpoch=1000\nMemoryPeak=1\nCPUUsageNSec=1\nCPUIntervalMax=NIE\n", encoding="utf-8"
    )
    rec = writer.build_record("jupyter-b.service", "s", "l", "hub_env", 900, 1100, 100)
    assert "cpu_interval_unavailable" in rec["quality"]
    assert rec["status"] == "partial"
    assert rec["cpu_interval_max_cores"] is None


def test_build_brak_probki(writer, z_sandboxem):
    rec = writer.build_record("jupyter-c.service", "s", "", "missing", 900, 1100, 100)
    assert rec["status"] == "no_samples"
    assert rec["lab"] is None and rec["lab_source"] == "missing"


# --- main ---------------------------------------------------------------------


def test_main_za_malo_argumentow(writer, z_sandboxem):
    _, out = z_sandboxem
    assert writer.main(["wlb-usage-record", "jupyter-d.service"]) == 2
    assert not out.exists()


def test_main_sciezka_szczesliwa_i_domyjslny_lab_source(writer, z_sandboxem, capsys):
    run, out = z_sandboxem
    run.mkdir()
    (run / "jupyter-e.service.kv").write_text(
        "BootID=b1\nSampledAtEpoch=1000\nMemoryPeak=9\nCPUUsageNSec=1\n", encoding="utf-8"
    )
    assert writer.main(["w", "jupyter-e.service", "s", "lab", "900", "1100", "200"]) == 0
    plik = next(out.glob("usage-*.jsonl"))
    rec = json.loads(plik.read_text(encoding="utf-8"))
    assert rec["status"] == "complete"
    assert rec["lab_source"] == "unknown"  # brak 8. argumentu — brak domyslania
