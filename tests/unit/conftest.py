import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ci"))


def load_script(name: str, path: Path):
    """Ładuje skrypt bez rozszerzenia .py jako moduł (np. wlb-hub-user)."""
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def hub_user():
    return load_script("wlb_hub_user", REPO_ROOT / "ansible/roles/tljh/files/wlb-hub-user")
