def run(env, seed=42):
    """Evaluator-only upper bound. Never expose this agent to participants."""
    env.reset(seed=seed)

    truth = getattr(env, "_truth", None)
    if truth is None:
        raise RuntimeError("Oracle requires evaluator-side private truth.")

    findings = []
    for item in truth:
        findings.append({
            "type": item["type"],
            "affected_ids": list(item["affected_ids"]),
            "evidence_ids": list(item.get("evidence_ids", []))[:10],
            "explanation": "Evaluator-only oracle prediction.",
        })

    return env.step({
        "type": "submit",
        "findings": findings,
    })[-1]
