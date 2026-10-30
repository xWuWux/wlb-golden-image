"""Bezpieczne agregaty kolejki WLB — brak nazw i brak zerowania błędów."""

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("wlb_health", str(ROOT / "ansible/roles/monitoring/files/wlb-health"))
spec = importlib.util.spec_from_loader(loader.name, loader)
health = importlib.util.module_from_spec(spec)
loader.exec_module(health)


def bundle(queue, name="prywatna-nazwa", size=12):
    directory = queue / name
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": "pending_review",
                "entries": [
                    {"type": "file", "size": size, "path": "dane-wrazliwe"},
                    {"type": "directory", "size": 0, "path": "."},
                ],
            }
        )
    )
    return directory


def test_queue_aggregate_without_entering_incoming(tmp_path):
    bundle(tmp_path)
    (tmp_path / ".incoming.prywatne").mkdir()
    (tmp_path / ".incoming.prywatne" / "source").symlink_to("/etc")
    (tmp_path / ".mover.lock").touch()
    assert health.queue_metrics(tmp_path) == (1, 12, 1)
    result = health.sample(tmp_path)
    assert "wlb_export_queue_bundles 1" in result
    assert "wlb_export_queue_payload_bytes 12" in result
    assert "wlb_export_queue_incoming 1" in result
    assert "prywat" not in result and "dane-wrazliwe" not in result


def test_empty_is_zero_but_missing_is_failure(tmp_path):
    assert health.queue_metrics(tmp_path) == (0, 0, 0)
    result = health.sample(tmp_path / "brak")
    assert "wlb_health_queue_collect_success 0" in result
    assert "wlb_export_queue_bundles" not in result


@pytest.mark.parametrize(
    "invalid", [b"{}", b"[]", b"nie json", b'{"schema_version":1,"state":"pending_review","entries":null}']
)
def test_bad_manifest_fails_closed(tmp_path, invalid):
    directory = bundle(tmp_path)
    (directory / "manifest.json").write_bytes(invalid)
    result = health.sample(tmp_path)
    assert "wlb_health_queue_collect_success 0" in result
    assert "wlb_export_queue_payload_bytes" not in result


def test_manifest_symlink_is_not_followed(tmp_path):
    directory = bundle(tmp_path)
    (directory / "manifest.json").unlink()
    (directory / "manifest.json").symlink_to("/etc/passwd")
    with pytest.raises(OSError):
        health.queue_metrics(tmp_path)


def test_root_symlink_is_rejected(tmp_path):
    path = tmp_path / "link"
    path.symlink_to(tmp_path)
    with pytest.raises(OSError):
        health.queue_metrics(path)


def test_publish_atomic_and_public_only_aggregate(tmp_path):
    output = tmp_path / "wlb-health.prom"
    health.publish(output, "metric 12\n")
    assert output.read_text() == "metric 12\n"
    assert os.stat(output).st_mode & 0o777 == 0o644
    assert list(tmp_path.iterdir()) == [output]


def test_siem_spool_counts_only_regular_wlb_files(tmp_path):
    (tmp_path / "wlb_siem.00000001").write_bytes(b"12345")
    (tmp_path / "wlb_siem.qi").write_bytes(b"abc")
    (tmp_path / "unrelated").write_bytes(b"ignored")
    assert health.siem_spool_bytes(tmp_path) == 8
    (tmp_path / "wlb_siem.00000002").symlink_to("/etc/passwd")
    with pytest.raises(ValueError):
        health.siem_spool_bytes(tmp_path)


def test_collect_uses_missing_measurement_instead_of_inventing_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(health, "siem_spool_bytes", lambda _: (_ for _ in ()).throw(OSError()))
    result = health.sample(tmp_path)
    assert "wlb_health_siem_spool_collect_success 0" in result
    assert "wlb_siem_spool_file_bytes" not in result


