"""Проверка обоих контейнеров одной командой.

Запуск:

    python scripts/check_images.py

Зачем отдельный скрипт, а не строчка в README. Сборку образов на машине
разработки выполнить не удалось: Docker Desktop установлен, но его движок
требует компонента Windows ``VirtualMachinePlatform``, то есть полной
перезагрузки системы, и перед сдачей её делать не стали. Значит эта часть
остаётся непроверенной, и единственное честное, что можно сделать, — отдать
проверку одной командой, которая сама скажет, что не сошлось, вместо списка
команд, которые читающий будет вводить руками и сверять глазами.

Что проверяется:

1. образ обязательной проверки собирается;
2. он проходит обязательный прогон **с отключённой сетью** — это и есть
   доказательство офлайна, а не обещание;
3. образ изоляции агента собирается;
4. политика в нём доходит до заявки при ``--network none --read-only``, без
   прав и с лимитами;
5. в образе агента физически нет пути к эталону: ни ``generator``, ни
   ``validator``, ни ``evaluator/oracle.py``.

Код возврата ненулевой, если провалился хотя бы один шаг. Шаги не прерывают
друг друга: при провале одного остальные всё равно отчитываются, иначе одна
опечатка скрывает состояние всей сдачи.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERIFY_IMAGE = "genesis-audit-verify"
AGENT_IMAGE = "genesis-audit-agent"

#: Эпизод для прогона агента. Берётся первый из набора train.
TRAIN = ROOT / "episodes" / "train"

#: Пути, которых в образе агента быть не должно.
FORBIDDEN_PATHS = (
    "/app/generator",
    "/app/validator",
    "/app/integration",
    "/app/evaluator/oracle.py",
)


def docker_executable() -> str | None:
    """Найти docker в PATH или по обычному пути установки Docker Desktop."""
    found = shutil.which("docker")
    if found:
        return found

    candidates = (
        Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe"),
        Path("/usr/bin/docker"),
        Path("/usr/local/bin/docker"),
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def run(docker: str, arguments: list[str], timeout: int = 900):
    return subprocess.run(
        [docker, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def first_episode() -> Path | None:
    if not TRAIN.is_dir():
        return None
    directories = sorted(path for path in TRAIN.iterdir() if path.is_dir())
    return directories[0] if directories else None


def main() -> int:
    docker = docker_executable()
    if docker is None:
        print("docker не найден ни в PATH, ни по обычному пути установки.")
        print("Поставьте Docker Desktop и запустите его, затем повторите.")
        return 1

    probe = run(docker, ["version", "--format", "{{.Server.Version}}"], timeout=60)
    if probe.returncode != 0:
        print("движок Docker не отвечает:")
        print((probe.stderr or probe.stdout).strip()[:400])
        print()
        print(
            "На Windows это обычно значит, что не включён компонент "
            "VirtualMachinePlatform: включите его и перезагрузите систему."
        )
        return 1
    print(f"движок Docker: {probe.stdout.strip()}")

    episode = first_episode()
    if episode is None:
        print("нет записанных эпизодов: сначала python scripts/build_episode_sets.py")
        return 1

    output = ROOT / "artifacts" / "agent"
    output.mkdir(parents=True, exist_ok=True)

    steps: list[tuple[str, list[str]]] = [
        ("сборка образа обязательной проверки", ["build", "-t", VERIFY_IMAGE, "."]),
        (
            "обязательный прогон в контейнере без сети",
            [
                "run", "--rm", "--network", "none",
                "--cpus", "2", "--memory", "4g",
                VERIFY_IMAGE,
            ],
        ),
        (
            "сборка образа изоляции агента",
            ["build", "-f", "Dockerfile.agent", "-t", AGENT_IMAGE, "."],
        ),
        (
            "политика в изоляции: без сети, read-only, без прав",
            [
                "run", "--rm", "--network", "none", "--read-only",
                "--cpus", "2", "--memory", "4g", "--pids-limit", "128",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "-v", f"{episode}:/episode:ro",
                "-v", f"{output}:/out",
                AGENT_IMAGE,
                "--policy", "reconcile",
                "--episode-dir", "/episode",
                "--out", "/out/submission.json",
            ],
        ),
    ]

    results: list[tuple[str, bool, str]] = []

    for title, arguments in steps:
        started = time.perf_counter()
        try:
            completed = run(docker, arguments)
        except subprocess.TimeoutExpired:
            results.append((title, False, "превышено время ожидания"))
            print(f"FAIL {title}: превышено время ожидания")
            continue

        elapsed = time.perf_counter() - started
        ok = completed.returncode == 0
        detail = "" if ok else (completed.stderr or completed.stdout).strip()[:300]
        results.append((title, ok, detail))
        print(f"{'OK  ' if ok else 'FAIL'} {title}  {elapsed:.1f}s")
        if not ok:
            print(f"     {detail}")

    # Пятый шаг: в образе агента не должно быть пути к эталону. Проверяется
    # после сборки и только если она прошла.
    agent_built = any(
        ok for title, ok, _ in results if title == "сборка образа изоляции агента"
    )
    if agent_built:
        leaks = []
        for path in FORBIDDEN_PATHS:
            completed = run(
                docker,
                [
                    "run", "--rm", "--entrypoint", "python", AGENT_IMAGE,
                    "-c", f"import os,sys; sys.exit(0 if os.path.exists({path!r}) else 1)",
                ],
                timeout=120,
            )
            if completed.returncode == 0:
                leaks.append(path)
        ok = not leaks
        detail = "" if ok else f"в образе агента есть путь к эталону: {leaks}"
        results.append(("в образе агента нет пути к эталону", ok, detail))
        print(f"{'OK  ' if ok else 'FAIL'} в образе агента нет пути к эталону")
        if not ok:
            print(f"     {detail}")

    failed = [title for title, ok, _ in results if not ok]
    print()
    if failed:
        print(f"провалено шагов: {len(failed)} из {len(results)}")
        for title in failed:
            print(f"  - {title}")
        return 1

    print(f"все шаги пройдены: {len(results)}")
    print(f"заявка агента: {output / 'submission.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
