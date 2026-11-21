"""Эпизоды-фикстуры, собранные руками.

Зачем: оценщик и базовые политики не должны ждать генератор. Четыре эпизода
покрывают все четыре типа дефектов, взаимодействие двух дефектов на одном
платеже и чистую книгу с правдоподобными отвлекающими случаями.

Это НЕ замена генератору. Настоящие 10 train + 10 dev эпизодов делает владелец
``generator/``. Фикстуры фиксируют схему публичных записей, на которую
рассчитывают оценщик и политики:

ledger
    row_id, journal_id, timestamp, account, debit_minor, credit_minor,
    currency, entity_id, invoice_id, payment_id, role, source_doc_id,
    source_minor, source_currency
invoices
    doc_id, invoice_id, entity_id, issued_at, due_at, currency, total_minor,
    line_items[{line_id, obligation_id, description, amount_minor, service_date}]
payments
    doc_id, payment_id, timestamp, currency, amount_minor, kind,
    original_payment_id, invoice_refs[{invoice_id, share_minor, currency}]
fx
    fx_id, date, source_currency, target_currency, rate (десятичная строка)
policy
    policy_id и правила выбора даты курса, признания расхода, границы периода

Соглашения, которые надо держать синхронно с генератором:

- деньги — целые минимальные единицы; ``debit_minor``/``credit_minor`` всегда в
  базовой валюте эпизода, а исходная сумма платежа лежит в ``source_minor`` и
  ``source_currency``;
- роль строки (``role``) различает expense, liability, allocation, suspense,
  cash: оценщик и политики опираются на неё, а не на имя счёта;
- FX-ошибка объявляется один раз и ключуется платежом и строкой денежного
  счёта (``role == "cash"``), а не каждой переоценённой строкой;
- отсутствующая ссылка — ``None``, а не угаданная связь.
"""

from __future__ import annotations

PERIOD_START = "2026-03-01T00:00:00+05:00"
PERIOD_END = "2026-04-01T00:00:00+05:00"
TIMEZONE = "Asia/Almaty"
UTC_OFFSET_HOURS = 5

_POLICY = {
    "policy_id": "POLICY-V1",
    "fx_rate_date": "payment_date",
    "expense_recognition": "service_date",
    "period_boundary": "[start, end)",
    "timezone": TIMEZONE,
    "rounding": "half_even_at_conversion",
    "amount_tolerance_minor": 0,
    "rule_ids": {
        "fx": "POLICY-FX",
        "period": "POLICY-PERIOD",
        "allocation": "POLICY-ALLOC",
        "duplicate": "POLICY-DUP",
    },
}


def _manifest(episode_id: str, ledger, invoices, payments) -> dict:
    return {
        "schema_version": "1.0.0",
        "episode_id": episode_id,
        "base_currency": "USD",
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
        "timezone": TIMEZONE,
        "currency_exponents": {"USD": 2, "EUR": 2},
        "record_counts": {
            "ledger": len(ledger),
            "invoices": len(invoices),
            "payments": len(payments),
        },
        "document_count": len(invoices) + len(payments),
        "rounding": "half_even",
    }


def _row(
    row_id,
    journal_id,
    timestamp,
    account,
    role,
    debit_minor=0,
    credit_minor=0,
    invoice_id=None,
    payment_id=None,
    source_doc_id=None,
    source_minor=None,
    source_currency=None,
    entity_id="ENT-1",
):
    return {
        "row_id": row_id,
        "journal_id": journal_id,
        "timestamp": timestamp,
        "account": account,
        "role": role,
        "debit_minor": debit_minor,
        "credit_minor": credit_minor,
        "currency": "USD",
        "entity_id": entity_id,
        "invoice_id": invoice_id,
        "payment_id": payment_id,
        "source_doc_id": source_doc_id,
        "source_minor": source_minor,
        "source_currency": source_currency,
    }


def _episode(episode_id, ledger, invoices, payments, fx, issues):
    return {
        "manifest": _manifest(episode_id, ledger, invoices, payments),
        "ledger": ledger,
        "invoices": invoices,
        "payments": payments,
        "fx": fx,
        "policy": [_POLICY],
        "truth": {"episode_id": episode_id, "issues": issues},
    }


# --- EP-CLEAN: чистая книга с отвлекающими случаями ---------------------------
# Отвлекающие случаи: счёт, оплаченный двумя платежами; возврат; одинаковая
# абонентская сумма за два разных месяца.

