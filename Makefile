SHELL := /bin/bash

IMAGE_NAME    ?= wlb-general
IMAGE_VERSION ?= 0.1.0
IMAGE_DATE    ?= $(shell date +%Y%m%d)
FULL_NAME     := $(IMAGE_NAME)-$(IMAGE_VERSION)-$(IMAGE_DATE)

BUILD_DIR := build
KEY       := $(BUILD_DIR)/packer_ed25519
PACKER_VARS := -var image_name=$(IMAGE_NAME) -var image_version=$(IMAGE_VERSION) -var image_date=$(IMAGE_DATE)

# Narzędzia z make tools (przypięte wersje Packera i Ansible) — bez ręcznego export PATH
export PATH := $(CURDIR)/.tools/bin:$(CURDIR)/.tools/venv-lint/bin:$(PATH)
export ANSIBLE_CONFIG := $(CURDIR)/ansible/ansible.cfg

.PHONY: help doctor init keys validate build test-up test test-password test-down freeze clean \
	tools lint check security observability unit integration perf ci

help: ## Lista celów
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-10s %s\n",$$1,$$2}'

doctor: ## Sprawdza środowisko: położenie repozytorium, CRLF, KVM, narzędzia, miejsce i pamięć
	@ci/preflight.sh

init: ## Pobiera wtyczki Packera (qemu, ansible)
	packer init packer/

$(KEY):
	mkdir -p $(BUILD_DIR)
	ssh-keygen -q -t ed25519 -N '' -C wlb-packer-build -f $(KEY)

keys: $(KEY)

validate: check ## Alias: stage 2 (build test)

# --- Pipeline CI (te same skrypty co w GitHub Actions) ---------------------------
tools: ## Narzędzia CI w .tools/ (bez sudo; kcov: sudo apt install kcov)
	ci/install-tools.sh

lint: ## 1. Lint, format i skan sekretów (FIX=1 poprawia formatowanie)
	ci/lint.sh

check: ## 2. Build test: walidacja i kompilacja bez budowania obrazu
	ci/build-check.sh

security: ## 3. SAST, IaC, podatności zależności, licencje
	ci/security.sh

observability: ## 3.5. Kontrakty obrazu: obserwowalność i zmienne wdrożeniowe
	ci/observability.sh

unit: ## 4. Testy jednostkowe z progami pokrycia
	ci/unit.sh

integration: ## 5. Budowanie obrazu, akceptacja MVP, migracja, dryf locków (KVM, ~1–2 h)
	ci/integration.sh

perf: ## 6. Benchmarki wydajności ostatniego obrazu
	ci/perf.sh

ci: lint check security observability unit ## Etapy 1–4 (szybkie, przed każdym pushem)

build: doctor keys ## Buduje golden image -> output/<nazwa>-<wersja>-<data>/
	packer build -only='wlb.qemu.wlb' $(PACKER_VARS) packer/
	@echo "Zamrożone wersje pakietów: $(BUILD_DIR)/artifacts/$(FULL_NAME)/ (make freeze, aby przenieść do envs/)"

test-up: doctor ## Uruchamia najnowszy obraz lokalnie jako Laboratorium testowe
	tests/run-local.sh $(IMAGE)

test: ## Kryteria akceptacji MVP na uruchomionej VM testowej
	tests/acceptance.sh

test-password: ## Hasło początkowe Administratora Klienta (a01) z działającej VM testowej
	@ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 \
	  -i $(BUILD_DIR)/test/id_ed25519 -p 2222 wlbadmin@127.0.0.1 sudo cat /root/wlb-hub-admin-initial-password \
	  || { echo "VM testowa nie działa albo hasło zostało już zmienione (make test-up)"; exit 1; }

test-down: ## Zatrzymuje VM testową
	tests/stop-local.sh

freeze: ## Kopiuje zamrożone wersje z ostatniego budowania do envs/ (do commita)
	@src=$$(ls -td $(BUILD_DIR)/artifacts/*/ 2>/dev/null | head -1); \
	test -n "$$src" || { echo "Brak artefaktów — najpierw make build"; exit 1; }; \
	cp -v "$$src/environment.lock.yml" envs/python/environment.lock.yml; \
	cp -v "$$src/renv.lock" envs/r/renv.lock; \
	if git diff --quiet -- envs/; then \
	  echo "Bez zmian: wersje w repozytorium są zgodne ze zbudowanym obrazem (nic do commita)."; \
	else \
	  git --no-pager diff --stat -- envs/; \
	  echo "Wersje się zmieniły: commit na osobnej gałęzi i PR (git switch -c freeze-$(IMAGE_VERSION))."; \
	fi

clean: ## Usuwa lokalne artefakty (obrazy w output/ zostają)
	rm -rf $(BUILD_DIR)/test $(BUILD_DIR)/coverage $(BUILD_DIR)/rendered $(BUILD_DIR)/sca packer_cache
