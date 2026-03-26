# AI Lamp (Lumi) — Makefile
# 3 components: Go (lumi + bootstrap), Python (lelamp), TypeScript (web)

VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
PI_HOST ?= lumi.local
PI_USER ?= root

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
# Lumi (Go) — build | generate | lint | test | deploy
# ============================================================================

.PHONY: lumi-build lumi-build-bootstrap lumi-generate lumi-lint lumi-test lumi-deploy lumi-deploy-bootstrap

lumi-build:
	cd $(LUMI_DIR) && GOOS=linux GOARCH=arm64 go build -ldflags "$(LDFLAGS_LAMP)" -o lumi-server ./cmd/lamp

lumi-build-bootstrap:
	cd $(LUMI_DIR) && GOOS=linux GOARCH=arm64 go build -ldflags "$(LDFLAGS_BOOT)" -o bootstrap-server ./cmd/bootstrap

lumi-generate:
	cd $(LUMI_DIR) && GOFLAGS=-mod=mod go generate ./...

lumi-lint:
	cd $(LUMI_DIR) && golangci-lint run

lumi-test:
	cd $(LUMI_DIR) && go test ./...

lumi-deploy: lumi-build
	scp $(LUMI_DIR)/lumi-server $(PI_USER)@$(PI_HOST):/usr/local/bin/lumi-server
	ssh $(PI_USER)@$(PI_HOST) "systemctl restart lumi.service"

lumi-deploy-bootstrap: lumi-build-bootstrap
	scp $(LUMI_DIR)/bootstrap-server $(PI_USER)@$(PI_HOST):/usr/local/bin/bootstrap-server
	ssh $(PI_USER)@$(PI_HOST) "systemctl restart bootstrap.service"

# ============================================================================
# LeLamp (Python) — install | dev | run | test | deploy
# ============================================================================

.PHONY: lelamp lelamp-install lelamp-dev lelamp-run lelamp-test lelamp-deploy lelamp-clean

lelamp: lelamp-dev

lelamp-install:
	cd $(LELAMP_DIR) && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

lelamp-dev:
	cd $(LELAMP_DIR) && PYTHONPATH=.. .venv/bin/uvicorn lelamp.server:app --host 0.0.0.0 --port $(LELAMP_PORT) --reload

lelamp-run:
	cd $(LELAMP_DIR) && PYTHONPATH=.. .venv/bin/python -m lelamp.server

lelamp-test:
	cd $(LELAMP_DIR) && .venv/bin/python -m pytest test/

lelamp-deploy:
	rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
		$(LELAMP_DIR)/ $(PI_USER)@$(PI_HOST):/opt/lelamp/
	ssh $(PI_USER)@$(PI_HOST) "cd /opt/lelamp && .venv/bin/pip install -r requirements.txt --quiet && systemctl restart lumi-lelamp.service"

lelamp-clean:
	rm -rf $(LELAMP_DIR)/.venv $(LELAMP_DIR)/__pycache__

# ============================================================================
# Web (React/Vite/Tailwind) — install | dev | build | deploy
# ============================================================================

.PHONY: web web-install web-dev web-build web-deploy

web: web-dev

web-install:
	cd $(WEB_DIR) && npm install

web-dev:
	cd $(WEB_DIR) && npm run dev

web-build:
	cd $(WEB_DIR) && npm run build

web-deploy: web-build
	rsync -avz $(WEB_DIR)/dist/ $(PI_USER)@$(PI_HOST):/usr/share/nginx/html/setup/

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
# All — deploy | clean
# ============================================================================

.PHONY: deploy-all clean

deploy-all: lumi-deploy lumi-deploy-bootstrap lelamp-deploy web-deploy

clean:
	rm -f $(LUMI_DIR)/lumi-server $(LUMI_DIR)/bootstrap-server
	rm -rf $(LELAMP_DIR)/.venv $(LELAMP_DIR)/__pycache__
	rm -rf $(WEB_DIR)/dist $(WEB_DIR)/node_modules
