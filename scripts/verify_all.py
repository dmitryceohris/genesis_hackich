"""Единая команда проверки.

Запуск:

    python scripts/verify_all.py

``make verify`` делегирует сюда. Отдельный скрипт, а не только цель Makefile,
по двум причинам: обязательная проверка должна запускаться и там, где ``make``
не установлен, и шаги должны быть видны по именам, а не спрятаны в рецепте.

Шаги выполняются по порядку и не прерывают друг друга: при провале одного
остальные всё равно отчитываются, иначе одна опечатка скрывает состояние всей
сдачи. Код возврата ненулевой, если провалился хотя бы один обязательный шаг.

Сеть не нужна, внешние зависимости не нужны: только стандартная библиотека.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Минимальная целевая версия из задания.
TARGET_PYTHON = (3, 11)

#: Ключи, которых не должно быть в публичных артефактах.
FORBIDDEN_IN_ARTIFACTS = (
    "truth",
    "provenance",
    "seed",
    "issue_id",
    "expected_amount_minor",
    "acceptable_evidence_sets",
)


@dataclass
class StepResult:
    name: str
    ok: bool
    seconds: float
    detail: str = ""


def run_command(name: str, command: list[str]) -> StepResult:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - started

    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else f"код возврата {completed.returncode}"
        return StepResult(name, False, elapsed, detail)

    return StepResult(name, True, elapsed)


def check_python_version() -> StepResult:
    started = time.perf_counter()
    actual = sys.version_info[:2]
    ok = actual >= TARGET_PYTHON
    detail = (
        ""
        if ok
        else f"нужен Python {TARGET_PYTHON[0]}.{TARGET_PYTHON[1]}+, "
        f"запущен {actual[0]}.{actual[1]}"
    )
    return StepResult("версия Python", ok, time.perf_counter() - started, detail)


def check_artifacts_are_clean() -> StepResult:
    """Проверка утечки на фактически записанном файле, а не в памяти.

    Тест ловит утечку в объекте траектории. Здесь проверяется то, что реально
    уйдёт в сдачу: сериализованный файл.
    """
    started = time.perf_counter()
    path = ROOT / "artifacts" / "trajectories.jsonl"

    if not path.exists():
        return StepResult(
            "артефакты без закрытых данных",
            False,
            time.perf_counter() - started,
            "trajectories.jsonl не создан",
        )

    text = path.read_text(encoding="utf-8")
    leaked = [key for key in FORBIDDEN_IN_ARTIFACTS if key in text]
    elapsed = time.perf_counter() - started

    if leaked:
        return StepResult(
            "артефакты без закрытых данных",
            False,
            elapsed,
            f"в траекториях встречаются закрытые поля: {', '.join(leaked)}",
        )

    lines = [line for line in text.splitlines() if line.strip()]
    for line in lines:
        try:
            json.loads(line)
        except json.JSONDecodeError as error:
            return StepResult(
                "артефакты без закрытых данных",
                False,
                elapsed,
                f"строка траектории не является JSON: {error}",
            )

    return StepResult("артефакты без закрытых данных", True, elapsed, f"{len(lines)} строк")


def main() -> int:
    steps: list[StepResult] = [check_python_version()]

    steps.append(
        run_command(
            "тесты контракта, награды, политик и парных проверок",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        )
    )
    steps.append(
        run_command(
            "независимая проверка данных и эталона",
            [sys.executable, "scripts/verify_episodes.py"],
        )
    )
    steps.append(
        run_command(
            "прогон базовых политик и запись траекторий",
            [sys.executable, "scripts/baseline_matrix.py"],
        )
    )
    steps.append(check_artifacts_are_clean())

    width = max(len(step.name) for step in steps)
    print()
    for step in steps:
        mark = "OK  " if step.ok else "FAIL"
        suffix = f"  {step.detail}" if step.detail else ""
        print(f"{mark} {step.name:<{width}}  {step.seconds:6.2f}s{suffix}")

    failed = [step.name for step in steps if not step.ok]
    print()
    if failed:
        print(f"провалено шагов: {len(failed)} из {len(steps)}")
        for name in failed:
            print(f"  - {name}")
        print()
        print("отчёты: artifacts/verification.json, artifacts/metrics.csv")
        return 1

    print(f"все шаги пройдены: {len(steps)}")
    print("отчёты: artifacts/verification.json, artifacts/metrics.csv,")
    print("        artifacts/summary.json, artifacts/trajectories.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
