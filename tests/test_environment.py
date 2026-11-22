import pytest

from environment.engine import FinAuditEnvironment
from evaluator.scoring import score_findings


def test_reset_does_not_expose_truth():
    env = FinAuditEnvironment(seed=42)
    observation, info = env.reset()

    assert "truth" not in observation
    assert "private" not in observation
    assert info["seed"] == 42


def test_list_records():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    observation, reward, terminated, truncated, info = env.step({
        "type": "list_records",
        "record_type": "invoices",
        "limit": 5,
    })

    assert len(observation["result"]["records"]) == 5
    assert reward == 0
    assert not terminated
    assert not truncated


def test_get_record():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    invoice = env.public["invoices"][0]

    observation, _, _, _, _ = env.step({
        "type": "get_record",
        "record_type": "invoices",
        "record_id": invoice["invoice_id"],
    })

    assert observation["result"]["invoice_id"] == invoice["invoice_id"]


def test_get_document():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    invoice = env.public["invoices"][0]

    observation, _, _, _, _ = env.step({
        "type": "get_document",
        "document_id": invoice["invoice_id"],
    })

    assert observation["result"]["document_type"] == "invoices"


def test_calculator():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    observation, _, _, _, _ = env.step({
        "type": "calculator",
        "operation": "add",
        "values": [100, 25],
    })

    assert observation["result"]["result"] == "125"


def test_calculator_division_by_zero():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    observation, _, _, _, _ = env.step({
        "type": "calculator",
        "operation": "divide",
        "values": [10, 0],
    })

    assert "error" in observation


def test_invalid_record_type():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    observation, _, _, _, _ = env.step({
        "type": "list_records",
        "record_type": "secrets",
    })

    assert "error" in observation


def test_step_limit():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    for _ in range(env.MAX_STEPS):
        env.step({
            "type": "list_records",
            "record_type": "invoices",
            "limit": 1,
        })

    _, reward, terminated, truncated, _ = env.step({
        "type": "list_records",
        "record_type": "invoices",
        "limit": 1,
    })

    assert truncated
    assert not terminated

    with pytest.raises(RuntimeError):
        env.step({
            "type": "list_records",
            "record_type": "invoices",
        })


def test_submission_ends_episode():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    observation, reward, terminated, truncated, info = env.step({
        "type": "submit",
        "findings": [],
    })

    assert terminated
    assert not truncated
    assert "f1" in info

    with pytest.raises(RuntimeError):
        env.step({"type": "list_records", "record_type": "invoices"})


def test_scoring_exact_match():
    truth = [{
        "type": "duplicate_invoice",
        "affected_ids": ["INV-1", "INV-2"],
    }]

    predictions = [{
        "type": "duplicate_invoice",
        "affected_ids": ["INV-2", "INV-1"],
        "evidence_ids": ["INV-1"],
    }]

    result = score_findings(predictions, truth, inspection_steps=5)

    assert result["true_positives"] == 1
    assert result["false_positives"] == 0
    assert result["false_negatives"] == 0
    assert result["f1"] == 1.0
    assert result["reward"] == pytest.approx(0.99)


def test_scoring_false_positive():
    result = score_findings(
        predictions=[{
            "type": "wrong_fx_rate",
            "affected_ids": ["FX-1"],
        }],
        truth=[],
        inspection_steps=0,
    )

    assert result["false_positives"] == 1
    assert result["precision"] == 0.0
    assert result["recall"] == 1.0
    assert result["f1"] == 0.0
    assert result["reward"] == -1.0


def test_scoring_missed_error():
    result = score_findings(
        predictions=[],
        truth=[{
            "type": "duplicate_invoice",
            "affected_ids": ["INV-1", "INV-2"],
        }],
        inspection_steps=0,
    )

    assert result["false_negatives"] == 1
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0
    assert result["reward"] == -1.0


def test_finding_limit():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    findings = [
        {
            "type": "duplicate_invoice",
            "affected_ids": [f"INV-{i}"],
            "evidence_ids": [],
        }
        for i in range(31)
    ]

    with pytest.raises(ValueError):
        env._validate_findings(findings)


def test_evidence_limit():
    env = FinAuditEnvironment(seed=42)
    env.reset()

    finding = {
        "type": "duplicate_invoice",
        "affected_ids": ["INV-1"],
        "evidence_ids": [f"ID-{i}" for i in range(11)],
    }

    with pytest.raises(ValueError):
        env._validate_findings([finding])