def _finding_key(finding):
    return (
        finding.get("type"),
        frozenset(finding.get("affected_ids", [])),
    )


def score_findings(predictions, truth, inspection_steps=0):
    if not isinstance(predictions, list):
        raise TypeError("predictions must be a list")

    if not isinstance(truth, list):
        raise TypeError("truth must be a list")

    if not isinstance(inspection_steps, int) or inspection_steps < 0:
        raise ValueError("inspection_steps must be a non-negative integer")

    truth_keys = [_finding_key(item) for item in truth]
    prediction_keys = [_finding_key(item) for item in predictions]

    unmatched_truth = list(truth_keys)
    true_positives = 0
    false_positives = 0

    for key in prediction_keys:
        if key in unmatched_truth:
            unmatched_truth.remove(key)
            true_positives += 1
        else:
            false_positives += 1

    false_negatives = len(unmatched_truth)

    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else (1.0 if not truth else 0.0)
    )

    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 1.0
    )

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    reward = max(
        -1.0,
        min(1.0, 2 * f1 - 1 - 0.002 * inspection_steps),
    )

    return {
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "inspection_steps": inspection_steps,
        "reward": reward,
    }