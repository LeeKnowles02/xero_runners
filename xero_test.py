import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from xero_jobs import ENDPOINTS, fetch_journal_lines_sample, get_by_path
from xero_db import delete_test_rows, insert_test_rows, log_run, log_assessment
from xero_test_assess import assess_incremental_journals


def _run_ref(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}_{int(datetime.now(timezone.utc).timestamp() * 1000) % 100000}"


def run_sample_db_test(headers: Dict[str, str], endpoint_name: str = "JournalLines", max_journals: int = 10) -> Dict[str, Any]:
    if endpoint_name != "JournalLines":
        raise ValueError("Only JournalLines is supported right now.")

    delete_test_rows(endpoint_name)
    run_ref = _run_ref("SAMPLE")
    journals, line_rows, _ = fetch_journal_lines_sample(headers=headers, max_journals=max_journals, start_after=None)
    base_cols = ENDPOINTS["JournalLines"]["columns"]
    db_rows = [{c: get_by_path(item, c) for c in base_cols} for item in line_rows]
    write_result = insert_test_rows(endpoint_name, db_rows, base_cols, run_ref=run_ref)
    log_run(endpoint_name, run_ref, "PASS", int(write_result["rows_written"]), details=f"sample journals={len(journals)}")
    return {
        "status": "PASS",
        "endpoint": endpoint_name,
        "journals_processed": len(journals),
        "rows_written": int(write_result["rows_written"]),
        "run_ref": run_ref,
    }


def run_incremental_validation_test(headers: Dict[str, str], endpoint_name: str = "JournalLines") -> Dict[str, Any]:
    if endpoint_name != "JournalLines":
        raise ValueError("Only JournalLines is supported right now.")

    base_cols = ENDPOINTS["JournalLines"]["columns"]

    # 1) CONTROL RUN (20)
    delete_test_rows(endpoint_name)
    run_ref_control = _run_ref("CTRL")
    control_journals, control_lines, checkpoint = fetch_journal_lines_sample(headers=headers, max_journals=20, start_after=None)
    control_rows = [{c: get_by_path(item, c) for c in base_cols} for item in control_lines]
    control_result = insert_test_rows(endpoint_name, control_rows, base_cols, run_ref=run_ref_control)
    log_run(endpoint_name, run_ref_control, "PASS", int(control_result["rows_written"]), details="control run")

    # 2) CLEAR TEST rows
    delete_test_rows(endpoint_name)

    # 3) BATCH A (10)
    run_ref_a = _run_ref("BATCHA")
    batch_a_journals, batch_a_lines, checkpoint_a = fetch_journal_lines_sample(headers=headers, max_journals=10, start_after=None)
    batch_a_rows = [{c: get_by_path(item, c) for c in base_cols} for item in batch_a_lines]
    batch_a_result = insert_test_rows(endpoint_name, batch_a_rows, base_cols, run_ref=run_ref_a)
    log_run(endpoint_name, run_ref_a, "PASS", int(batch_a_result["rows_written"]), details="batch A")

    # 4) BATCH B (next 10 after checkpoint)
    run_ref_b = _run_ref("BATCHB")
    start_after = checkpoint_a if checkpoint_a is not None else checkpoint
    batch_b_journals, batch_b_lines, _ = fetch_journal_lines_sample(headers=headers, max_journals=10, start_after=start_after)
    batch_b_rows = [{c: get_by_path(item, c) for c in base_cols} for item in batch_b_lines]
    batch_b_result = insert_test_rows(endpoint_name, batch_b_rows, base_cols, run_ref=run_ref_b)
    log_run(endpoint_name, run_ref_b, "PASS", int(batch_b_result["rows_written"]), details="batch B")

    # 5) ASSESSMENT
    assessment = assess_incremental_journals(control_journals, batch_a_journals, batch_b_journals)
    combined_run_ref = _run_ref("ASSESS")
    log_assessment(combined_run_ref, assessment["status"], assessment["summary"], json.dumps(assessment))

    return {
        "status": assessment["status"],
        "summary": assessment["summary"],
        "row_counts": assessment["row_counts"],
        "checks": assessment["checks"],
        "run_refs": {
            "control": run_ref_control,
            "batch_a": run_ref_a,
            "batch_b": run_ref_b,
            "assessment": combined_run_ref,
        },
        "rows_written": {
            "control": int(control_result["rows_written"]),
            "batch_a": int(batch_a_result["rows_written"]),
            "batch_b": int(batch_b_result["rows_written"]),
        },
    }


def clear_test_rows(endpoint_name: str = "JournalLines") -> Dict[str, Any]:
    result = delete_test_rows(endpoint_name)
    out: Dict[str, Any] = {
        "status": "PASS",
        "endpoint": endpoint_name,
        "rows_deleted": int(result.get("rows_deleted", 0)),
    }
    if result.get("note"):
        out["note"] = result["note"]
    return out
