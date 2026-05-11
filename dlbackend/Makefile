.PHONY: install install-cpu install-gpu install-dev start start-runpod start-jupyter test test-api test-local test-action test-action-api test-action-local test-emotion test-emotion-api test-emotion-local lint

NGINX_CONF ?= /workspace/ai-lamp-openclaw/dlbackend/nginx.conf

HOST ?= 0.0.0.0
PORT ?= 8001

# Auto-detect CUDA and install the right onnxruntime variant
install:
	@if command -v nvidia-smi > /dev/null 2>&1 && nvidia-smi > /dev/null 2>&1; then \
		echo "CUDA detected — installing onnxruntime-gpu"; \
		pip install -e ".[gpu]"; \
	else \
		echo "No CUDA detected — installing onnxruntime (CPU)"; \
		pip install -e ".[cpu]"; \
	fi

install-cpu:
	pip install -e ".[cpu]"

install-gpu:
	pip install -e ".[gpu]"

install-dev:
	pip install -e ".[cpu,dev]"

start: install
	python src/server.py --host $(HOST) --port $(PORT)

JUPYTER_PORT ?= 8890

# RunPod: install nginx if missing, start nginx proxy, then start uvicorn
start-runpod: install
	@if ! command -v nginx > /dev/null 2>&1; then \
		apt-get update && apt-get install -y nginx; \
	fi
	nginx -s stop 2>/dev/null || true
	pkill nginx 2>/dev/null || true
	nginx -c $(NGINX_CONF)
	@mkdir -p /workspace/logs/dlbackend
	python src/server.py --host 127.0.0.1 --port $(PORT) 2>&1 | multilog t s1048576 n3 /workspace/logs/dlbackend

# Start jupyter-lab on port 8890, nginx proxies /jupyter/ to it.
# Logs via multilog with rotation (1MB per file, 3 files kept).
start-jupyter:
	@if ! command -v jupyter-lab > /dev/null 2>&1; then \
		pip install jupyterlab; \
	fi
	@pkill -f "jupyter-lab" 2>/dev/null || true
	@mkdir -p /workspace/logs/jupyter
	@(sleep 3 && TOKEN=$$(grep -oP 'token=\K[a-f0-9]+' /workspace/logs/jupyter/current 2>/dev/null | tail -1); \
	if [ -n "$$TOKEN" ]; then \
		echo "Jupyter Lab: https://<host>:8888/jupyter/?token=$$TOKEN"; \
	else \
		echo "Jupyter Lab started — grep token from /workspace/logs/jupyter/current"; \
	fi) &
	jupyter-lab --ip=127.0.0.1 --port=$(JUPYTER_PORT) --no-browser --allow-root --notebook-dir=/workspace 2>&1 | multilog t s1048576 n3 /workspace/logs/jupyter

test:
	python -m pytest tests/ -v

test-api: test-action-api test-emotion-api

test-local: test-action-local test-emotion-local

test-action: test-action-api test-action-local

test-action-api:
	python -m pytest tests/action_api/ -v

test-action-local:
	python -m pytest tests/action_local/ -v

test-emotion: test-emotion-api test-emotion-local

test-emotion-api:
	python -m pytest tests/emotion_api/ -v

test-emotion-local:
	python -m pytest tests/emotion_local/ -v

lint:
	ruff check src/ tests/