def test_chrony_parsing_synchronised_and_unsynchronised(monkeypatch, tmp_path):
    class Result:
        returncode = 0
        stdout = "00000000,,0,0,Not synchronised\n"

    monkeypatch.setattr(health.subprocess, "run", lambda *args, **kwargs: Result())
    assert "wlb_health_chrony_synchronised 0" in health.sample(tmp_path)
    Result.stdout = "01020304,host,2,0,Normal\n"
    assert "wlb_health_chrony_synchronised 1" in health.sample(tmp_path)
    Result.stdout = "invalid\n"
    result = health.sample(tmp_path)
    assert "wlb_health_chrony_collect_success 0" in result
    assert "wlb_health_chrony_synchronised" not in result


def test_limits_and_unknown_entries(monkeypatch, tmp_path):
    (tmp_path / "nieznany").touch()
    with pytest.raises(ValueError):
        health.queue_metrics(tmp_path)
    (tmp_path / "nieznany").unlink()
    (tmp_path / ".incoming.fake").touch()
    with pytest.raises(ValueError):
        health.queue_metrics(tmp_path)
    (tmp_path / ".incoming.fake").unlink()
    directory = bundle(tmp_path)
    monkeypatch.setattr(health, "MAX_MANIFEST", 1)
    with pytest.raises(ValueError):
        health.queue_metrics(tmp_path)
    monkeypatch.setattr(health, "MAX_MANIFEST", 10000)
    monkeypatch.setattr(health, "MAX_TOTAL_MANIFEST_BYTES", 1)
    with pytest.raises(ValueError):
        health.queue_metrics(tmp_path)
    monkeypatch.setattr(health, "MAX_TOTAL_MANIFEST_BYTES", 10000)
    monkeypatch.setattr(health, "MAX_TOTAL_ENTRIES", 1)
    with pytest.raises(ValueError):
        health.queue_metrics(tmp_path)
    monkeypatch.setattr(health, "MAX_TOTAL_ENTRIES", 1000)
    (directory / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "state": "pending_review", "entries": [{"type": "file", "size": -1}]})
    )
    with pytest.raises(ValueError):
        health.queue_metrics(tmp_path)
    monkeypatch.setattr(health, "MAX_BUNDLES", 0)
    with pytest.raises(ValueError):
        health.queue_metrics(tmp_path)
    with pytest.raises(ValueError):
        health.siem_spool_bytes(tmp_path)


def test_service_unknown_and_failed_other_sources(monkeypatch, tmp_path):
    class Result:
        returncode = 4
        stdout = "invalid"

    monkeypatch.setattr(health.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(ValueError):
        health.service_active("auditd.service")
    monkeypatch.setattr(health, "siem_spool_bytes", lambda _: 7)
    monkeypatch.setattr(health.os, "statvfs", lambda _: (_ for _ in ()).throw(OSError()))
    result = health.sample(tmp_path)
    assert "wlb_siem_spool_file_bytes 7" in result
    assert "wlb_health_auditd_collect_success 0" in result
    assert 'wlb_health_filesystem_collect_success{scope="root"} 0' in result


def test_publish_failure_cleans_temp(monkeypatch, tmp_path):
    def fail(*args):
        raise OSError("failed")

    monkeypatch.setattr(health.os, "replace", fail)
    with pytest.raises(OSError):
        health.publish(tmp_path / "metrics.prom", "a 1\n")
    assert list(tmp_path.iterdir()) == []


def test_main_reports_failure_without_paths(monkeypatch, capsys):
    monkeypatch.setattr(health, "sample", lambda _: "metric 1\n")
    monkeypatch.setattr(health, "publish", lambda *args: None)
    assert health.main() == 0
    monkeypatch.setattr(health, "publish", lambda *args: (_ for _ in ()).throw(OSError("secret")))
    assert health.main() == 1
    assert "secret" not in capsys.readouterr().err


def test_missing_workspace_is_not_treated_as_empty(monkeypatch):
    monkeypatch.setattr(health, "workspace_mounted", lambda: False)
    result = health.sample(Path("/workspace/.wlb-export-queue"))
    assert "wlb_health_queue_collect_success 0" in result
    assert "wlb_export_queue_bundles" not in result
