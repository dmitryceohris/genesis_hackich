# Единая команда проверки.
#
#   make verify
#
# На Windows, где интерпретатор называется python:
#
#   make verify PYTHON=python
#
# Рецепты делегируют скриптам в scripts/, а не содержат логику сами: тогда
# обязательная проверка запускается и там, где make не установлен.

PYTHON ?= python3

.DEFAULT_GOAL := help

.PHONY: help verify test reference baselines clean

help:
	@echo "verify     - все обязательные проверки, ненулевой код при провале"
	@echo "test       - только тесты (unittest, без внешних зависимостей)"
	@echo "reference  - независимая проверка данных и эталона"
	@echo "baselines  - прогон базовых политик, метрики и траектории"
	@echo "clean      - удалить artifacts/ и кэш байткода"
	@echo ""
	@echo "PYTHON=$(PYTHON) (переопределяется: make verify PYTHON=python)"

verify:
	$(PYTHON) scripts/verify_all.py

test:
	$(PYTHON) -m unittest discover -s tests -t .

reference:
	$(PYTHON) scripts/verify_episodes.py

baselines:
	$(PYTHON) scripts/baseline_matrix.py

clean:
	$(PYTHON) -c "import shutil, pathlib; shutil.rmtree('artifacts', ignore_errors=True); [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
