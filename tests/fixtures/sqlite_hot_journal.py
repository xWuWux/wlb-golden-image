"""Prawdziwy gorący dziennik rollback SQLite dla testów DR bazy huba (#306).

JupyterHub 5.5.x nie przełącza bazy na WAL — pracuje w domyślnym ``journal_mode=DELETE``
i po awarii zostawia obok bazy plik ``jupyterhub.sqlite-journal``. Ten moduł tworzy taki
dziennik w kontrolowany sposób: proces potomny otwiera transakcję, modyfikuje strony
i kończy się przez ``os._exit()``, więc SQLite nie wycofuje transakcji ani nie usuwa
dziennika. Odtworzenie kopii na taką bazę bez przeniesienia ``-journal`` powoduje, że
SQLite przy pierwszym otwarciu odtwarza stare strony z dziennika i po cichu cofa kopię
(albo zgłasza błąd B-tree).
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

# Pierwsze 8 bajtów nagłówka dziennika rollback SQLite (magic).
JOURNAL_MAGIC = bytes.fromhex("d9d505f920a163d7")

# Wiersze bazowe; test porównuje z nimi treść bazy po odtworzeniu z gorącym dziennikiem.
BASELINE_USERS: tuple[str, ...] = tuple(f"baseline-{i:02d}" for i in range(12))

# Proces potomny celowo kończy się przez os._exit(), bez zamykania połączenia SQLite:
# close() wycofałby transakcję i usunął -journal, a właśnie gorący dziennik jest celem.
_CHILD = r"""
import os
import sqlite3
import sys

db = sys.argv[1]
conn = sqlite3.connect(db, isolation_level=None)

mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
if mode != "delete":
    print(f"journal_mode={mode!r}, oczekiwano 'delete'", file=sys.stderr)
    os._exit(1)

conn.execute("PRAGMA synchronous=FULL")
conn.execute("PRAGMA cache_size=2")
conn.execute("BEGIN IMMEDIATE")
conn.execute("UPDATE users SET name = name || '-hot'")
conn.execute("CREATE TABLE payload(x BLOB)")
for _ in range(8):
    conn.execute("INSERT INTO payload VALUES (randomblob(4096))")

journal = db + "-journal"
if not os.path.isfile(journal) or os.path.getsize(journal) == 0:
    print("SQLite nie utworzył niepustego -journal", file=sys.stderr)
    os._exit(1)

os._exit(0)
"""


def make_hot_journal(db: Path) -> Path:
    """Tworzy bazę SQLite i zostawia obok niej prawdziwy gorący dziennik rollback.

    Baza dostaje tabelę ``users`` z wierszami :data:`BASELINE_USERS`, a następnie
    proces potomny wykonuje niezatwierdzoną transakcję i kończy się bez sprzątania.
    Dzięki temu ``db-journal`` jest gorący: pierwsze otwarcie bazy odtworzy z niego
    stare strony. Funkcja nie otwiera bazy po utworzeniu dziennika, bo to zużyłoby
    dziennik i zniwelowało scenariusz testowy.

    :param db: ścieżka bazy, obok której ma powstać ``-journal``.
    :returns: ścieżka utworzonego dziennika (``<db>-journal``).
    :raises RuntimeError: gdy SQLite nie utworzy poprawnego gorącego dziennika.
    """
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)

    conn = sqlite3.connect(db)
    try:
        mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        assert mode == "delete", f"journal_mode={mode!r}, oczekiwano 'delete'"
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO users(name) VALUES (?)",
            [(name,) for name in BASELINE_USERS],
        )
        conn.commit()
    finally:
        conn.close()

    # S603: polecenie jest stałe (sys.executable + _CHILD), a db to tylko argument.
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _CHILD, str(db)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"nie udało się zostawić gorącego dziennika SQLite: rc={proc.returncode}, stderr={proc.stderr.strip()!r}"
        )

    journal = Path(f"{db}-journal")
    if not journal.is_file() or journal.stat().st_size == 0:
        raise RuntimeError(f"brak niepustego dziennika {journal}")
    with journal.open("rb") as fh:
        magic = fh.read(len(JOURNAL_MAGIC))
    if magic != JOURNAL_MAGIC:
        raise RuntimeError(f"{journal} nie ma nagłówka gorącego dziennika SQLite")
    return journal
