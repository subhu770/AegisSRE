.PHONY: help install test benchmark run lint docker-build docker-up clean

PYTHON ?= python
PIP ?= pip
UVICORN ?= uvicorn
PYTEST ?= pytest

help:
	@echo "AegisSRE Automation & SRE Engine Targets:"
	@echo "  make install       Install dependencies in editable mode"
	@echo "  make test          Run full deterministic test suite with pytest"
	@echo "  make benchmark     Run 50-incident accuracy evaluation benchmark"
	@echo "  make run           Start FastAPI diagnosis service locally"
	@echo "  make docker-build  Build production container image"
	@echo "  make docker-up     Start container stack with Docker Compose"
	@echo "  make clean         Remove build artifacts and cached bytecode"

install:
	$(PIP) install -e .[dev]

test:
	$(PYTEST) -v tests/

benchmark:
	$(PYTHON) benchmarks/eval_accuracy.py

run:
	$(UVICORN) src.api.main:app --host 0.0.0.0 --port 8000 --reload

lint:
	$(PYTHON) -m ruff check src/ tests/ benchmarks/

docker-build:
	docker build -t aegis-sre:latest .

docker-up:
	docker compose up -d

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf build/ dist/ *.egg-info .pytest_cache
