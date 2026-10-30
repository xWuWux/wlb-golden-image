"""Walidacja odpowiedzi eksportera, także błędów i etykiet."""

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("metrics_check", ROOT / "ci/metrics_check.py")
metrics_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics_check)
CONTRACT = yaml.safe_load((ROOT / "observability/contract.yml").read_text())


def valid():
    return "\n".join(f"{selector} 1" for selector in CONTRACT["metrics"]["selectors"]) + "\n"


def test_contract_matches_source():
    assert metrics_check.check_static(CONTRACT) == []
    assert metrics_check.check(valid(), CONTRACT) == []


def test_rejects_missing_duplicate_and_failed_measurement():
    data = valid().replace("wlb_health_queue_collect_success 1", "wlb_health_queue_collect_success 0")
    data += "wlb_health_queue_collect_success 1\n"
    errors = metrics_check.check(data, CONTRACT)
    assert any("duplikat" in error for error in errors)
    missing = valid().replace("wlb_export_queue_bundles 1\n", "")
    assert any("wlb_export_queue_bundles" in error for error in metrics_check.check(missing, CONTRACT))
    failed = valid().replace("wlb_health_queue_collect_success 1", "wlb_health_queue_collect_success 0")
    assert any("nieudany" in error for error in metrics_check.check(failed, CONTRACT))


def test_numeric_formats_and_unknown_labels():
    data = valid().replace("wlb_health_timestamp_seconds 1", "wlb_health_timestamp_seconds 1.79e+09")
    assert metrics_check.check(data, CONTRACT) == []
    assert metrics_check.check(data.replace("1.79e+09", "NaN"), CONTRACT)
    assert metrics_check.check(data + 'wlb_health_auditd_active{user="private"} 1\n', CONTRACT)


def test_static_rejects_duplicates_unknown_metric_and_endpoint():
    contract = {"metrics": dict(CONTRACT["metrics"])}
    contract["metrics"]["selectors"] = ["does_not_exist", "does_not_exist"]
    contract["metrics"]["endpoint"] = "http://0.0.0.0:9100/metrics"
    assert len(metrics_check.check_static(contract)) == 4
    assert metrics_check.check("", contract)


def test_invalid_value_and_boolean():
    assert metrics_check.check(valid().replace("wlb_health_auditd_active 1", "wlb_health_auditd_active 2"), CONTRACT)
    assert metrics_check.check(
        valid().replace("wlb_health_auditd_active 1", "wlb_health_auditd_active invalid"), CONTRACT
    )
    assert metrics_check.check("# comment\nnode_cpu 1\n" + valid(), CONTRACT) == []


def test_main(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(metrics_check.sys, "argv", ["metrics_check"])
    assert metrics_check.main() == 2
    monkeypatch.setattr(metrics_check.sys, "argv", ["metrics_check", "--static"])
    assert metrics_check.main() == 0
    path = tmp_path / "metrics"
    path.write_text(valid())
    monkeypatch.setattr(metrics_check.sys, "argv", ["metrics_check", str(path)])
    assert metrics_check.main() == 0
    path.write_text("bad\n")
    assert metrics_check.main() == 1
    assert "brak" in capsys.readouterr().err
