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


def test_firstboot_overrides_the_dropin_installed_by_the_role():
    """wlb-firstboot nie może rozjechać się ze ścieżką i flagą, które ustawia rola (#22).

    Firstboot nie instaluje eksportera — tylko nadpisuje ExecStart z pliku obrazu, zachowując
    pozostałe flagi (textfile collector). Zmiana nazwy pliku lub adresu w roli bez zmiany
    w firstboocie kończyłaby się cichym brakiem ekspozycji albo błędem na wdrożonej VM.
    """
    tasks = yaml.safe_load((ROOT / "ansible/roles/monitoring/tasks/main.yml").read_text())
    dropin_dest = next(
        t["ansible.builtin.copy"]["dest"]
        for t in tasks
        if t.get("ansible.builtin.copy", {}).get("dest", "").endswith("10-wlb.conf")
    )
    firstboot = (ROOT / "ansible/roles/lab_config/files/wlb-firstboot").read_text()
    assert f"NODE_EXPORTER_DROPIN=$R{dropin_dest}" in firstboot
    assert f"NODE_EXPORTER_MONITORING_DROPIN=$R{dropin_dest.rsplit('/', 1)[0]}/20-wlb-monitoring.conf" in firstboot
    assert "--web.listen-address=127.0.0.1:9100" in firstboot
