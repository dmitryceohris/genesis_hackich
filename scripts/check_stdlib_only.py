"""Проверка, что код не зависит от сторонних пакетов.

Запуск:

    python scripts/check_stdlib_only.py

Официальная проверка идёт без сети, поэтому «зависимостей нет» должно быть
проверяемым фактом, а не фразой в README. Скрипт разбирает импорты статически
(``ast``), не исполняя модули: иначе проверка сама требовала бы установленного
окружения.

``pytest`` разрешён только в тестах и только как необязательный инструмент:
обязательный прогон идёт через ``unittest``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Каталоги с нашим кодом.
PACKAGES = (
    "evaluator",
    "policies",
    "validator",
    "generator",
    "integration",
    "environment",
    "tests",
    "scripts",
)

#: Модули в корне репозитория. Адаптер жюри — точка входа, его тоже проверяем.
ROOT_MODULES = ("judge_adapter.py",)

#: Пакеты репозитория: это не внешние зависимости.
OWN_MODULES = frozenset(PACKAGES) | {"judge_adapter"}

#: Разрешённые необязательные инструменты и где именно.
ALLOWED_OPTIONAL = {"pytest": "tests"}


def top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Относительные импорты (level > 0) всегда внутренние.
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def main() -> int:
    stdlib = set(sys.stdlib_module_names)
    offenders: list[str] = []
    optional_uses: list[str] = []
    scanned = 0

    paths = [
        path for package in PACKAGES for path in sorted((ROOT / package).rglob("*.py"))
    ]
    paths += [ROOT / name for name in ROOT_MODULES if (ROOT / name).exists()]

    for path in paths:
        scanned += 1
        relative = path.relative_to(ROOT).as_posix()
        for name in sorted(top_level_imports(path)):
            if name in stdlib or name in OWN_MODULES or name == "__future__":
                continue
            if name in ALLOWED_OPTIONAL:
                expected = ALLOWED_OPTIONAL[name]
                if relative.startswith(f"{expected}/"):
                    optional_uses.append(f"{relative}: {name}")
                else:
                    offenders.append(
                        f"{relative}: {name} разрешён только в {expected}/"
                    )
                continue
            offenders.append(f"{relative}: {name}")

    print(f"просмотрено файлов: {scanned}")
    if optional_uses:
        print("необязательные инструменты:")
        for line in optional_uses:
            print(f"  {line}")

    if offenders:
        print()
        print("сторонние зависимости времени выполнения:")
        for line in offenders:
            print(f"  {line}")
        print()
        print(
            "Либо уберите зависимость, либо зафиксируйте её в requirements.txt "
            "точной версией и хешем и обновите этот список."
        )
        return 1

    print("сторонних зависимостей времени выполнения нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
