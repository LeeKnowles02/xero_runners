#!/usr/bin/env python3
"""
CLI test: Azure SQL + Frankfurter exchange rates load.

Expects .env with AZURE_SQL_* and FRANKFURTER_* (optional).
Run: python test_exchange_rates.py
"""
from __future__ import annotations

from db import engine, smoke_test
from exchange_rates_service import (
    get_latest_exchange_rates,
    load_latest_exchange_rates,
)


def main() -> None:
    print("1) Testing Azure SQL connection…")
    eng = engine()
    smoke_test(eng)
    print("   DB connection OK")

    print("2) Calling load_latest_exchange_rates()…")
    result = load_latest_exchange_rates()
    if not result.get("ok"):
        print("   FAILED:", result.get("error"))
        if result.get("traceback"):
            print(result["traceback"])
        raise SystemExit(1)

    print(f"   rows_loaded={result['rows_loaded']}")
    print(
        f"   rate_date={result['rate_date']} base={result['base']} quotes={result['quotes']}"
    )
    print(f"   Loaded {result['base']} -> {', '.join(result['quotes'])}")
    print(f"   response_type={result.get('response_type')} api_url={result.get('api_url')}")

    print("3) Latest rows in xero.ExchangeRates…")
    rows = get_latest_exchange_rates(20)
    if not rows:
        print("   (no rows returned)")
    for r in rows:
        print(
            f"   {r['RateDate']} {r['BaseCurrency']}/{r['QuoteCurrency']} "
            f"rate={r['Rate']} provider={r['Provider']!r} loaded={r['LoadedAtUTC']}"
        )

    print("Done.")


if __name__ == "__main__":
    main()
