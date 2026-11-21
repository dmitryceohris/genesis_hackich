
import csv
import json
from pathlib import Path
from typing import Any


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as file:
        for record in records:
            file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )


def _write_csv(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        path.write_text("", encoding="utf-8")
        return

    preferred_fields = {
        "ledger": [
            "entry_id",
            "transaction_id",
            "timestamp",
            "entity_id",
            "invoice_id",
            "payment_id",
            "currency",
            "account",
            "debit_minor",
            "credit_minor",
        ],
        "fx": [
            "fx_id",
            "date",
            "base_currency",
            "quote_currency",
            "rate",
            "source",
        ],
    }

    if path.name == "ledger.csv":
        fields = preferred_fields["ledger"]
    elif path.name == "fx.csv":
        fields = preferred_fields["fx"]
    else:
        fields = []

    all_fields = set()
    for record in records:
        all_fields.update(record.keys())

    ordered_fields = [
        field for field in fields if field in all_fields
    ]

    extra_fields = sorted(all_fields - set(ordered_fields))
    fieldnames = ordered_fields + extra_fields

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()

        for record in records:
            row = {}

            for field in fieldnames:
                value = record.get(field)

                if isinstance(value, (dict, list)):
                    value = json.dumps(
                        value,
                        ensure_ascii=False,
                        default=str,
                    )

                row[field] = value

            writer.writerow(row)


def export_episode(
    episode: dict,
    output_root: str | Path = "episodes",
    include_private: bool = True,
) -> Path:
    """
    Export a generated episode into public and private files.

    Expected input:
    {
        "manifest": {...},
        "company": {...},
        "public": {
            "ledger": [...],
            "invoices": [...],
            "payments": [...],
            "fx": [...],
            "policy": {...}
        },
        "private": {
            "truth": [...],
            "provenance": [...]
        }
    }
    """

    required_top_level = {
        "manifest",
        "company",
        "public",
        "private",
    }

    missing = required_top_level - episode.keys()
    if missing:
        raise ValueError(
            f"Episode is missing required keys: {sorted(missing)}"
        )

    manifest = episode["manifest"]
    public = episode["public"]
    private = episode["private"]

    episode_id = manifest.get("episode_id")
    if not episode_id:
        raise ValueError("manifest.episode_id is required")

    required_public = {
        "ledger",
        "invoices",
        "payments",
        "fx",
        "policy",
    }

    missing_public = required_public - public.keys()
    if missing_public:
        raise ValueError(
            f"Public data is missing: {sorted(missing_public)}"
        )

    root = Path(output_root) / episode_id
    public_dir = root / "public"
    private_dir = root / "private"

    public_dir.mkdir(parents=True, exist_ok=True)

    # Public episode files
    _write_json(root / "manifest.json", manifest)

    _write_csv(
        public_dir / "ledger.csv",
        public["ledger"],
    )

    _write_jsonl(
        public_dir / "invoices.jsonl",
        public["invoices"],
    )

    _write_jsonl(
        public_dir / "payments.jsonl",
        public["payments"],
    )

    _write_csv(
        public_dir / "fx.csv",
        public["fx"],
    )

    _write_json(
        public_dir / "policy.json",
        public["policy"],
    )

    # Private evaluation data is kept outside public/
    if include_private:
        private_dir.mkdir(parents=True, exist_ok=True)

        _write_json(
            private_dir / "truth.json",
            private["truth"],
        )

        _write_json(
            private_dir / "provenance.json",
            private["provenance"],
        )

    # Basic isolation check
    forbidden_names = {
        "truth.json",
        "provenance.json",
    }

    for path in public_dir.rglob("*"):
        if path.is_file() and path.name in forbidden_names:
            raise RuntimeError(
                f"Private file leaked into public directory: {path}"
            )

    return root
