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


def test_monitoring_tool_paths_match_the_role_and_firstboot():
    """wlb-monitoring, rola monitoring i wlb-firstboot muszą wskazywać te same ścieżki (#22).

    Rozjazd (np. inny katalog drop-inów albo reguł) kończyłby się cichym brakiem ekspozycji albo,
    gorzej, plikiem reguły, którego zapora nie wczytuje po restarcie.
    """
    tasks = yaml.safe_load((ROOT / "ansible/roles/monitoring/tasks/main.yml").read_text())
    copies = {c["dest"]: c for c in (t["ansible.builtin.copy"] for t in tasks if "ansible.builtin.copy" in t)}
    dirs = {t["ansible.builtin.file"]["path"] for t in tasks if "ansible.builtin.file" in t}
    tool = (ROOT / "ansible/roles/monitoring/files/wlb-monitoring").read_text()
    firstboot = (ROOT / "ansible/roles/lab_config/files/wlb-firstboot").read_text()

    assert copies["/usr/local/sbin/wlb-monitoring"]["src"] == "wlb-monitoring"
    assert copies["/usr/local/sbin/wlb-monitoring"]["mode"] == "0755"
    assert "SELF=${WLB_MONITORING_SELF:-/usr/local/sbin/wlb-monitoring}" in tool
    assert "WLB_MONITORING=${WLB_MONITORING:-/usr/local/sbin/wlb-monitoring}" in firstboot

    dropin = next(dest for dest in copies if dest.endswith("10-wlb.conf"))
    assert f"DROPIN_DIR=${{WLB_NODE_EXPORTER_DROPIN_DIR:-{dropin.rsplit('/', 1)[0]}}}" in tool
    assert "--web.listen-address=127.0.0.1:9100" in copies[dropin]["content"]

    assert "/etc/nftables.d" in dirs
    assert "NFT_DIR=${WLB_NFT_DIR:-/etc/nftables.d}" in tool
    assert "NFT_DIR=$R/etc/nftables.d" in firstboot
    assert 'include "${NFT_DIR}/*-wlb-*.nft"' in firstboot
    assert "chain monitoring_in {" in firstboot and "jump monitoring_in" in firstboot


def test_tool_is_installed_before_the_exporter_starts():
    """Override eksportera woła guard z /usr/local/sbin — narzędzie musi istnieć przed startem."""
    tasks = yaml.safe_load((ROOT / "ansible/roles/monitoring/tasks/main.yml").read_text())
    names = [t["name"] for t in tasks]
    tool = next(i for i, t in enumerate(tasks) if t.get("ansible.builtin.copy", {}).get("src") == "wlb-monitoring")
    start = names.index("Uruchomienie node_exporter")
    assert tool < start
