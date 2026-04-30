"""
Frankfurter → Azure SQL exchange rates loader for Xero Runner.

Uses db.engine() and xero.ExchangeRates / xero.ProcessLog (see sql/xero_exchange_rates.sql).
"""
from __future__ import annotations

import json
import traceback
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from sqlalchemy import text

from config.settings import get_frankfurter_settings
from db import engine

PROCESS_NAME = "Xero Exchange Rates Load"
ACTION_NAME = "Load Latest Exchange Rates"

UNSUPPORTED_FORMAT_MSG = "Unsupported Frankfurter response format. Expected dict or list."


def _safe_config_for_log() -> str:
    """Non-secret config snapshot for failure logs."""
    c = get_frankfurter_settings()
    return json.dumps(
        {
            "FRANKFURTER_BASE_URL": c["base_url"],
            "FRANKFURTER_BASE": c["base"],
            "FRANKFURTER_QUOTES": c["quotes"],
            "FRANKFURTER_PROVIDER": c["provider"],
        },
        ensure_ascii=False,
    )


def normalize_frankfurter_payload(
    data: Any,
) -> Tuple[Dict[str, Any], str]:
    """
    Normalize Frankfurter JSON to {date, base, rates: {quote: rate}}.
    Returns (normalized_dict, response_type) where response_type is 'dict' or 'list'.
    """
    if isinstance(data, dict):
        if "date" not in data or "base" not in data or "rates" not in data:
            raise ValueError(
                "Frankfurter dict response missing required keys: date, base, rates"
            )
        if not isinstance(data["rates"], dict):
            raise ValueError("Frankfurter dict response: rates must be an object")
        for q, r in data["rates"].items():
            qc = str(q).strip()
            if not qc:
                raise ValueError("Frankfurter dict: quote currency key is blank")
            try:
                float(r)
            except (TypeError, ValueError):
                raise ValueError(f"Frankfurter dict: rate for {qc} is not numeric")
        return dict(data), "dict"

    if isinstance(data, list):
        if not data:
            raise ValueError("Frankfurter list response is empty")
        first_date = None
        first_base = None
        rates: Dict[str, Any] = {}
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"Frankfurter list item {i} is not an object")
            for k in ("date", "base", "quote", "rate"):
                if k not in item:
                    raise ValueError(f"Frankfurter list item {i} missing key: {k}")
            d = item["date"]
            b = item["base"]
            q = str(item["quote"]).strip() if item["quote"] is not None else ""
            r = item["rate"]
            if not q:
                raise ValueError(f"Frankfurter list item {i}: quote currency is blank")
            try:
                float(r)
            except (TypeError, ValueError):
                raise ValueError(f"Frankfurter list item {i}: rate is not numeric")
            if first_date is None:
                first_date = d
                first_base = b
            elif str(d) != str(first_date):
                raise ValueError("Frankfurter list: all items must use the same date")
            elif str(b).upper() != str(first_base).upper():
                raise ValueError("Frankfurter list: all items must use the same base")
            rates[str(q).upper()[:3]] = r
        return {
            "date": first_date,
            "base": first_base,
            "rates": rates,
        }, "list"

    raise ValueError(UNSUPPORTED_FORMAT_MSG)


def build_frankfurter_request(
    cfg: Optional[dict] = None,
) -> Tuple[str, requests.PreparedRequest]:
    """Build a prepared GET (from/to query params) and the resolved URL for logging."""
    cfg = cfg or get_frankfurter_settings()
    url = cfg["base_url"].rstrip("/")
    quotes_list = [q.strip() for q in cfg["quotes"].split(",") if q.strip()]
    params = {
        "from": cfg["base"],
        "to": ",".join(quotes_list),
    }
    session = requests.Session()
    prep = session.prepare_request(requests.Request("GET", url, params=params))
    return prep.url, prep


def fetch_latest_exchange_rates(cfg: Optional[dict] = None) -> Tuple[Dict[str, Any], str, str]:
    """
    GET Frankfurter API; return (raw_json, full_request_url, note).
    raw_json may be dict or list before normalization.
    """
    cfg = cfg or get_frankfurter_settings()
    attempt_url, prepared = build_frankfurter_request(cfg)
    session = requests.Session()
    resp = session.send(prepared, timeout=60)
    resp.raise_for_status()
    return resp.json(), attempt_url, ""


