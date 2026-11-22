# Контейнер ОБЯЗАТЕЛЬНОЙ ПРОВЕРКИ: воспроизводимый офлайн-прогон make verify.
#
# Это НЕ контейнер изоляции агента: тот запускает чужой код и описан в
# Dockerfile.agent. Здесь прогоняются наши собственные тесты, поэтому образ
# содержит и генератор, и валидатор, и oracle.
#
# ЗАПОЛНИТЬ перед сдачей: закрепить базовый образ по digest, а не по тегу.
# Тег подвижен, и «тот же Dockerfile» через неделю даст другой образ.
#
#   docker pull python:3.11-slim
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.11-slim
#
# затем заменить строку FROM на python:3.11-slim@sha256:<полученный digest>.

FROM python:3.11-slim

# Детерминированность прогона. Код не зависит от порядка хеширования (все
# перечисления отсортированы), но фиксация стоит ноль и документирует намерение.
ENV PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

# Зависимостей времени выполнения нет: код на стандартной библиотеке, и это
# проверяется шагом scripts/check_stdlib_only.py внутри make verify.
# Если они появятся, устанавливать их здесь — до копирования исходников, чтобы
# слой кэшировался отдельно:
#
#   COPY requirements.txt .
#   RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY . /app

# Байт-код компилируется на этапе сборки: при read-only запуске записать его
# будет некуда, а прогон не должен на этом спотыкаться.
RUN python -m compileall -q evaluator policies validator generator integration environment runner tests scripts \
    && mkdir -p /app/artifacts \
    && chown -R 1000:1000 /app

# Непривилегированный пользователь: проверке root не нужен.
USER 1000:1000

CMD ["python", "scripts/verify_all.py"]
