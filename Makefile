# AI Lamp (Lumi) — Makefile
# 3 components: Go (lumi + bootstrap), Python (lelamp), TypeScript (web)

VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
PI_HOST ?= lumi.local
PI_USER ?= root

# Go build
MODULE         := go-lamp.autonomous.ai
LDFLAGS_LAMP   := -X $(MODULE)/server/config.InternVersion=$(VERSION)
LDFLAGS_BOOT   := -X $(MODULE)/bootstrap/config.BootstrapVersion=$(VERSION)

# LeLamp
LELAMP_DIR     := lelamp
LELAMP_PORT    := 5001

# ============================================================================
# Go
# ============================================================================

.PHONY: build-lamp build-bootstrap generate lint test

build-lamp:
	GOOS=linux GOARCH=arm64 go build -ldflags "$(LDFLAGS_LAMP)" -o lumi-server ./cmd/lamp

build-bootstrap:
	GOOS=linux GOARCH=arm64 go build -ldflags "$(LDFLAGS_BOOT)" -o bootstrap-server ./cmd/bootstrap

generate:
	GOFLAGS=-mod=mod go generate ./...

lint:
	golangci-lint run

test:
	go test ./...

# ============================================================================
# LeLamp (Python) — install | dev | run | test | deploy | upload
# ============================================================================

.PHONY: lelamp lelamp-install lelamp-dev lelamp-run lelamp-test lelamp-deploy lelamp-upload lelamp-clean

lelamp: lelamp-dev

lelamp-install:
	cd $(LELAMP_DIR) && python3 -m .venv .venv && .venv/bin/pip install -r requirements.txt

lelamp-dev:
	cd $(LELAMP_DIR) && PYTHONPATH=.. .venv/bin/uvicorn lelamp.server:app --host 0.0.0.0 --port $(LELAMP_PORT) --reload

lelamp-run:
	cd $(LELAMP_DIR) && PYTHONPATH=.. .venv/bin/python -m lelamp.server

lelamp-test:
	cd $(LELAMP_DIR) && .venv/bin/python -m pytest test/

lelamp-deploy:
	rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
		$(LELAMP_DIR)/ $(PI_USER)@$(PI_HOST):/opt/lelamp/
	ssh $(PI_USER)@$(PI_HOST) "cd /opt/lelamp && .venv/bin/pip install -r requirements.txt --quiet && systemctl restart lelamp.service"

lelamp-upload:
	scripts/upload-lelamp.sh

lelamp-clean:
	rm -rf $(LELAMP_DIR)/.venv $(LELAMP_DIR)/__pycache__

# ============================================================================
# Web (React/Vite/Tailwind) — install | dev | build | deploy | upload
# ============================================================================

.PHONY: web web-install web-dev web-build web-deploy web-upload

web: web-dev

web-install:
	cd web && npm install

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build

web-deploy: web-build
	rsync -avz web/dist/ $(PI_USER)@$(PI_HOST):/usr/share/nginx/html/setup/

web-upload: web-build
	scripts/upload-web.sh

# ============================================================================
# Deploy & Upload (all components)
# ============================================================================

.PHONY: deploy-lamp deploy-bootstrap deploy-all upload-lamp upload-bootstrap

deploy-lamp: build-lamp
	scp lumi-server $(PI_USER)@$(PI_HOST):/usr/local/bin/lumi-server
	ssh $(PI_USER)@$(PI_HOST) "systemctl restart lumi.service"

deploy-bootstrap: build-bootstrap
	scp bootstrap-server $(PI_USER)@$(PI_HOST):/usr/local/bin/bootstrap-server
	ssh $(PI_USER)@$(PI_HOST) "systemctl restart bootstrap.service"

deploy-all: deploy-lamp deploy-bootstrap lelamp-deploy web-deploy

upload-lamp: build-lamp
	scripts/upload-intern.sh

upload-bootstrap: build-bootstrap
	scripts/upload-bootstrap.sh

# ============================================================================
# Dev shortcuts
# ============================================================================

.PHONY: clean

clean:
	rm -f lumi-server bootstrap-server
	rm -rf $(LELAMP_DIR)/.venv $(LELAMP_DIR)/__pycache__
	rm -rf web/dist web/node_modules
