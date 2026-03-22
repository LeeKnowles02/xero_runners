from typing import Any, Dict, List, Set


def assess_incremental_journals(
    control_journals: List[Dict[str, Any]],
    batch_a_journals: List[Dict[str, Any]],
    batch_b_journals: List[Dict[str, Any]],
) -> Dict[str, Any]:
    control_ids: Set[str] = {str(j.get("JournalID")) for j in control_journals if j.get("JournalID")}
    a_ids: Set[str] = {str(j.get("JournalID")) for j in batch_a_journals if j.get("JournalID")}
    b_ids: Set[str] = {str(j.get("JournalID")) for j in batch_b_journals if j.get("JournalID")}
    combined = a_ids | b_ids

    overlap = a_ids & b_ids
    missing = control_ids - combined
    extra = combined - control_ids

    same_coverage = control_ids == combined
    no_overlap = len(overlap) == 0
    checkpoint_progressed = True
    if batch_a_journals and batch_b_journals:
        try:
            a_max = max(int(j.get("JournalNumber") or 0) for j in batch_a_journals)
            b_min = min(int(j.get("JournalNumber") or 0) for j in batch_b_journals)
            checkpoint_progressed = b_min >= a_max
        except Exception:
            checkpoint_progressed = True

    passed = same_coverage and no_overlap and checkpoint_progressed
    summary = (
        "PASS: Control coverage equals Batch A + Batch B with no overlap."
        if passed else
        "FAIL: Incremental validation mismatch detected."
    )

    return {
        "status": "PASS" if passed else "FAIL",
        "summary": summary,
        "row_counts": {
            "control_journals": len(control_ids),
            "batch_a_journals": len(a_ids),
            "batch_b_journals": len(b_ids),
            "combined_journals": len(combined),
            "overlap_journals": len(overlap),
            "missing_from_batches": len(missing),
            "extra_in_batches": len(extra),
        },
        "checks": {
            "same_journals_covered": same_coverage,
            "no_overlap": no_overlap,
            "checkpoint_progressed": checkpoint_progressed,
        },
    }
