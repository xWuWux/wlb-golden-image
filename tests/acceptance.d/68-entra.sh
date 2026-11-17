# shellcheck shell=bash
echo "== Logowanie Entra ID: moduły w obrazie (#18) =="
# Obraz w CI działa w AUTH_MODE=native (brak tenantu testowego), więc nie przełączamy huba. Sprawdzamy, że
# moduły Entra są w obrazie i działają z oauthenticator/JupyterHub ZAINSTALOWANYMI przez TLJH (a nie tylko
# z wersjami z ci/requirements-unit.txt): pełna ścieżka get_authenticated_user z podmienioną wymianą
# kodu na token, rejestr przypisań i odmowy.
ENTRA_DIR=/opt/wlb/hub
HUB_PY=/opt/tljh/hub/bin/python3
expect_ok "Moduły Entra zainstalowane (#18)" test -r "$ENTRA_DIR/wlb_entra_auth.py" -a -r "$ENTRA_DIR/wlb_entra_accounts.py"
expect_fail "Badacz nie zmieni modułów logowania (#18)" as "$R1" touch "$ENTRA_DIR/wlb_entra_auth.py"

entra_tmp=$(mktemp -d)
chmod 0700 "$entra_tmp"
cat >"$entra_tmp/entra-accounts" <<'EOF'
3f1c2b4a-0000-4000-8000-000000000001 9a8b7c6d-0000-4000-8000-0000000000a1 u01
EOF
chmod 0600 "$entra_tmp/entra-accounts"
expect_ok "Rejestr przypisań: poprawny przechodzi (#18)" \
  python3 "$ENTRA_DIR/wlb_entra_accounts.py" --check "$entra_tmp/entra-accounts" --tenant 3f1c2b4a-0000-4000-8000-000000000001
expect_fail "Rejestr przypisań: obcy tenant odrzucony (#18)" \
  python3 "$ENTRA_DIR/wlb_entra_accounts.py" --check "$entra_tmp/entra-accounts" --tenant 3f1c2b4a-0000-4000-8000-000000000002

cat >"$entra_tmp/probe.py" <<'PY'
import asyncio, sys, time
sys.path.insert(0, "/opt/wlb/hub")
import jwt
from tornado import web
from traitlets.config import Config
from wlb_entra_auth import WlbEntraAuthenticator

TID, CLIENT, ROLE = "3f1c2b4a-0000-4000-8000-000000000001", "6c3e2f10-0000-4000-8000-0000000000c1", "WLB.Lab.test"
c = Config()
for key, value in dict(tenant_id=TID, client_id=CLIENT, client_secret="s", required_role=ROLE, allow_all=True,
                       oauth_callback_url="https://portal.wlb.local/hub/oauth_callback", accounts_file=sys.argv[1],
                       logins_file=sys.argv[1] + ".logins").items():
    setattr(c.WlbEntraAuthenticator, key, value)
auth = WlbEntraAuthenticator(config=c)
assert auth.allow_all is False, "allow_all nie może być włączone"
assert auth.authorize_url.endswith("/oauth2/v2.0/authorize"), auth.authorize_url

def login(**claims):
    base = dict(aud=CLIENT, iss=f"https://login.microsoftonline.com/{TID}/v2.0", tid=TID,
                oid="9a8b7c6d-0000-4000-8000-0000000000a1", exp=int(time.time()) + 600, roles=[ROLE])
    base.update(claims)
    token = jwt.encode(base, "x" * 32, algorithm="HS256")
    async def token_info(handler, params):
        return {"access_token": "a", "token_type": "Bearer", "id_token": token}
    auth.get_token_info = token_info
    auth.build_access_tokens_request_params = lambda handler, data: {}
    try:
        model = asyncio.run(auth.get_authenticated_user(None, {}))
    except web.HTTPError as exc:
        return exc.status_code
    return model and model["name"]

results = {
    "przypisany": login(),
    "bez_roli": login(roles=[]),
    "nieprzypisany": login(oid="9a8b7c6d-0000-4000-8000-0000000000ff"),
    "obcy_tenant": login(tid="3f1c2b4a-0000-4000-8000-000000000002"),
}
print(results)
assert results == {"przypisany": "u01", "bez_roli": None, "nieprzypisany": 403, "obcy_tenant": 403}, results
# sesja związana z osobą: przekazanie konta innej osobie kończy sesję poprzedniej
class U: name = "u01"
assert asyncio.run(auth.refresh_user(U())) is True
open(sys.argv[1], "w").write(f"{TID} 9a8b7c6d-0000-4000-8000-0000000000b2 u01\n")
assert asyncio.run(auth.refresh_user(U())) is False
PY
expect_ok "WlbEntraAuthenticator na oauthenticator z TLJH: przypisanie, rola, odmowy, sesja (#18)" \
  "$HUB_PY" "$entra_tmp/probe.py" "$entra_tmp/entra-accounts"
rm -rf "$entra_tmp"
