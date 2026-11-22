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

.PHONY: help verify test reference baselines episodes clean image agent-image agent-run docker-verify

help:
	@echo "verify     - все обязательные проверки, ненулевой код при провале"
	@echo "test       - только тесты (unittest, без внешних зависимостей)"
	@echo "reference  - независимая проверка данных и эталона"
	@echo "baselines  - прогон базовых политик, метрики и траектории"
	@echo "episodes   - записать наборы train и dev каталогами"
	@echo "clean      - удалить artifacts/ и кэш байткода"
	@echo ""
	@echo "image         - собрать образ обязательной проверки"
	@echo "docker-verify - прогнать обязательную проверку в контейнере без сети"
	@echo "agent-image   - собрать образ изоляции агента"
	@echo "agent-run     - прогнать политику в изоляции: без сети, read-only"
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

episodes:
	$(PYTHON) scripts/build_episode_sets.py

image:
	docker build -t genesis-audit-verify .

docker-verify: image
	docker run --rm --network none --cpus 2 --memory 4g genesis-audit-verify

agent-image:
	docker build -f Dockerfile.agent -t genesis-audit-agent .

# EPISODE задаёт каталог эпизода; по умолчанию первый из набора train.
EPISODE ?= episodes/train/EP-4E07408562BE

agent-run: agent-image
	$(PYTHON) -c "import pathlib; pathlib.Path('artifacts/agent').mkdir(parents=True, exist_ok=True)"
	docker run --rm --network none --read-only --cpus 2 --memory 4g 		--pids-limit 128 --cap-drop ALL --security-opt no-new-privileges 		-v "$(CURDIR)/$(EPISODE):/episode:ro" 		-v "$(CURDIR)/artifacts/agent:/out" 		genesis-audit-agent 		--policy reconcile --episode-dir /episode --out /out/submission.json

clean:
	$(PYTHON) -c "import shutil, pathlib; shutil.rmtree('artifacts', ignore_errors=True); [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
