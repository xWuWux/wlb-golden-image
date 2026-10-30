"""Migracja prefiksu wykonywana wyłącznie podczas budowy obrazu (#193)."""

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "ansible/roles/python_env/files/wlb-version-python-env"
loader = importlib.machinery.SourceFileLoader("wlb_version_python_env", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


@pytest.fixture
def layout(tmp_path):
    user = tmp_path / "tljh/user"
    (user / "bin").mkdir(parents=True)
    (user / "bin/conda").write_text("conda")
    (user / "sentinel").write_text("oryginał")
    return user, tmp_path / "wlb/envs"


def clone_stub(calls, fail_call=None):
    def run(argv, *, check, **kwargs):
        assert check
        calls.append(argv)
        if len(calls) == fail_call:
            raise subprocess.CalledProcessError(1, argv)
        if "--clone" in argv:
            dest = Path(argv[argv.index("--prefix") + 1])
            (dest / "bin").mkdir(parents=True)
            (dest / "bin/python").write_text("klon")
        return subprocess.CompletedProcess(argv, 0, stdout="name: x\ndependencies:\n  - python=3\nprefix: /x\n")

    return run


def test_klon_do_wersji_i_idempotencja(layout, monkeypatch):
    user, envs = layout
    calls = []
    monkeypatch.setattr(mod.subprocess, "run", clone_stub(calls))
    mod.migrate(user, envs, "0.3.1-cd.5")
    assert user.is_symlink()
    assert user.resolve() == envs / "python-0.3.1-cd.5"
    assert not user.with_name("user.wlb-build-backup").exists()
    assert calls[0][1:5] == ["create", "--yes", "--copy", "--clone"]
    mod.migrate(user, envs, "0.3.1-cd.5")
    assert len(calls) == 5


@pytest.mark.parametrize("fail_call", [1, 2, 3, 4, 5])
def test_blad_nie_zmienia_oryginalu(layout, monkeypatch, fail_call):
    user, envs = layout
    monkeypatch.setattr(mod.subprocess, "run", clone_stub([], fail_call))
    with pytest.raises(subprocess.CalledProcessError):
        mod.migrate(user, envs, "1.0")
    assert not user.is_symlink()
    assert (user / "sentinel").read_text() == "oryginał"
    assert not (envs / "python-1.0").exists()


def test_nie_nadpisuje_docelowego_prefiksu(layout):
    user, envs = layout
    (envs / "python-1.0").mkdir(parents=True)
    with pytest.raises(ValueError, match="już istnieje"):
        mod.migrate(user, envs, "1.0")
    assert (user / "sentinel").exists()


def test_zla_wersja_i_pozostalosci_blokuja(layout):
    user, envs = layout
    with pytest.raises(ValueError, match="wersja"):
        mod.migrate(user, envs, "../escape")
    user.with_name("user.wlb-build-backup").mkdir()
    with pytest.raises(ValueError, match="pozostałość"):
        mod.migrate(user, envs, "1.0")
    assert (user / "sentinel").exists()


def test_inny_istniejacy_symlink_odrzucony(layout):
    user, envs = layout
    target = envs / "python-old"
    target.mkdir(parents=True)
    (envs / "python-new").mkdir()
    import shutil

    shutil.rmtree(user)
    user.symlink_to(target)
    with pytest.raises(ValueError, match="inne środowisko"):
        mod.migrate(user, envs, "new")
    assert user.resolve() == target


def test_niezgodny_eksport_przerywa_przed_zmiana_dowiazania(layout, monkeypatch):
    user, envs = layout
    calls = []
    normal = clone_stub(calls)

    def mismatch(argv, *, check, **kwargs):
        result = normal(argv, check=check, **kwargs)
        if len(calls) == 3:
            result.stdout = "dependencies:\n  - wrong-package=1\n"
        return result

    monkeypatch.setattr(mod.subprocess, "run", mismatch)
    with pytest.raises(ValueError, match="eksport pakietów"):
        mod.migrate(user, envs, "1.0")
    assert not user.is_symlink()
    assert (user / "sentinel").read_text() == "oryginał"
    assert not (envs / "python-1.0").exists()