def _clean_episode() -> dict:
    invoices = [
        {
            "doc_id": "D-INV-41",
            "invoice_id": "INV-41",
            "entity_id": "ENT-1",
            "issued_at": "2026-03-02T10:00:00+05:00",
            "due_at": "2026-03-20T10:00:00+05:00",
            "currency": "USD",
            "total_minor": 8000,
            "line_items": [
                {
                    "line_id": "LI-41-1",
                    "obligation_id": "OBL-41",
                    "description": "consulting, March",
                    "amount_minor": 8000,
                    "service_date": "2026-03-02",
                }
            ],
        },
        {
            "doc_id": "D-INV-42",
            "invoice_id": "INV-42",
            "entity_id": "ENT-2",
            "issued_at": "2026-03-05T10:00:00+05:00",
            "due_at": "2026-03-25T10:00:00+05:00",
            "currency": "USD",
            "total_minor": 2000,
            "line_items": [
                {
                    "line_id": "LI-42-1",
                    "obligation_id": "OBL-SUB-MAR",
                    "description": "subscription, March",
                    "amount_minor": 2000,
                    "service_date": "2026-03-05",
                }
            ],
        },
        {
            # Та же сумма, что у INV-42, но другое обязательство и другой месяц
            # услуги: законный повтор, не дубль.
            "doc_id": "D-INV-43",
            "invoice_id": "INV-43",
            "entity_id": "ENT-2",
            "issued_at": "2026-03-06T10:00:00+05:00",
            "due_at": "2026-03-26T10:00:00+05:00",
            "currency": "USD",
            "total_minor": 2000,
            "line_items": [
                {
                    "line_id": "LI-43-1",
                    "obligation_id": "OBL-SUB-FEB",
                    "description": "subscription, February",
                    "amount_minor": 2000,
                    "service_date": "2026-03-06",
                }
            ],
        },
    ]

    payments = [
        {
            "doc_id": "D-PAY-41",
            "payment_id": "PAY-41",
            "timestamp": "2026-03-10T12:00:00+05:00",
            "currency": "USD",
            "amount_minor": 5000,
            "kind": "payment",
            "original_payment_id": None,
            "invoice_refs": [
                {"invoice_id": "INV-41", "share_minor": 5000, "currency": "USD"}
            ],
        },
        {
            # Второй платёж по тому же счёту: законная разбивка.
            "doc_id": "D-PAY-42",
            "payment_id": "PAY-42",
            "timestamp": "2026-03-12T12:00:00+05:00",
            "currency": "USD",
            "amount_minor": 3000,
            "kind": "payment",
            "original_payment_id": None,
            "invoice_refs": [
                {"invoice_id": "INV-41", "share_minor": 3000, "currency": "USD"}
            ],
        },
        {
            "doc_id": "D-PAY-43",
            "payment_id": "PAY-43",
            "timestamp": "2026-03-18T12:00:00+05:00",
            "currency": "USD",
            "amount_minor": 2000,
            "kind": "refund",
            "original_payment_id": "PAY-41",
            "invoice_refs": [
                {"invoice_id": "INV-41", "share_minor": 2000, "currency": "USD"}
            ],
        },
    ]

    ledger = [
        # Начисления
        _row("R-41", "J-41", "2026-03-02T10:00:00+05:00", "expense:services",
             "expense", debit_minor=8000, invoice_id="INV-41",
             source_doc_id="D-INV-41"),
        _row("R-42", "J-41", "2026-03-02T10:00:00+05:00", "liability:payable",
             "liability", credit_minor=8000, invoice_id="INV-41",
             source_doc_id="D-INV-41"),
        _row("R-43", "J-42", "2026-03-05T10:00:00+05:00", "expense:subscription",
             "expense", debit_minor=2000, invoice_id="INV-42",
             source_doc_id="D-INV-42", entity_id="ENT-2"),
        _row("R-44", "J-42", "2026-03-05T10:00:00+05:00", "liability:payable",
             "liability", credit_minor=2000, invoice_id="INV-42",
             source_doc_id="D-INV-42", entity_id="ENT-2"),
        _row("R-45", "J-43", "2026-03-06T10:00:00+05:00", "expense:subscription",
             "expense", debit_minor=2000, invoice_id="INV-43",
             source_doc_id="D-INV-43", entity_id="ENT-2"),
        _row("R-46", "J-43", "2026-03-06T10:00:00+05:00", "liability:payable",
             "liability", credit_minor=2000, invoice_id="INV-43",
             source_doc_id="D-INV-43", entity_id="ENT-2"),
        # Первый платёж
        _row("R-47", "J-44", "2026-03-10T12:00:00+05:00", "liability:payable",
             "allocation", debit_minor=5000, invoice_id="INV-41",
             payment_id="PAY-41", source_doc_id="D-PAY-41",
             source_minor=5000, source_currency="USD"),
        _row("R-48", "J-44", "2026-03-10T12:00:00+05:00", "asset:bank",
             "cash", credit_minor=5000, payment_id="PAY-41",
             source_doc_id="D-PAY-41", source_minor=5000,
             source_currency="USD"),
        # Второй платёж
        _row("R-49", "J-45", "2026-03-12T12:00:00+05:00", "liability:payable",
             "allocation", debit_minor=3000, invoice_id="INV-41",
             payment_id="PAY-42", source_doc_id="D-PAY-42",
             source_minor=3000, source_currency="USD"),
        _row("R-50", "J-45", "2026-03-12T12:00:00+05:00", "asset:bank",
             "cash", credit_minor=3000, payment_id="PAY-42",
             source_doc_id="D-PAY-42", source_minor=3000,
             source_currency="USD"),
        # Возврат
        _row("R-51", "J-46", "2026-03-18T12:00:00+05:00", "asset:bank",
             "cash", debit_minor=2000, payment_id="PAY-43",
             source_doc_id="D-PAY-43", source_minor=2000,
             source_currency="USD"),
        _row("R-52", "J-46", "2026-03-18T12:00:00+05:00", "liability:payable",
             "allocation", credit_minor=2000, invoice_id="INV-41",
             payment_id="PAY-43", source_doc_id="D-PAY-43",
             source_minor=2000, source_currency="USD"),
    ]

    return _episode("EP-CLEAN", ledger, invoices, payments, [], [])


