from copy import deepcopy
from decimal import Decimal


CURRENCY_EXPONENTS = {
    "USD": 2, "EUR": 2, "GBP": 2, "CHF": 2,
    "KZT": 2, "JPY": 0,
}

RULES = {
    "fx": "POLICY-FX",
    "period": "POLICY-PERIOD",
    "allocation": "POLICY-ALLOC",
    "duplicate": "POLICY-DUP",
}


def adapt_episode(episode):
    """Convert our nested generator episode to the official flat schema."""
    manifest = deepcopy(episode["manifest"])
    public = episode["public"]
    private = episode["private"]

    base = manifest["base_currency"]

    manifest["currency_exponents"] = deepcopy(CURRENCY_EXPONENTS)
    manifest["record_counts"] = {
        "ledger": len(public["ledger"]),
        "invoices": len(public["invoices"]),
        "payments": len(public["payments"]),
        "fx": len(public["fx"]),
        "policy": 5,
    }

    invoice_doc_ids = {
        invoice["invoice_id"]: f"DOC-{invoice['invoice_id']}"
        for invoice in public["invoices"]
    }

    invoices = []
    for invoice in public["invoices"]:
        invoices.append({
            "doc_id": invoice_doc_ids[invoice["invoice_id"]],
            "document_number": invoice.get(
                "document_number", invoice["invoice_id"]
            ),
            "invoice_id": invoice["invoice_id"],
            "entity_id": invoice["entity_id"],
            "issued_at": invoice["invoice_date"],
            "due_at": invoice["due_date"],
            "currency": invoice["currency"],
            "total_minor": invoice["total_minor"],
            "line_items": [
                {
                    "line_id": line["line_id"],
                    "obligation_id": line["line_id"],
                    "description": line["description"],
                    "amount_minor": line["line_total_minor"] + (invoice["tax_minor"] if index == len(invoice["line_items"]) - 1 else 0),
                    "service_date": invoice["invoice_date"],
                }
                for index, line in enumerate(invoice["line_items"])
            ],
        })

    payment_doc_ids = {
        payment["payment_id"]: f"DOC-PAY-{payment['payment_id']}"
        for payment in public["payments"]
    }

    payments = []
    for payment in public["payments"]:
        payments.append({
            "doc_id": payment_doc_ids[payment["payment_id"]],
            "bank_reference": payment["bank_reference"],
            "payment_id": payment["payment_id"],
            "timestamp": payment["timestamp"],
            "currency": payment["currency"],
            "amount_minor": payment["amount_minor"],
            "kind": payment.get("payment_type", "payment"),
            "original_payment_id": payment.get("related_payment_id"),
            "invoice_refs": [
                {
                    "invoice_id": allocation["invoice_id"],
                    "share_minor": allocation["allocated_minor"],
                    "currency": payment["currency"],
                }
                for allocation in payment["allocations"]
            ],
        })

    ledger = []
    for row in public["ledger"]:
        account = row["account"]

        if account == "Operating Expenses":
            role = "expense"
        elif account == "Bank":
            role = "cash"
        elif account == "FX Revaluation":
            # Не распределение: иначе тождество распределения считало бы
            # курсовую разницу долей обязательства.
            role = "other"
        elif row["payment_id"] is not None:
            role = "allocation"
        else:
            role = "other"

        amount = row["debit_minor"] or row["credit_minor"]

        # Валютное плечо, если генератор его построил: со счёта ушла сумма в
        # иностранной валюте, в книге отражён её пересчёт. Без этих двух полей
        # ошибку пересчёта нельзя вывести из публичных записей.
        source_minor = row.get("source_minor", amount)
        source_currency = row.get("source_currency", row["currency"])

        ledger.append({
            "row_id": row["entry_id"],
            "journal_id": row["transaction_id"],
            "timestamp": row["timestamp"],
            "account": account,
            "role": role,
            "debit_minor": row["debit_minor"],
            "credit_minor": row["credit_minor"],
            "currency": row["currency"],
            "entity_id": row["entity_id"],
            "invoice_id": row["invoice_id"],
            "payment_id": row["payment_id"],
            "source_doc_id": (
                payment_doc_ids.get(row["payment_id"])
                if row["payment_id"]
                else invoice_doc_ids.get(row["invoice_id"])
            ),
            "source_minor": source_minor,
            "source_currency": source_currency,
        })

    fx = [
        {
            "fx_id": row["fx_id"],
            "date": row["date"],
            "source_currency": row["quote_currency"],
            "target_currency": row["base_currency"],
            "rate": row["rate"],
            "reference_rate": row.get("reference_rate", row["rate"]),
        }
        for row in public["fx"]
    ]

    policy = [{
        "policy_id": "POLICY-BASE",
        "accounting_basis": public["policy"]["accounting_basis"],
        "rule_ids": deepcopy(RULES),
    }]

    for key, policy_id in RULES.items():
        policy.append({
            "policy_id": policy_id,
            "rule": key,
            "policy_version": public["policy"]["policy_version"],
        })

    type_map = {
        "duplicate_invoice": "duplicate_invoice",
        "payment_allocation": "payment_allocation",
        "fx_rate": "fx_conversion",
        "accounting_period": "period_cutoff",
    }

    from validator.snapshot import public_snapshot
    from validator.reconstruction import reconstruct

    public_episode = {
        "manifest": manifest,
        "ledger": ledger,
        "invoices": invoices,
        "payments": payments,
        "fx": fx,
        "policy": policy,
    }

    from itertools import product

    discrepancies = reconstruct(public_snapshot(public_episode))
    remaining = list(discrepancies)
    issues = []
    undeclarable = []
    disagreements = []
    naming = []

    for item in private["truth"]:
        expected_kind = type_map[item["type"]]
        expected_ids = set(item.get("affected_ids", []))

        # Привязка идёт по пересечению ID, а не по одному типу. Иначе при двух
        # ошибках одного типа соответствие error_id -> расхождение становится
        # произвольным, и ссылка из provenance на issue_id перестаёт означать
        # то же событие.
        matched = [
            d for d in remaining
            if d.kind == expected_kind and (d.keys & expected_ids)
        ]

        if not matched:
            # Запасной путь: если расхождение этого типа осталось ровно одно,
            # соответствие однозначно и без пересечения ID. Генератор и
            # реконструкция могут называть затронутые записи по-разному.
            same_kind = [d for d in remaining if d.kind == expected_kind]
            if len(same_kind) == 1:
                matched = same_kind

        if not matched:
            # Ошибка внесена, но из публичных записей не выводится. Объявлять
            # её в эталоне нельзя: по контракту каждое расхождение обязано
            # быть доказуемо, иначе эталон требует недоступного факта и
            # честный агент теряет на нём recall без шансов. Такой случай —
            # дефект генератора, и он возвращается наверх отдельным списком,
            # а не падением: диагностика важнее остановки.
            undeclarable.append({
                "error_id": item["error_id"],
                "generator_type": item["type"],
                "official_type": expected_kind,
                "affected_ids": sorted(expected_ids),
                "reason": "independent_reconstruction_found_no_discrepancy",
            })
            continue

        for discrepancy in matched:
            remaining.remove(discrepancy)

        evidence_sets = [
            sorted(set().union(*variants))
            for variants in product(
                *(d.support_variants for d in matched)
            )
        ]

        reconstructed_amount = sum(d.amount_minor for d in matched)
        reconstructed_ids = set().union(*(d.keys for d in matched))

        # Сверка двух независимых выводов об одной и той же ошибке: что
        # записал генератор при внесении и что восстановила реконструкция из
        # публичных записей. Эталон берёт второе, поэтому по этим полям
        # проверка валидатора нестрогая, и расхождение нужно видеть, а не
        # прятать. Молчаливое согласие ничего не доказывает; расхождение —
        # доказывает, что одна из сторон считает не то.
        generator_amount = item.get("claimed_amount_minor")
        if generator_amount is not None and generator_amount != reconstructed_amount:
            disagreements.append({
                "error_id": item["error_id"],
                "official_type": expected_kind,
                "field": "amount_minor",
                "generator": generator_amount,
                "reconstruction": reconstructed_amount,
                "adopted": "reconstruction",
            })
        # По составу ID две стороны расходятся только если говорят о разных
        # событиях, то есть множества не пересекаются вовсе. Пересекающиеся
        # наборы при совпавших типе и сумме описывают одну и ту же ошибку
        # разными словами: генератор называет оба счёта, реконструкция —
        # счёт и строку журнала. Это соглашение об именовании, и путать его с
        # расхождением о факте нельзя — иначе таблица расхождений перестаёт
        # что-либо значить.
        if expected_ids and not (expected_ids & reconstructed_ids):
            disagreements.append({
                "error_id": item["error_id"],
                "official_type": expected_kind,
                "field": "affected_ids",
                "generator": sorted(expected_ids),
                "reconstruction": sorted(reconstructed_ids),
                "adopted": "reconstruction",
            })
        elif expected_ids != reconstructed_ids:
            naming.append({
                "error_id": item["error_id"],
                "official_type": expected_kind,
                "generator": sorted(expected_ids),
                "reconstruction": sorted(reconstructed_ids),
                "shared": sorted(expected_ids & reconstructed_ids),
            })

        issues.append({
            "issue_id": item["error_id"],
            "type": expected_kind,
            "affected_ids": sorted(reconstructed_ids),
            "expected_amount_minor": reconstructed_amount,
            "currency": matched[0].currency,
            "acceptable_evidence_sets": evidence_sets,
        })

    declared_ids = {issue["issue_id"] for issue in issues}

    # Provenance остаётся только для объявленных ошибок: условие прохождения
    # эпизода требует, чтобы каждая ошибка эталона имела запись о том, как она
    # внесена, и наоборот. Записи о недоказуемых ошибках уходят в отдельное
    # поле вместе с причиной.
    provenance = [
        deepcopy(record)
        for record in private.get("provenance", [])
        if record.get("error_id") in declared_ids
    ]
    dropped_provenance = [
        deepcopy(record)
        for record in private.get("provenance", [])
        if record.get("error_id") not in declared_ids
    ]

    return {
        "manifest": manifest,
        "ledger": ledger,
        "invoices": invoices,
        "payments": payments,
        "fx": fx,
        "policy": policy,
        "truth": {
            "episode_id": manifest["episode_id"],
            "issues": issues,
        },
        "provenance": {
            "episode_id": manifest["episode_id"],
            "records": provenance,
            "undeclarable": undeclarable,
            "undeclarable_provenance": dropped_provenance,
            "derivation_disagreements": disagreements,
            "affected_ids_naming": naming,
        },
    }
