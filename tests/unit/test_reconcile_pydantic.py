"""Regression: ci.425 imported 2.14.1 but exported stale pip metadata 2.14.2."""

import json
import sys
from importlib.metadata import distributions

import pytest
from conftest import REPO_ROOT, load_script

repair = load_script(
    "reconcile_pydantic",
    REPO_ROOT / "ansible/roles/python_env/files/reconcile_pydantic.py",
)


@pytest.fixture
def env(tmp_path):
    site = tmp_path / "site-packages"
    conda = tmp_path / "conda-meta"
    site.mkdir()
    conda.mkdir()
    for version in ("2.14.1", "2.14.2"):
        dist = site / f"pydantic-{version}.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(f"Name: pydantic\nVersion: {version}\n")
    owned = (
        f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages/pydantic-2.14.1.dist-info/METADATA"
    )
    (conda / "pydantic-2.14.1-build.json").write_text(
        json.dumps({"name": "pydantic", "version": "2.14.1", "files": [owned]})
    )
    (site / "pydantic").mkdir()
    (site / "pydantic" / "__init__.py").write_text("unchanged payload")
    return site, conda, tmp_path / "quarantine"


def test_duplicate_metadata_quarantined_and_second_run_is_noop(env):
    site, conda, quarantine = env
    record_before = next(conda.iterdir()).read_bytes()
    assert sorted(d.version for d in distributions(path=[str(site)])) == ["2.14.1", "2.14.2"]
    assert repair.reconcile(*env, "2.14.1") == ["pydantic-2.14.2.dist-info"]
    assert [d.version for d in distributions(path=[str(site)])] == ["2.14.1"]
    assert (quarantine / "pydantic-2.14.2.dist-info/METADATA").is_file()
    assert (site / "pydantic/__init__.py").read_text() == "unchanged payload"
    assert next(conda.iterdir()).read_bytes() == record_before
    assert repair.reconcile(*env, "2.14.1") == []


@pytest.mark.parametrize("fault", ["runtime", "owner", "missing", "collision", "symlink", "metadata", "inside"])
def test_ambiguous_state_fails_without_moving_stale_metadata(env, fault):
    site, conda, quarantine = env
    version = "2.14.1"
    if fault == "runtime":
        version = "2.14.2"
    elif fault == "owner":
        next(conda.iterdir()).write_text('{"name":"pydantic","version":"2.14.1","files":[]}')
    elif fault == "missing":
        (site / "pydantic-2.14.1.dist-info/METADATA").unlink()
        (site / "pydantic-2.14.1.dist-info").rmdir()
    elif fault == "collision":
        (quarantine / "pydantic-2.14.2.dist-info").mkdir(parents=True)
    elif fault == "symlink":
        (site / "pydantic-2.14.3.dist-info").symlink_to(site / "pydantic-2.14.1.dist-info")
    elif fault == "metadata":
        (site / "pydantic-2.14.2.dist-info/METADATA").write_text("Name: other\nVersion: 2.14.2\n")
    elif fault == "inside":
        quarantine = site / "quarantine"
    with pytest.raises(ValueError):
        repair.reconcile(site, conda, quarantine, version)
    assert (site / "pydantic-2.14.2.dist-info").is_dir()
