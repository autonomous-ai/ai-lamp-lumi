# AI Lamp (Lumi) — Makefile
# 3 components: Go (lumi + bootstrap), Python (lelamp), TypeScript (web)

VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")

# Directories
LUMI_DIR       := lumi
LELAMP_DIR     := lelamp
WEB_DIR        := $(LUMI_DIR)/web

# Go build
MODULE         := go-lamp.autonomous.ai
LDFLAGS_LAMP   := -X $(MODULE)/server/config.LumiVersion=$(VERSION)
LDFLAGS_BOOT   := -X $(MODULE)/bootstrap/config.BootstrapVersion=$(VERSION)

# LeLamp
LELAMP_PORT    := 5001

# ============================================================================
# Lumi (Go) — build | generate | lint | test
# ============================================================================

.PHONY: lumi-build lumi-build-bootstrap lumi-generate lumi-lint lumi-test

lumi-build:
	cd $(LUMI_DIR) && GOOS=linux GOARCH=arm64 go build -ldflags "-s -w $(LDFLAGS_LAMP)" -o lumi-server ./cmd/lamp


lumi-build-bootstrap:
	cd $(LUMI_DIR) && GOOS=linux GOARCH=arm64 go build -ldflags "-s -w $(LDFLAGS_BOOT)" -o bootstrap-server ./cmd/bootstrap


lumi-generate:
	cd $(LUMI_DIR) && GOFLAGS=-mod=mod go generate ./...

lumi-lint:
	cd $(LUMI_DIR) && golangci-lint run

lumi-test:
	cd $(LUMI_DIR) && go test ./...

# ============================================================================
# LeLamp (Python) — dev | run | test
# ============================================================================

.PHONY: lelamp lelamp-dev lelamp-run lelamp-test lelamp-clean

lelamp: lelamp-dev

lelamp-dev:
	cd $(LELAMP_DIR) && PYTHONPATH=.. .venv/bin/uvicorn lelamp.server:app --host 0.0.0.0 --port $(LELAMP_PORT) --reload

lelamp-run:
	cd $(LELAMP_DIR) && PYTHONPATH=.. .venv/bin/python -m lelamp.server

lelamp-test:
	cd $(LELAMP_DIR) && .venv/bin/python -m pytest test/

lelamp-clean:
	rm -rf $(LELAMP_DIR)/.venv $(LELAMP_DIR)/__pycache__

# ============================================================================
# Web (React/Vite/Tailwind) — install | dev | build
# ============================================================================

.PHONY: web web-install web-dev web-build

web: web-dev

web-install:
	cd $(WEB_DIR) && npm install

web-dev:
	cd $(WEB_DIR) && npm run dev

web-build:
	cd $(WEB_DIR) && npm run build

# ============================================================================
# Upload (OTA to GCS) — unified format: make upload-<component>
# ============================================================================

.PHONY: upload-lumi upload-bootstrap upload-lelamp upload-web upload-skills upload-setup upload-setup-ap upload-all

upload-lumi:
	bash scripts/upload-lumi.sh

upload-bootstrap:
	bash scripts/upload-bootstrap.sh

upload-lelamp:
	bash scripts/upload-lelamp.sh

upload-web:
	bash scripts/upload-web.sh

upload-skills:
	bash scripts/upload-skills.sh

upload-setup:
	bash scripts/upload-setup.sh

upload-setup-ap:
	bash scripts/upload-setup-ap.sh

upload-all: upload-lumi upload-bootstrap upload-lelamp upload-web upload-skills

# ============================================================================
# Clean
# ============================================================================

.PHONY: clean

clean:
	rm -f $(LUMI_DIR)/lumi-server $(LUMI_DIR)/bootstrap-server
	rm -rf $(LELAMP_DIR)/.venv $(LELAMP_DIR)/__pycache__
	rm -rf $(WEB_DIR)/dist $(WEB_DIR)/node_modules