# --- EP-CUTOFF: одна ошибка отнесения к периоду -------------------------------

def _cutoff_episode() -> dict:
    invoices = [
        {
            "doc_id": "D-INV-17",
            "invoice_id": "INV-17",
            "entity_id": "ENT-3",
            "issued_at": "2026-03-31T18:00:00+05:00",
            "due_at": "2026-04-15T18:00:00+05:00",
            "currency": "USD",
            "total_minor": 25000,
            "line_items": [
                {
                    "line_id": "LI-17-1",
                    "obligation_id": "OBL-17",
                    "description": "integration work",
                    "amount_minor": 25000,
                    "service_date": "2026-03-31",
                }
            ],
        },
        {
            # Контроль: счёт выписан 1 апреля за услугу 31 марта и признан
            # в марте верно. Простое правило «дата счёта вне периода» здесь
            # даёт ложное обвинение.
            "doc_id": "D-INV-18",
            "invoice_id": "INV-18",
            "entity_id": "ENT-4",
            "issued_at": "2026-04-01T09:00:00+05:00",
            "due_at": "2026-04-20T09:00:00+05:00",
            "currency": "USD",
            "total_minor": 10000,
            "line_items": [
                {
                    "line_id": "LI-18-1",
                    "obligation_id": "OBL-18",
                    "description": "support, March",
                    "amount_minor": 10000,
                    "service_date": "2026-03-31",
                }
            ],
        },
    ]

    ledger = [
        # Дефект: обе стороны начисления проведены 1 апреля, хотя услуга
        # оказана 31 марта и по политике расход относится к марту.
        _row("R-12", "J-7", "2026-04-01T09:00:00+05:00", "expense:services",
             "expense", debit_minor=25000, invoice_id="INV-17",
             source_doc_id="D-INV-17", entity_id="ENT-3"),
        _row("R-13", "J-7", "2026-04-01T09:00:00+05:00", "liability:payable",
             "liability", credit_minor=25000, invoice_id="INV-17",
             source_doc_id="D-INV-17", entity_id="ENT-3"),
        # Контроль: признано верно.
        _row("R-14", "J-8", "2026-03-31T18:00:00+05:00", "expense:support",
             "expense", debit_minor=10000, invoice_id="INV-18",
             source_doc_id="D-INV-18", entity_id="ENT-4"),
        _row("R-15", "J-8", "2026-03-31T18:00:00+05:00", "liability:payable",
             "liability", credit_minor=10000, invoice_id="INV-18",
             source_doc_id="D-INV-18", entity_id="ENT-4"),
    ]

    issues = [
        {
            "issue_id": "ISS-CUTOFF-1",
            "type": "period_cutoff",
            "affected_ids": ["INV-17", "R-12"],
            "expected_amount_minor": 25000,
            "currency": "USD",
            "acceptable_evidence_sets": [
                ["D-INV-17", "R-12", "POLICY-PERIOD"],
                # Альтернативный достаточный набор: сам счёт как запись плюс
                # строка признания и правило.
                ["INV-17", "R-12", "POLICY-PERIOD"],
            ],
        }
    ]

    # Платежей в этом эпизоде нет: дефект относится к начислению.
    return _episode("EP-CUTOFF", ledger, invoices, [], [], issues)


