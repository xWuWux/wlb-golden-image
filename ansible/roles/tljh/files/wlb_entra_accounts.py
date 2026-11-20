#!/usr/bin/env python3
"""Rejestr przypisań tożsamości Entra ID do kont WLB (#18, #102 D4).

Jeden wiersz = jedna osoba przypisana do jednego konta huba:

    # tid (tenant)                         oid (obiekt użytkownika)              konto
    3f1c2b4a-0000-4000-8000-000000000001   9a8b7c6d-0000-4000-8000-0000000000a1  u01

Plik leży na VM (domyślnie /etc/wlb/entra-accounts, root, 0600) i zawiera wyłącznie
identyfikatory — bez imion, adresów e-mail ani UPN. Mapowanie osoba↔konto z datami
prowadzi rejestr organizacyjny (#102); tu jest tylko bieżące przypisanie potrzebne do
logowania. Konto może być stanowiskowe (`u01`, `a01`) albo istniejące konto nazwane
z okresu przed IMG-002 — dzięki temu przejście na Entra nie wymaga przenoszenia kont.

Moduł działa bez JupyterHub (sama biblioteka standardowa): czyta go authenticator huba
(`wlb_entra_auth.py`) i `wlb-firstboot` (walidacja przed zmianą konfiguracji):

    wlb_entra_accounts.py --check PLIK --tenant TID   # kod 0: poprawny, 1: błędy na stderr
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = "/etc/wlb/entra-accounts"

# Identyfikatory obiektów Entra (tid, oid) to GUID; porównujemy w postaci małych liter.
GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Ten sam format loginu co w wlb-hub-user (konto huba = jupyter-<login> w systemie).
LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")


class AccountsError(ValueError):
    """Rejestr jest niepoprawny — logowanie przez Entra nie może z niego korzystać."""


@dataclass(frozen=True)
class Accounts:
    """Bieżące przypisania: (tid, oid) -> konto oraz odwrotnie."""

    by_identity: dict[tuple[str, str], str]

    def login_for(self, tid: str, oid: str) -> str | None:
        return self.by_identity.get((tid.lower(), oid.lower()))

    def identity_for(self, login: str) -> tuple[str, str] | None:
        for identity, mapped in self.by_identity.items():
            if mapped == login:
                return identity
        return None

    @property
    def logins(self) -> set[str]:
        return set(self.by_identity.values())


def parse(text: str, tenant_id: str | None = None) -> Accounts:
    """Parsuje treść rejestru; każdy błąd zgłasza z numerem wiersza (bez wartości identyfikatorów)."""
    tenant = tenant_id.lower() if tenant_id else None
    errors: list[str] = []
    by_identity: dict[tuple[str, str], str] = {}
    line_of_login: dict[str, int] = {}
    line_of_identity: dict[tuple[str, str], int] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 3:
            errors.append(f"wiersz {number}: oczekiwano trzech pól 'tid oid konto', jest {len(fields)}")
            continue
        tid, oid, login = fields[0].lower(), fields[1].lower(), fields[2]
        if not GUID_RE.fullmatch(tid):
            errors.append(f"wiersz {number}: tid nie jest identyfikatorem GUID")
        elif tenant and tid != tenant:
            errors.append(f"wiersz {number}: tid spoza tenantu Laboratorium (ENTRA_TENANT_ID)")
        if not GUID_RE.fullmatch(oid):
            errors.append(f"wiersz {number}: oid nie jest identyfikatorem GUID")
        if not LOGIN_RE.fullmatch(login):
            errors.append(f"wiersz {number}: niepoprawny login konta (format jak w wlb-hub-user)")
        identity = (tid, oid)
        if identity in line_of_identity:
            errors.append(f"wiersz {number}: ta sama osoba (tid, oid) już w wierszu {line_of_identity[identity]}")
        if login in line_of_login:
            errors.append(f"wiersz {number}: to samo konto przypisane już w wierszu {line_of_login[login]}")
        line_of_identity.setdefault(identity, number)
        line_of_login.setdefault(login, number)
        by_identity.setdefault(identity, login)
    if not errors and not by_identity:
        errors.append("rejestr nie zawiera żadnego przypisania")
    if errors:
        raise AccountsError("; ".join(errors))
    return Accounts(by_identity)


def load(path: str | Path = DEFAULT_PATH, tenant_id: str | None = None) -> Accounts:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AccountsError(f"nie można odczytać rejestru {path}: {exc.strerror}") from exc
    return parse(text, tenant_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", metavar="PLIK", required=True, help="waliduje rejestr i kończy")
    parser.add_argument("--tenant", metavar="TID", help="wymagany tenant Entra (ENTRA_TENANT_ID)")
    args = parser.parse_args(argv)
    try:
        accounts = load(args.check, args.tenant)
    except AccountsError as exc:
        print(f"rejestr Entra: {exc}", file=sys.stderr)
        return 1
    # bez listy loginów: stare konta nazwane mogą zawierać dane osobowe, a wynik trafia do dziennika
    print(f"rejestr Entra: {len(accounts.by_identity)} przypisań")
    return 0


if __name__ == "__main__":
    sys.exit(main())
