"""Regresja #306: gorący dziennik rollback SQLite nie może po cichu cofać odtworzenia bazy.

Scenariusz z recenzji: baza JupyterHuba pracuje w ``journal_mode=DELETE``, więc po awarii
zostaje ``jupyterhub.sqlite-journal``. Odtworzenie kopii przez podmianę samego pliku bazy,
bez przeniesienia dziennika, pozwala SQLite odtworzyć stare strony przy pierwszym otwarciu.
Test dowodzi, że treść po takim odtworzeniu nie jest treścią kopii (albo baza jawnie pada
z błędem B-tree), oraz że przeniesienie dziennika temu zapobiega.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))

from sqlite_hot_journal import BASELINE_USERS, make_hot_journal  # noqa: E402

BACKUP_USERS: tuple[str, ...] = tuple(f"backup-{i:02d}" for i in range(12))


def _create_backup(path: Path, names: tuple[str, ...]) -> None:
    with closing(sqlite3.connect(path)) as conn:
        mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        assert mode == "delete", f"journal_mode={mode!r}, oczekiwano 'delete'"
        conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO users(name) VALUES (?)",
            [(name,) for name in names],
        )
        conn.commit()


def _read_users(path: Path) -> tuple[str, ...]:
    with closing(sqlite3.connect(path)) as conn:
        return tuple(row[0] for row in conn.execute("SELECT name FROM users ORDER BY id"))


def test_goracy_journal_cofa_podmieniona_kopie(tmp_path: Path) -> None:
    db = tmp_path / "jupyterhub.sqlite"
    hot_journal = make_hot_journal(db)
    assert hot_journal == Path(f"{db}-journal")
    assert hot_journal.stat().st_size > 0

    backup = tmp_path / "jupyterhub-backup.sqlite"
    _create_backup(backup, BACKUP_USERS)
    assert _read_users(backup) == BACKUP_USERS

    # Odtworzenie kopii bez przeniesienia -journal: dokładnie regres z recenzji #306.
    shutil.copy2(backup, db)
    assert hot_journal.exists(), "dziennik zniknął przed otwarciem odtworzonej bazy"

    try:
        restored = _read_users(db)
    except sqlite3.DatabaseError:
        # Drugi dopuszczalny objaw regresu: stary dziennik jawnie psuje strukturę B-tree.
        return

    assert restored != BACKUP_USERS, (
        "gorący -journal nie zadziałał: odtworzona baza ma treść kopii; test nie wykryłby regresu z recenzji #306"
    )
    assert restored == BASELINE_USERS, (
        f"stary dziennik nie cofnął odtworzenia do stanu sprzed transakcji: odczytano {restored!r}"
    )
    assert not hot_journal.exists(), "gorący dziennik nie został zużyty po odtworzeniu"


def test_po_przeniesieniu_dziennika_kopia_zostaje(tmp_path: Path) -> None:
    db = tmp_path / "jupyterhub.sqlite"
    hot_journal = make_hot_journal(db)

    backup = tmp_path / "jupyterhub-backup.sqlite"
    _create_backup(backup, BACKUP_USERS)

    shutil.copy2(backup, db)
    forensic = tmp_path / "przed-odtworzeniem"
    forensic.mkdir()
    hot_journal.rename(forensic / hot_journal.name)

    # Kontrola pozytywna: bez gorącego dziennika odtworzona kopia pozostaje kopią.
    assert _read_users(db) == BACKUP_USERS
