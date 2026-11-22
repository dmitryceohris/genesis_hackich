
from generator.company import generate_company
from generator.invoices import generate_invoices
from generator.payments import generate_payments
from generator.ledger import generate_ledger
from generator.fx import generate_fx
from generator.error_injection import inject_errors, ERROR_TYPES
from generator.validator import (
    validate_clean_data,
    validate_public_data,
)
from generator.truth import validate_truth


def generate_episode(
    seed: int,
    config: dict | None = None,
) -> dict:

    config = config or {}

    company_data = generate_company(
        seed,
        config.get("company", {}),
    )

    company = company_data["company"]
    manifest = company_data["manifest"]

    # Generate clean source data
    invoices = generate_invoices(
        seed,
        manifest,
        config.get("n_invoices", 50),
    )

    payments = generate_payments(
        seed,
        manifest,
        invoices,
    )

    ledger = generate_ledger(
        seed,
        manifest,
        invoices,
        payments,
    )

    fx = generate_fx(seed, manifest)

    # Validate clean financial history before mutations
    validate_clean_data(
        manifest,
        ledger,
        invoices,
        payments,
        fx,
    )

    # Inject deliberate financial errors
    injected = inject_errors(
        seed=seed,
        manifest=manifest,
        ledger=ledger,
        invoices=invoices,
        payments=payments,
        fx=fx,
        config={
    "error_types": config.get(
        "error_types",
        ERROR_TYPES,
    ),
    "interaction_scenario": config.get(
        "interaction_scenario"
    ),
},
    )

    final_ledger = injected["ledger"]
    final_invoices = injected["invoices"]
    final_payments = injected["payments"]
    final_fx = injected["fx"]

    # Validate public data without rejecting intentional errors
    validate_public_data(
        manifest,
        final_ledger,
        final_invoices,
        final_payments,
        final_fx,
    )

    # Validate private answer key and provenance
    validate_truth(
        injected["truth"],
        injected["provenance"],
        final_ledger,
        final_invoices,
        final_payments,
        final_fx,
    )

    policy = {
        "policy_version": "1.0",
        "accounting_basis": "accrual",
        "base_currency": manifest["base_currency"],
        "period_start": manifest["period_start"],
        "period_end": manifest["period_end"],
        "timezone": manifest["timezone"],
        "fx_policy": {
            "source": "SYNTHETIC_DAILY",
            "rate_type": "daily",
            "conversion_rule": (
                "Use the rate corresponding to the transaction date."
            ),
        },
        "invoice_policy": {
            "duplicate_document_numbers": False,
            "payment_allocation_required": True,
        },
        "payment_policy": {
    "allocation_total_must_equal_payment": True,
    "partial_payments_allowed": True,
    "refunds_allowed": True,
    "refunds_must_reference_original_payment": True,
    "cumulative_refunds_cannot_exceed_original": True,
},
        "period_policy": {
            "postings_must_be_within_reporting_period": True,
        },
    }

    manifest["counts"] = {
        "ledger_entries": len(final_ledger),
        "invoices": len(final_invoices),
        "payments": len(final_payments),
        "fx_rates": len(final_fx),
        "documents": len(final_invoices) + len(final_payments),
        "errors": len(injected["truth"]),
    }

    return {
        "manifest": manifest,
        "company": company,
        "public": {
            "ledger": final_ledger,
            "invoices": final_invoices,
            "payments": final_payments,
            "fx": final_fx,
            "policy": policy,
        },
        "private": {
            "truth": injected["truth"],
            "provenance": injected["provenance"],
        },
    }
