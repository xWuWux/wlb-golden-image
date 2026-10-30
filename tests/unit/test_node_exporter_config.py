"""Kontrakt bezpiecznego nasłuchu node_exporter przed integracją z monitoringiem (#22)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_node_exporter_is_configured_before_install_and_only_listens_locally():
    tasks = yaml.safe_load((ROOT / "ansible/roles/monitoring/tasks/main.yml").read_text())
    dropin = next(t for t in tasks if t.get("ansible.builtin.copy", {}).get("dest", "").endswith("10-wlb.conf"))
    install = next(t for t in tasks if t.get("ansible.builtin.apt", {}).get("name") == "prometheus-node-exporter")
    assert tasks.index(dropin) < tasks.index(install)
    assert install["ansible.builtin.apt"]["policy_rc_d"] == 101
    assert "ExecStart=\n" in dropin["ansible.builtin.copy"]["content"]
    assert "--web.listen-address=127.0.0.1:9100" in dropin["ansible.builtin.copy"]["content"]
    assert "--collector.textfile.directory=/var/lib/wlb-node-exporter" in dropin["ansible.builtin.copy"]["content"]


def test_textfile_directory_is_not_writable_by_researchers():
    tasks = yaml.safe_load((ROOT / "ansible/roles/monitoring/tasks/main.yml").read_text())
    directory = next(
        t["ansible.builtin.file"]
        for t in tasks
        if t.get("ansible.builtin.file", {}).get("path") == "/var/lib/wlb-node-exporter"
    )
    assert (directory["owner"], directory["group"], directory["mode"]) == ("root", "root", "0755")