# --- EP-INTERACT: FX и распределение на одном платеже -------------------------
# Базовая валюта USD. По документу все 60.00 EUR относятся к INV-21.
# Верный курс 1.25, в журнале применён 1.20, и распределено только 50.00 EUR.

def _interacting_episode() -> dict:
    invoices = [
        {
            "doc_id": "D-INV-21",
            "invoice_id": "INV-21",
            "entity_id": "ENT-5",
            "issued_at": "2026-03-10T10:00:00+05:00",
            "due_at": "2026-03-30T10:00:00+05:00",
            "currency": "EUR",
            "total_minor": 6000,
            "line_items": [
                {
                    "line_id": "LI-21-1",
                    "obligation_id": "OBL-21",
                    "description": "licence, March",
                    "amount_minor": 6000,
                    "service_date": "2026-03-10",
                }
            ],
        }
    ]

    payments = [
        {
            "doc_id": "D-PAY-21",
            "payment_id": "PAY-21",
            "timestamp": "2026-03-15T12:00:00+05:00",
            "currency": "EUR",
            "amount_minor": 6000,
            "kind": "payment",
            "original_payment_id": None,
            # Назначение платежа: все 60.00 EUR идут на INV-21.
            "invoice_refs": [
                {"invoice_id": "INV-21", "share_minor": 6000, "currency": "EUR"}
            ],
        }
    ]

    fx = [
        {
            "fx_id": "FX-1",
            "date": "2026-03-10",
            "source_currency": "EUR",
            "target_currency": "USD",
            "rate": "1.25",
        },
        {
            # Фиксинг на дату платежа: по политике именно он применяется.
            "fx_id": "FX-2",
            "date": "2026-03-15",
            "source_currency": "EUR",
            "target_currency": "USD",
            "rate": "1.25",
        },
    ]

    ledger = [
        # Начисление по верному курсу: 6000 * 1.25 = 7500.
        _row("R-19", "J-20", "2026-03-10T10:00:00+05:00", "expense:licence",
             "expense", debit_minor=7500, invoice_id="INV-21",
             source_doc_id="D-INV-21", source_minor=6000,
             source_currency="EUR", entity_id="ENT-5"),
        _row("R-20", "J-20", "2026-03-10T10:00:00+05:00", "liability:payable",
             "liability", credit_minor=7500, invoice_id="INV-21",
             source_doc_id="D-INV-21", source_minor=6000,
             source_currency="EUR", entity_id="ENT-5"),
        # Платёж: распределено 50.00 EUR по курсу 1.20 = 6000.
        _row("R-21", "J-21", "2026-03-15T12:00:00+05:00", "liability:payable",
             "allocation", debit_minor=6000, invoice_id="INV-21",
             payment_id="PAY-21", source_doc_id="D-PAY-21",
             source_minor=5000, source_currency="EUR", entity_id="ENT-5"),
        # Остаток 10.00 EUR ушёл на промежуточный счёт, тоже по 1.20.
        _row("R-22", "J-21", "2026-03-15T12:00:00+05:00", "asset:suspense",
             "suspense", debit_minor=1200, invoice_id=None,
             payment_id="PAY-21", source_doc_id="D-PAY-21",
             source_minor=1000, source_currency="EUR", entity_id="ENT-5"),
        # Денежная строка: 6000 EUR отражены как 7200 USD вместо 7500.
        _row("R-23", "J-21", "2026-03-15T12:00:00+05:00", "asset:bank",
             "cash", credit_minor=7200, payment_id="PAY-21",
             source_doc_id="D-PAY-21", source_minor=6000,
             source_currency="EUR", entity_id="ENT-5"),
    ]

    issues = [
        {
            "issue_id": "ISS-FX-1",
            "type": "fx_conversion",
            "affected_ids": ["PAY-21", "R-23"],
            # 6000 * (1.25 - 1.20) = 300 минимальных единиц USD.
            "expected_amount_minor": 300,
            "currency": "USD",
            "acceptable_evidence_sets": [
                ["D-PAY-21", "R-23", "FX-2", "POLICY-FX"],
            ],
        },
        {
            "issue_id": "ISS-ALLOC-1",
            "type": "payment_allocation",
            "affected_ids": ["INV-21", "PAY-21"],
            # Недостающие 10.00 EUR по верному курсу: 1000 * 1.25 = 1250.
            "expected_amount_minor": 1250,
            "currency": "USD",
            "acceptable_evidence_sets": [
                ["D-PAY-21", "R-21", "R-22", "POLICY-ALLOC"],
            ],
        },
    ]

    return _episode("EP-INTERACT", ledger, invoices, payments, fx, issues)


