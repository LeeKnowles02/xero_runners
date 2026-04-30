"""Xero exchange rates UI (Frankfurter → Azure SQL)."""
from flask import flash, redirect, render_template, url_for

from exchange_rates_service import (
    get_latest_exchange_rates,
    get_latest_process_logs,
    load_latest_exchange_rates,
)


def register_exchange_rates_routes(app):
    @app.get("/xero/exchange-rates")
    def exchange_rates_page():
        rates = []
        logs = []
        try:
            rates = get_latest_exchange_rates(500)
            logs = get_latest_process_logs(30)
        except Exception as e:
            flash(f"Could not load exchange rates or logs: {e}", "error")
        return render_template(
            "exchange_rates.html",
            active_page="exchange_rates",
            rates=rates,
            logs=logs,
        )

    @app.post("/xero/exchange-rates/run")
    def exchange_rates_run():
        try:
            result = load_latest_exchange_rates()
            if result.get("ok"):
                flash(
                    f"Success: loaded {result['rows_loaded']} row(s) for {result['rate_date']} "
                    f"— {result['base']} → {', '.join(result['quotes'])}.",
                    "success",
                )
            else:
                flash(
                    result.get("error") or "Load failed (see ProcessLog for details).",
                    "error",
                )
        except Exception as e:
            flash(f"Load failed: {e}", "error")
        return redirect(url_for("exchange_rates_page"))
