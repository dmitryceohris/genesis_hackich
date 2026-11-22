"""Восстановление расхождений только из публичного снимка.

Функции здесь получают ``Snapshot`` и ничего больше: ``truth`` сюда физически
не попадает. Сравнение с эталоном делает доверенная обвязка в ``verify.py``.

Устройство отличается от политики сверки намеренно. Политика отвечает на вопрос
«что я успею найти за 100 шагов». Валидатор отвечает на другой: «какие
нарушения тождеств вообще есть в этих данных» — и перечисляет их все, включая
те, которых в эталоне нет. Необъявленное расхождение означает, что данные
противоречивы, а по критериям это не сложность, а потеря баллов.

Для каждого расхождения собираются варианты достаточного набора доказательств:
один и тот же факт можно взять и из документа, и из записи, поэтому вариантов
несколько, и эталону достаточно совпасть с любым.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import product

from .arithmetic import company_timezone, convert_minor, in_period, local_date, row_amount_minor
from .snapshot import Snapshot

DEFAULT_RULE_IDS = {
    "fx": "POLICY-FX",
    "period": "POLICY-PERIOD",
    "allocation": "POLICY-ALLOC",
    "duplicate": "POLICY-DUP",
}


@dataclass(frozen=True)
class Discrepancy:
    """Расхождение, выведенное из публичных записей."""

    kind: str
    keys: frozenset[str]
    amount_minor: int
    currency: str
    support_variants: tuple[frozenset[str], ...]
    detail: str

    def signature(self) -> tuple:
        """Канонический ключ для сравнения с эталоном."""
        return (self.kind, self.keys, self.amount_minor, self.currency)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "keys": sorted(self.keys),
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "support_variants": [sorted(group) for group in self.support_variants],
            "detail": self.detail,
        }


def _variants(fixed: set[str], alternatives: list[tuple[str, ...]]) -> tuple[frozenset[str], ...]:
    """Все достаточные наборы: фиксированная часть плюс выбор по каждому факту."""
    cleaned = {value for value in fixed if value}
    options = [tuple(value for value in group if value) for group in alternatives]
    if any(not group for group in options):
        # Факт нечем подтвердить: вариантов нет, и это поймает verify.
        return ()
    return tuple(
        frozenset(cleaned | set(combination)) for combination in product(*options)
    )


def reconstruct(snapshot: Snapshot) -> list[Discrepancy]:
    """Все расхождения снимка в детерминированном порядке."""
    rules = {**DEFAULT_RULE_IDS, **snapshot.rule_ids}
    if not snapshot.period_start:
        return []
    tz = company_timezone(snapshot.period_start)

    found = (
        _period_identity(snapshot, rules, tz)
        + _duplicate_identity(snapshot, rules)
        + _allocation_identity(snapshot, rules, tz)
        + _fx_identity(snapshot, rules, tz)
    )
    return sorted(found, key=lambda item: (item.kind, tuple(sorted(item.keys))))


def _expense_rows(snapshot: Snapshot, invoice_id: str) -> list[dict]:
    return [
        row
        for row in snapshot.ledger
        if row.get("invoice_id") == invoice_id and row.get("role") == "expense"
    ]


def _document_amount_minor(invoice: dict, row: dict) -> int:
    """Сумма искажения по документу, а не по расходному плечу проводки.

    Дубль счёта и сдвиг периода искажают книги на всю сумму документа, налог
    включительно: проводка состоит из расходного плеча, налогового и
    обязательства, и переносится или дублируется она целиком. Расходное плечо
    — только часть, и раньше сумма занижалась ровно на налог.

    ``total_minor`` берётся с документа, если он есть; иначе остаётся сумма
    строки, чтобы проверка работала и на книге без документов.
    """
    total = invoice.get("total_minor")
    if type(total) is int:
        return total
    return row_amount_minor(row)


def _period_identity(snapshot: Snapshot, rules: dict, tz) -> list[Discrepancy]:
    """Тождество: период признания расхода равен периоду даты услуги."""
    found: list[Discrepancy] = []
    for invoice in snapshot.invoices:
        invoice_id = invoice.get("invoice_id")
        service_days = [
            date.fromisoformat(item["service_date"])
            for item in invoice.get("line_items") or []
            if item.get("service_date")
        ]
        if type(invoice_id) is not str or not service_days:
            continue
        service_day = max(service_days)
        service_inside = in_period(
            service_day, snapshot.period_start, snapshot.period_end, tz
        )

        for row in _expense_rows(snapshot, invoice_id):
            timestamp = row.get("timestamp")
            if type(timestamp) is not str:
                continue
            recognition_day = local_date(timestamp, tz)
            recognition_inside = in_period(
                recognition_day, snapshot.period_start, snapshot.period_end, tz
            )
            if service_inside == recognition_inside:
                continue
            found.append(
                Discrepancy(
                    kind="period_cutoff",
                    keys=frozenset({invoice_id, row["row_id"]}),
                    amount_minor=_document_amount_minor(invoice, row),
                    currency=row.get("currency") or snapshot.base_currency,
                    support_variants=_variants(
                        {row["row_id"], rules["period"]},
                        [(invoice.get("doc_id"), invoice_id)],
                    ),
                    detail=(
                        f"услуга {service_day.isoformat()} внутри периода "
                        f"{service_inside}, признание "
                        f"{recognition_day.isoformat()} внутри периода "
                        f"{recognition_inside}"
                    ),
                )
            )
    return found


def _duplicate_identity(snapshot: Snapshot, rules: dict) -> list[Discrepancy]:
    """Тождество: одно обязательство проводится не более одного раза."""
    groups: dict[tuple, list[dict]] = {}
    for invoice in snapshot.invoices:
        obligations = frozenset(
            item.get("obligation_id")
            for item in invoice.get("line_items") or []
            if item.get("obligation_id")
        )
        if not obligations:
            continue
        groups.setdefault((invoice.get("entity_id"), obligations), []).append(invoice)

    found: list[Discrepancy] = []
    for key in sorted(groups, key=lambda item: (str(item[0]), tuple(sorted(item[1])))):
        posted = [
            invoice
            for invoice in groups[key]
            if _expense_rows(snapshot, invoice.get("invoice_id"))
        ]
        if len(posted) < 2:
            continue
        ordered = sorted(
            posted,
            key=lambda invoice: (
                invoice.get("issued_at") or "",
                invoice.get("invoice_id") or "",
            ),
        )
        original = ordered[0]
        for duplicate in ordered[1:]:
            row = _expense_rows(snapshot, duplicate["invoice_id"])[0]
            found.append(
                Discrepancy(
                    kind="duplicate_invoice",
                    keys=frozenset({duplicate["invoice_id"], row["row_id"]}),
                    amount_minor=_document_amount_minor(duplicate, row),
                    currency=row.get("currency") or snapshot.base_currency,
                    support_variants=_variants(
                        {row["row_id"], rules["duplicate"]},
                        [
                            (original.get("doc_id"), original.get("invoice_id")),
                            (duplicate.get("doc_id"), duplicate.get("invoice_id")),
                        ],
                    ),
                    detail=(
                        f"обязательство {sorted(key[1])} проведено и по "
                        f"{original.get('invoice_id')}, и по "
                        f"{duplicate.get('invoice_id')}"
                    ),
                )
            )
    return found


def _allocation_identity(snapshot: Snapshot, rules: dict, tz) -> list[Discrepancy]:
    """Тождество: распределение в журнале равно назначению в документе."""
    found: list[Discrepancy] = []
    for payment in snapshot.payments:
        payment_id = payment.get("payment_id")
        timestamp = payment.get("timestamp")
        if type(payment_id) is not str or type(timestamp) is not str:
            continue
        payment_day = local_date(timestamp, tz)

        for reference in payment.get("invoice_refs") or []:
            invoice_id = reference.get("invoice_id")
            stated = reference.get("share_minor")
            if type(invoice_id) is not str or type(stated) is not int:
                continue
            share_currency = reference.get("currency") or payment.get("currency")

            allocation_rows = [
                row
                for row in snapshot.ledger
                if row.get("payment_id") == payment_id
                and row.get("invoice_id") == invoice_id
                and row.get("role") == "allocation"
            ]
            allocated = sum(
                row.get("source_minor")
                if type(row.get("source_minor")) is int
                else row_amount_minor(row)
                for row in allocation_rows
            )
            missing = stated - allocated
            if missing == 0:
                continue

            fixed = {row["row_id"] for row in allocation_rows}
            fixed.add(rules["allocation"])

            if share_currency == snapshot.base_currency:
                amount = abs(missing)
            else:
                fx_row = snapshot.fx_rate(
                    share_currency, snapshot.base_currency, payment_day.isoformat()
                )
                if fx_row is None:
                    # Пересчитать нечем: это ловит инвариант missing_fx_fixing.
                    continue
                amount = abs(
                    convert_minor(
                        missing,
                        fx_row["rate"],
                        snapshot.exponent(share_currency),
                        snapshot.exponent(snapshot.base_currency),
                    )
                )
                # Курс обязателен в наборе: без него сумму не воспроизвести.
                fixed.add(fx_row.get("fx_id"))

            found.append(
                Discrepancy(
                    kind="payment_allocation",
                    keys=frozenset({invoice_id, payment_id}),
                    amount_minor=amount,
                    currency=snapshot.base_currency,
                    support_variants=_variants(
                        fixed, [(payment.get("doc_id"), payment_id)]
                    ),
                    detail=(
                        f"документ относит {stated}, журнал распределяет "
                        f"{allocated} в {share_currency}"
                    ),
                )
            )
    return found


def _fx_identity(snapshot: Snapshot, rules: dict, tz) -> list[Discrepancy]:
    """Тождество: денежная строка оценена по фиксингу на дату платежа."""
    payment_by_id = {
        payment.get("payment_id"): payment for payment in snapshot.payments
    }

    found: list[Discrepancy] = []
    for row in snapshot.ledger:
        if row.get("role") != "cash":
            continue
        source_currency = row.get("source_currency")
        source_minor = row.get("source_minor")
        if type(source_currency) is not str or source_currency == snapshot.base_currency:
            continue
        if type(source_minor) is not int:
            continue

        payment = payment_by_id.get(row.get("payment_id"))
        timestamp = payment["timestamp"] if payment else row.get("timestamp")
        if type(timestamp) is not str:
            continue
        rate_day = local_date(timestamp, tz)
        fx_row = snapshot.fx_rate(
            source_currency, snapshot.base_currency, rate_day.isoformat()
        )
        if fx_row is None:
            continue

        expected = convert_minor(
            source_minor,
            fx_row["rate"],
            snapshot.exponent(source_currency),
            snapshot.exponent(snapshot.base_currency),
        )
        recorded = row_amount_minor(row)
        if expected == recorded:
            continue

        found.append(
            Discrepancy(
                kind="fx_conversion",
                keys=frozenset({row.get("payment_id"), row["row_id"]} - {None}),
                amount_minor=abs(expected - recorded),
                currency=snapshot.base_currency,
                support_variants=_variants(
                    {row["row_id"], fx_row.get("fx_id"), rules["fx"]},
                    [
                        (
                            payment.get("doc_id") if payment else None,
                            payment.get("payment_id") if payment else None,
                        )
                    ],
                ),
                detail=(
                    f"по фиксингу {fx_row.get('rate')} на {rate_day.isoformat()} "
                    f"ожидается {expected}, отражено {recorded}"
                ),
            )
        )
    return found
