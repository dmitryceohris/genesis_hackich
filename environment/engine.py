from copy import deepcopy
from decimal import Decimal, InvalidOperation

from generator.generator import generate_episode
from evaluator.scoring import score_findings


class FinAuditEnvironment:
    MAX_STEPS = 100
    MAX_FINDINGS = 30
    MAX_EVIDENCE_IDS = 10
    PAGE_SIZE = 50

    RECORD_TYPES = {
        "ledger": "ledger",
        "invoices": "invoices",
        "payments": "payments",
        "fx": "fx",
    }

    ID_FIELDS = {
        "ledger": "entry_id",
        "invoices": "invoice_id",
        "payments": "payment_id",
        "fx": "fx_id",
    }

    def __init__(self, seed=42):
        self.seed = seed
        self.public = None
        self.manifest = None
        self.company = None
        self._truth = None
        self.steps = 0
        self.done = False
        self.findings = []

    def reset(self, seed=None):
        if seed is not None:
            self.seed = seed

        episode = generate_episode(self.seed)

        self.public = deepcopy(episode["public"])
        self.manifest = deepcopy(episode["manifest"])
        self.company = deepcopy(episode["company"])

        self._truth = deepcopy(episode["private"]["truth"])

        self.steps = 0
        self.done = False
        self.findings = []

        observation = {
            "manifest": deepcopy(self.manifest),
            "company": deepcopy(self.company),
            "policy": deepcopy(self.public["policy"]),
            "available_actions": [
                "list_records",
                "get_record",
                "get_document",
                "calculator",
                "submit",
            ],
            "remaining_steps": self.MAX_STEPS,
        }

        return observation, {"seed": self.seed}

    def _error(self, message):
        return {
            "error": message,
            "remaining_steps": max(0, self.MAX_STEPS - self.steps),
        }

    def _get_records(self, record_type):
        if record_type not in self.RECORD_TYPES:
            raise ValueError(f"Unsupported record_type: {record_type}")

        key = self.RECORD_TYPES[record_type]
        return self.public[key]

    def _find_record(self, record_type, record_id):
        records = self._get_records(record_type)
        id_field = self.ID_FIELDS[record_type]

        for record in records:
            if record.get(id_field) == record_id:
                return deepcopy(record)

        return None

    def _list_records(self, action):
        record_type = action.get("record_type")
        records = self._get_records(record_type)

        offset = action.get("offset", 0)
        limit = action.get("limit", self.PAGE_SIZE)

        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")

        if not isinstance(limit, int) or not 1 <= limit <= self.PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {self.PAGE_SIZE}")

        filters = action.get("filters", {})

        if not isinstance(filters, dict):
            raise ValueError("filters must be an object")

        filtered = []

        for record in records:
            matches = all(
                record.get(field) == value
                for field, value in filters.items()
            )

            if matches:
                filtered.append(record)

        page = filtered[offset:offset + limit]

        return {
            "record_type": record_type,
            "records": deepcopy(page),
            "offset": offset,
            "returned": len(page),
            "total_matching": len(filtered),
            "has_more": offset + len(page) < len(filtered),
        }

    def _get_document(self, document_id):
        for record_type in ("invoices", "payments"):
            result = self._find_record(record_type, document_id)

            if result is not None:
                return {
                    "document_type": record_type,
                    "document": result,
                }

        return None

    def _calculate(self, action):
        operation = action.get("operation")
        values = action.get("values")

        if not isinstance(values, list) or len(values) != 2:
            raise ValueError("calculator requires exactly two values")

        try:
            a = Decimal(str(values[0]))
            b = Decimal(str(values[1]))
        except InvalidOperation:
            raise ValueError("calculator values must be numeric")

        if not a.is_finite() or not b.is_finite():
            raise ValueError("calculator values must be finite")

        if operation == "add":
            result = a + b
        elif operation == "subtract":
            result = a - b
        elif operation == "multiply":
            result = a * b
        elif operation == "divide":
            if b == 0:
                raise ValueError("division by zero")
            result = a / b
        else:
            raise ValueError("operation must be add, subtract, multiply, or divide")

        return {"result": str(result)}

    def _validate_findings(self, findings):
        if not isinstance(findings, list):
            raise ValueError("findings must be a list")

        if len(findings) > self.MAX_FINDINGS:
            raise ValueError(
                f"Maximum findings allowed: {self.MAX_FINDINGS}"
            )

        validated = []

        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                raise ValueError(f"Finding {index} must be an object")

            error_type = finding.get("type")
            affected_ids = finding.get("affected_ids")
            evidence_ids = finding.get("evidence_ids", [])

            if not isinstance(error_type, str) or not error_type:
                raise ValueError(f"Finding {index}: invalid type")

            if not isinstance(affected_ids, list) or not affected_ids:
                raise ValueError(
                    f"Finding {index}: affected_ids must be a non-empty list"
                )

            if not all(isinstance(x, str) and x for x in affected_ids):
                raise ValueError(f"Finding {index}: invalid affected_ids")

            if not isinstance(evidence_ids, list):
                raise ValueError(f"Finding {index}: evidence_ids must be a list")

            if len(evidence_ids) > self.MAX_EVIDENCE_IDS:
                raise ValueError(
                    f"Finding {index}: maximum {self.MAX_EVIDENCE_IDS} evidence IDs"
                )

            if not all(isinstance(x, str) and x for x in evidence_ids):
                raise ValueError(f"Finding {index}: invalid evidence_ids")

            validated.append({
                "type": error_type,
                "affected_ids": list(affected_ids),
                "evidence_ids": list(evidence_ids),
                "explanation": str(finding.get("explanation", "")),
            })

        return validated

    def step(self, action):
        if self.public is None:
            raise RuntimeError("Call reset() before step()")

        if self.done:
            raise RuntimeError("Episode is finished. Call reset().")

        if not isinstance(action, dict):
            raise TypeError("action must be a dictionary")

        action_type = action.get("type")

        if action_type != "submit":
            if self.steps >= self.MAX_STEPS:
                self.done = True
                return {}, -1.0, False, True, {
                    "error": "Maximum steps reached",
                }

            self.steps += 1

        try:
            if action_type == "list_records":
                result = self._list_records(action)

            elif action_type == "get_record":
                record_type = action.get("record_type")
                record_id = action.get("record_id")

                if record_type not in self.RECORD_TYPES:
                    raise ValueError("Unsupported record_type")

                result = self._find_record(record_type, record_id)

                if result is None:
                    result = {"error": "Record not found"}

            elif action_type == "get_document":
                document_id = action.get("document_id")

                if not isinstance(document_id, str):
                    raise ValueError("document_id must be a string")

                result = self._get_document(document_id)

                if result is None:
                    result = {"error": "Document not found"}

            elif action_type == "calculator":
                result = self._calculate(action)

            elif action_type == "submit":
                self.findings = self._validate_findings(
                    action.get("findings", [])
                )

                self.done = True

                metrics = score_findings(
                    self.findings,
                    self._truth,
                    inspection_steps=self.steps,
                )

                return (
                    {"status": "submitted"},
                    metrics["reward"],
                    True,
                    False,
                    metrics,
                )

            else:
                raise ValueError(f"Unknown action type: {action_type}")

            return (
                {"result": result},
                0.0,
                False,
                False,
                {"remaining_steps": self.MAX_STEPS - self.steps},
            )

        except (ValueError, TypeError) as exc:
            return (
                {"error": str(exc)},
                0.0,
                False,
                False,
                {"remaining_steps": self.MAX_STEPS - self.steps},
            )