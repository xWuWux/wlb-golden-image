# IMG-005: Dostęp i szyfrowanie na pierwszy lokalny pilotaż — Native auth + lokalny TLS + wymagany CIDR

* **Status:** Przyjęta (zakres: lokalny pilotaż; docelowy IdP/MFA — oczekuje na decyzję platformy w #18)
* **Data:** 2026-10-23
* **Autorzy / decyduje:** Właściciel Platformy
* **Powiązania:** Regulamin: §6, §20 · IP_CMC: OPZ B.5/B.6/B.13/B.27/B.29/B.30, BP-VL-1.3 · Zgłoszenia/PR: #18, #57 · Pliki: `ansible/roles/tljh/templates/config.yaml.j2`, `10-wlb.py.j2`, `ansible/roles/lab_config/files/wlb-firstboot`

## Kontekst i problem

Docelowo §6 wymaga logowania przez IdP GUMed z MFA i (§20) szyfrowania in-transit; OPZ wskazuje Entra ID / OIDC. To **decyzja platformy** (IdP, portal vs VDI) i wymaga infrastruktury (IdP, mapowanie loginów, wyjście huba do IdP) — czyli skalowania poza lokalny pilotaż. Jednocześnie dziś hub stoi na `:80` bez TLS, a `HUB_ALLOWED_CIDR`/`ADMIN_SSH_CIDR` mają groźny domyślny `0.0.0.0/0`.

## Rozważane opcje

1. **Native auth + lokalny TLS + wymagany CIDR** — zostaje NativeAuthenticator; TLS z wewnętrznego CA na VM; `wlb-firstboot` wymaga jawnego CIDR.
2. **Native auth + HTTP na izolowanym LAN** — bez TLS; niezgodne z §20/B.13.
3. **Od razu OIDC (Keycloak/Entra) + TLS** — pełne MFA/SSO; wymaga IdP i odkłada pilotaż (skalowanie).

## Decyzja

**Opcja 1 na pilotaż.** Native Authenticator (już w obrazie) + **TLS terminowany na VM z certyfikatu wewnętrznego CA** (Let's Encrypt odpada bez internetu) + **wymuszony `HUB_ALLOWED_CIDR`** (koniec z `0.0.0.0/0`). Badacz-tester łączy się bezpośrednio, tylko z sieci wskazanej w CIDR. **Docelowo** (produkcja): OIDC — rekomendacja **A z #18: Keycloak federujący Entra ID** + grupy per Laboratorium; to pozostaje decyzją platformy w #18.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Tak, czasowe. §6 wymaga MFA/IdP; na **pilotaż** używamy Native auth (zgodnie z otwartym pytaniem WLB_Specs: „badacz-tester tymczasowo bezpośrednio na czas MVP"). TLS (§20) spełniamy od razu. MFA/IdP przed szerszą produkcją.

## Konsekwencje

* **Pozytywne:** pilotaż rusza bez IdP; ruch szyfrowany (§20); zamknięty domyślny wektor `0.0.0.0/0`; `oauthenticator` jest już w obrazie, więc przejście na OIDC to konfiguracja, nie nowe pakiety.
* **Negatywne / dług techniczny:** Native auth przechowuje hasła w bazie huba; migracja kont i usunięcie haseł Native przy przejściu na OIDC; `10-wlb.py.j2` do uwarunkowania (`HUB_AUTH=native|oidc`, bez `allow_all` w OIDC). **Osobne zgłoszenie M1:** `wlb-firstboot` odmawia pracy bez CIDR + port 443 tylko przy włączonym TLS.
* **Świadomie pominięte:** bramka VDI/Guacamole (§14.7) — osobny tor; natychmiastowe OIDC — odłożone, by nie blokować pilotażu.