# --- EP-DUP: дубль счёта ------------------------------------------------------

def _duplicate_episode() -> dict:
    invoices = [
        {
            "doc_id": "D-INV-31",
            "invoice_id": "INV-31",
            "entity_id": "ENT-6",
            "issued_at": "2026-03-05T10:00:00+05:00",
            "due_at": "2026-03-25T10:00:00+05:00",
            "currency": "USD",
            "total_minor": 4500,
            "line_items": [
                {
                    "line_id": "LI-31-1",
                    "obligation_id": "OBL-9",
                    "description": "logistics, week 10",
                    "amount_minor": 4500,
                    "service_date": "2026-03-04",
                }
            ],
        },
        {
            # То же обязательство OBL-9 выставлено и проведено второй раз.
            "doc_id": "D-INV-32",
            "invoice_id": "INV-32",
            "entity_id": "ENT-6",
            "issued_at": "2026-03-06T10:00:00+05:00",
            "due_at": "2026-03-26T10:00:00+05:00",
            "currency": "USD",
            "total_minor": 4500,
            "line_items": [
                {
                    "line_id": "LI-32-1",
                    "obligation_id": "OBL-9",
                    "description": "logistics, week 10",
                    "amount_minor": 4500,
                    "service_date": "2026-03-04",
                }
            ],
        },
    ]

    ledger = [
        _row("R-31", "J-31", "2026-03-05T10:00:00+05:00", "expense:logistics",
             "expense", debit_minor=4500, invoice_id="INV-31",
             source_doc_id="D-INV-31", entity_id="ENT-6"),
        _row("R-32", "J-31", "2026-03-05T10:00:00+05:00", "liability:payable",
             "liability", credit_minor=4500, invoice_id="INV-31",
             source_doc_id="D-INV-31", entity_id="ENT-6"),
        _row("R-33", "J-32", "2026-03-06T10:00:00+05:00", "expense:logistics",
             "expense", debit_minor=4500, invoice_id="INV-32",
             source_doc_id="D-INV-32", entity_id="ENT-6"),
        _row("R-34", "J-32", "2026-03-06T10:00:00+05:00", "liability:payable",
             "liability", credit_minor=4500, invoice_id="INV-32",
             source_doc_id="D-INV-32", entity_id="ENT-6"),
    ]

    issues = [
        {
            "issue_id": "ISS-DUP-1",
            "type": "duplicate_invoice",
            "affected_ids": ["INV-32", "R-33"],
            "expected_amount_minor": 4500,
            "currency": "USD",
            "acceptable_evidence_sets": [
                ["D-INV-31", "D-INV-32", "R-33", "POLICY-DUP"],
            ],
        }
    ]

    return _episode("EP-DUP", ledger, invoices, [], [], issues)


def build_episodes() -> dict[str, dict]:
    """Свежая копия всех фикстур.

    Копия каждый раз: тесты перестановок и переименования меняют записи на
    месте, и общий мутируемый словарь связал бы тесты между собой.
    """
    return {
        "EP-CLEAN": _clean_episode(),
        "EP-CUTOFF": _cutoff_episode(),
        "EP-INTERACT": _interacting_episode(),
        "EP-DUP": _duplicate_episode(),
    }


def build_episode(episode_id: str) -> dict:
    episodes = build_episodes()
    if episode_id not in episodes:
        raise KeyError(f"unknown fixture episode {episode_id!r}")
    return episodes[episode_id]


EPISODE_IDS = ("EP-CLEAN", "EP-CUTOFF", "EP-INTERACT", "EP-DUP")