def log_process_start(conn) -> int:
    cur = conn.execute(
        text(
            """
            INSERT INTO xero.ProcessLog (ProcessName, ActionName, Status, Detail, ErrorMessage, FinishedAtUTC)
            OUTPUT inserted.LogID
            VALUES (:pn, :an, 'STARTED', NULL, NULL, NULL)
            """
        ),
        {"pn": PROCESS_NAME, "an": ACTION_NAME},
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("ProcessLog insert did not return LogID")
    return int(row[0])


def log_process_success(conn, log_id: int, detail: str) -> None:
    conn.execute(
        text(
            """
            UPDATE xero.ProcessLog
            SET Status = 'SUCCESS',
                FinishedAtUTC = SYSUTCDATETIME(),
                Detail = :detail,
                ErrorMessage = NULL
            WHERE LogID = :id
            """
        ),
        {"id": log_id, "detail": detail[:400000] if detail else None},
    )


def log_process_failure(conn, log_id: Optional[int], error_message: str, detail: Optional[str] = None) -> None:
    if log_id is None:
        conn.execute(
            text(
                """
                INSERT INTO xero.ProcessLog (ProcessName, ActionName, Status, Detail, ErrorMessage, FinishedAtUTC)
                VALUES (:pn, :an, 'FAILED', :detail, :em, SYSUTCDATETIME())
                """
            ),
            {
                "pn": PROCESS_NAME,
                "an": ACTION_NAME,
                "detail": (detail or "")[:400000] if detail else None,
                "em": error_message[:400000] if error_message else None,
            },
        )
        return
    conn.execute(
        text(
            """
            UPDATE xero.ProcessLog
            SET Status = 'FAILED',
                FinishedAtUTC = SYSUTCDATETIME(),
                Detail = :detail,
                ErrorMessage = :em
            WHERE LogID = :id
            """
        ),
        {
            "id": log_id,
            "detail": (detail or "")[:400000] if detail else None,
            "em": error_message[:400000] if error_message else None,
        },
    )


def upsert_exchange_rates(
    conn,
    normalized: Dict[str, Any],
    *,
    provider: Optional[str],
    source_system: str = "Frankfurter",
) -> int:
    """
    MERGE rows into xero.ExchangeRates. Match on RateDate, BaseCurrency, QuoteCurrency, Provider (NULL-safe).
    Returns number of quote currencies written.
    """
    rate_date_s = normalized["date"]
    if isinstance(rate_date_s, str):
        rate_date = datetime.strptime(rate_date_s[:10], "%Y-%m-%d").date()
    elif isinstance(rate_date_s, date):
        rate_date = rate_date_s
    else:
        rate_date = rate_date_s

    base = str(normalized["base"]).strip().upper()[:3]
    rates: Dict[str, Any] = normalized["rates"]
    rows = 0
    prov = provider.strip() if provider else None
    if prov == "":
        prov = None

    merge_sql = text(
        """
        MERGE xero.ExchangeRates AS t
        USING (SELECT :rd AS RateDate, :bc AS BaseCurrency, :qc AS QuoteCurrency,
                      :rate AS Rate, :prov AS Provider, :ss AS SourceSystem) AS s
        ON t.RateDate = s.RateDate
           AND t.BaseCurrency = s.BaseCurrency
           AND t.QuoteCurrency = s.QuoteCurrency
           AND (t.Provider = s.Provider OR (t.Provider IS NULL AND s.Provider IS NULL))
        WHEN MATCHED THEN
            UPDATE SET Rate = s.Rate, LoadedAtUTC = SYSUTCDATETIME(), SourceSystem = s.SourceSystem
        WHEN NOT MATCHED THEN
            INSERT (RateDate, BaseCurrency, QuoteCurrency, Rate, Provider, SourceSystem)
            VALUES (s.RateDate, s.BaseCurrency, s.QuoteCurrency, s.Rate, s.Provider, s.SourceSystem);
        """
    )

    for quote_key, rate_val in rates.items():
        qc = str(quote_key).strip().upper()[:3]
        dec = Decimal(str(rate_val))
        conn.execute(
            merge_sql,
            {
                "rd": rate_date,
                "bc": base,
                "qc": qc,
                "rate": dec,
                "prov": prov,
                "ss": source_system[:50],
            },
        )
        rows += 1
    return rows


def load_latest_exchange_rates() -> Dict[str, Any]:
    """
    Log STARTED → fetch → validate → upsert → log SUCCESS, or log FAILED.
    Returns summary dict for UI/tests.
    """
    cfg = get_frankfurter_settings()
    log_id: Optional[int] = None
    api_url = build_frankfurter_request(cfg)[0]
    response_type = ""

    try:
        with engine().begin() as conn:
            log_id = log_process_start(conn)

        raw, api_url, _ = fetch_latest_exchange_rates(cfg)
        normalized, response_type = normalize_frankfurter_payload(raw)

        quotes_loaded = list(normalized["rates"].keys())
        rate_date_str = str(normalized["date"])[:10]
        base_s = str(normalized["base"]).upper()

        with engine().begin() as conn:
            rows_loaded = upsert_exchange_rates(
                conn,
                normalized,
                provider=cfg["provider"],
            )
            success_detail = json.dumps(
                {
                    "rows_loaded": rows_loaded,
                    "rate_date": rate_date_str,
                    "base_currency": base_s,
                    "quote_currencies": quotes_loaded,
                    "provider": cfg["provider"],
                    "api_url": api_url,
                    "response_type": response_type,
                },
                ensure_ascii=False,
            )
            log_process_success(conn, log_id, success_detail)

        return {
            "ok": True,
            "rows_loaded": rows_loaded,
            "rate_date": rate_date_str,
            "base": base_s,
            "quotes": quotes_loaded,
            "api_url": api_url,
            "response_type": response_type,
        }

    except Exception as e:
        err = str(e)
        tb = traceback.format_exc()
        detail_obj = {
            "traceback": tb,
            "api_url_attempted": api_url,
            "config": json.loads(_safe_config_for_log()),
        }
        try:
            with engine().begin() as conn:
                log_process_failure(
                    conn,
                    log_id,
                    err,
                    detail=json.dumps(detail_obj, ensure_ascii=False),
                )
        except Exception:
            pass
        return {
            "ok": False,
            "error": err,
            "traceback": tb,
            "api_url": api_url,
            "response_type": response_type or None,
        }


def get_latest_exchange_rates(limit: int = 200) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), 2000))
    with engine().connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT TOP (:lim)
                    RateDate, BaseCurrency, QuoteCurrency, Rate, Provider, SourceSystem, LoadedAtUTC
                FROM xero.ExchangeRates
                ORDER BY RateDate DESC, QuoteCurrency ASC
                """
            ),
            {"lim": lim},
        )
        rows = []
        for r in result:
            rows.append(
                {
                    "RateDate": r[0],
                    "BaseCurrency": r[1],
                    "QuoteCurrency": r[2],
                    "Rate": r[3],
                    "Provider": r[4],
                    "SourceSystem": r[5],
                    "LoadedAtUTC": r[6],
                }
            )
        return rows


def get_latest_process_logs(limit: int = 50) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), 500))
    with engine().connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT TOP (:lim)
                    LogID, ProcessName, ActionName, Status, Detail, ErrorMessage, StartedAtUTC, FinishedAtUTC
                FROM xero.ProcessLog
                WHERE ProcessName = :pn
                ORDER BY StartedAtUTC DESC
                """
            ),
            {"lim": lim, "pn": PROCESS_NAME},
        )
        out = []
        for r in result:
            out.append(
                {
                    "LogID": r[0],
                    "ProcessName": r[1],
                    "ActionName": r[2],
                    "Status": r[3],
                    "Detail": r[4],
                    "ErrorMessage": r[5],
                    "StartedAtUTC": r[6],
                    "FinishedAtUTC": r[7],
                }
            )
        return out
