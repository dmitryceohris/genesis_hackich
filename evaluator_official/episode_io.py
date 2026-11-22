"""Формат эпизода на диске: запись и чтение.

Определения проверок требуют, чтобы эпизод можно было создать в каталоге
(``generate_episode(seed, config, output_dir)``) и затем загрузить именно его
(``reset`` с ``config={"mode":"closed","episode_dir":...}``). Поэтому нужен
согласованный формат файлов, и он здесь.

Раскладка каталога — из §03 задания:

    <episode_dir>/
      manifest.json
      ledger.csv
      invoices.jsonl
      payments.jsonl
      fx.csv
      policy.json
      truth.json        # закрытый, только для оценщика
      provenance.json   # закрытый, только для оценщика

Модуль живёт в ``evaluator/`` потому, что оценщик обязан читать ``truth.json``
из каталога эпизода. Генератор пишет те же файлы и может импортировать отсюда
же. Формат предложенный: если владельцы зон генератора и среды захотят другую
раскладку, меняется этот файл, а не обе стороны по отдельности.

CSV не хранит типов, поэтому числовые поля перечислены явно, а отсутствующая
ссылка записывается буквальным маркером ``null`` и превращается обратно в
``None`` при чтении — как требует §03: «Отсутствующие ссылки — явные null, а
не угаданные связи».
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

MANIFEST = "manifest.json"
LEDGER = "ledger.csv"
INVOICES = "invoices.jsonl"
PAYMENTS = "payments.jsonl"
FX = "fx.csv"
POLICY = "policy.json"
TRUTH = "truth.json"
PROVENANCE = "provenance.json"

#: Файлы, которые агент видеть не должен ни при каких условиях.
PRIVATE_FILES = (TRUTH, PROVENANCE)

#: Буквальный маркер отсутствующей ссылки в CSV.
NULL_MARKER = "null"

LEDGER_COLUMNS = (
    "row_id",
    "journal_id",
    "timestamp",
    "account",
    "role",
    "debit_minor",
    "credit_minor",
    "currency",
    "entity_id",
    "invoice_id",
    "payment_id",
    "source_doc_id",
    "source_minor",
    "source_currency",
)

#: Целочисленные поля журнала: читаются как int, а не как строка.
LEDGER_INT_COLUMNS = frozenset({"debit_minor", "credit_minor", "source_minor"})

FX_COLUMNS = ("fx_id", "date", "source_currency", "target_currency", "rate")


def _encode(value: object) -> str:
    if value is None:
        return NULL_MARKER
    return str(value)


def _decode(column: str, raw: str, int_columns: frozenset[str]) -> object:
    if raw == NULL_MARKER:
        return None
    if column in int_columns:
        return int(raw)
    return raw


def _write_csv(path: Path, rows, columns: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_encode(row.get(column)) for column in columns])


def _read_csv(path: Path, int_columns: frozenset[str]) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {
                column: _decode(column, value, int_columns)
                for column, value in row.items()
            }
            for row in reader
        ]


def _write_jsonl(path: Path, records) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_json(path: Path, payload) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_episode(episode: dict, output_dir: str | Path) -> Path:
    """Записать эпизод целиком, включая закрытую часть.

    Вызывается генератором на стороне жюри: каталог эпизода доверенный, и
    ``truth.json`` с ``provenance.json`` в нём лежать обязаны. Агент этот
    каталог не видит.
    """
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    _write_json(directory / MANIFEST, episode["manifest"])
    _write_csv(directory / LEDGER, episode.get("ledger") or [], LEDGER_COLUMNS)
    _write_jsonl(directory / INVOICES, episode.get("invoices") or [])
    _write_jsonl(directory / PAYMENTS, episode.get("payments") or [])
    _write_csv(directory / FX, episode.get("fx") or [], FX_COLUMNS)
    _write_json(directory / POLICY, episode.get("policy") or [])
    _write_json(directory / TRUTH, episode["truth"])
    _write_json(
        directory / PROVENANCE,
        episode.get("provenance")
        or {
            "episode_id": episode["manifest"]["episode_id"],
            "note": (
                "provenance не заполнен: истории генерации и внесённых "
                "изменений пока нет, её создаёт генератор"
            ),
        },
    )
    return directory


def read_public_episode(episode_dir: str | Path) -> dict:
    """Прочитать только публичную часть: то, что доступно агенту.

    ``truth.json`` и ``provenance.json`` намеренно не читаются. Это не
    экономия, а граница: функция, из которой нельзя достать эталон, не может
    случайно отдать его в наблюдение.
    """
    directory = Path(episode_dir)
    return {
        "manifest": _read_json(directory / MANIFEST, {}),
        "ledger": _read_csv(directory / LEDGER, LEDGER_INT_COLUMNS),
        "invoices": _read_jsonl(directory / INVOICES),
        "payments": _read_jsonl(directory / PAYMENTS),
        "fx": _read_csv(directory / FX, frozenset()),
        "policy": _read_json(directory / POLICY, []),
    }


def read_truth(episode_dir: str | Path) -> dict:
    """Прочитать закрытый эталон. Только доверенный процесс оценщика."""
    truth = _read_json(Path(episode_dir) / TRUTH)
    if truth is None:
        raise FileNotFoundError(f"{TRUTH} отсутствует в {episode_dir}")
    return truth


def read_provenance(episode_dir: str | Path) -> dict:
    """Прочитать закрытую историю генерации. Только процесс оценщика."""
    return _read_json(Path(episode_dir) / PROVENANCE, {})
