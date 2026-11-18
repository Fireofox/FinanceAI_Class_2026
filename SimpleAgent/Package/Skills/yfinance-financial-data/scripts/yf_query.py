#!/usr/bin/env python3
"""CLI adapter for Yahoo Finance data, designed for Agent Skills.

Outputs JSON only (including errors); diagnostics and network libraries should not
be relied on for deterministic schemas. Yahoo data is not guaranteed real-time.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import yfinance as yf
except ImportError:
    yf = None

ROOT = Path(__file__).resolve().parents[1]
DICTIONARY = ROOT / "references" / "info_fields_zh_TW.csv"


def clean(v: Any) -> Any:
    """Convert pandas/numpy/date structures to bounded, JSON-safe values."""
    if v is None:
        return None
    if pd is not None:
        if isinstance(v, pd.DataFrame):
            df = v.copy()
            return {
                "index_name": str(df.index.name or "index"),
                "columns": [str(x) for x in df.columns],
                "records": [
                    {"index": str(idx), **{str(k): clean(val) for k, val in row.items()}}
                    for idx, row in df.iterrows()
                ],
            }
        if isinstance(v, pd.Series):
            return [{"index": str(k), "value": clean(x)} for k, x in v.items()]
        if isinstance(v, (pd.Timestamp, pd.Timedelta)):
            return str(v)
        try:
            if pd.isna(v) is True:
                return None
        except (TypeError, ValueError):
            pass
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [clean(x) for x in v]
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if hasattr(v, "item"):
        try:
            return clean(v.item())
        except (ValueError, TypeError):
            pass
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def object_table(v: Any, limit: int) -> Any:
    """Limit huge data tables without discarding table structure."""
    if pd is not None and isinstance(v, (pd.DataFrame, pd.Series)):
        return clean(v.head(limit) if limit > 0 else v)
    if isinstance(v, list):
        return clean(v[:limit] if limit > 0 else v)
    return clean(v)


def field_mapping() -> list[dict[str, str]]:
    if not DICTIONARY.exists():
        return []
    with DICTIONARY.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return rows


def translate_key(key: str) -> str | None:
    for row in field_mapping():
        english = row.get("Index / Key") or row.get("Index") or row.get("Key") or ""
        if english.strip().strip('`') == key:
            return row.get("中文名稱")
    return None


def optional_attr(obj: Any, attribute: str) -> Any:
    if not hasattr(type(obj), attribute) and attribute not in getattr(obj, "__dict__", {}):
        # Some yfinance classes expose dynamic attributes; getattr is still safe.
        pass
    return getattr(obj, attribute)


def query(t: Any, args: argparse.Namespace) -> tuple[Any, list[str]]:
    warnings: list[str] = []
    if args.command == "info":
        info = dict(t.info or {})
        keys = sorted(info) if args.all or not args.fields else [s.strip() for s in args.fields.split(",") if s.strip()]
        missing = [k for k in keys if k not in info]
        if missing:
            warnings.append("Unavailable fields: " + ", ".join(missing))
        return {k: {"value": clean(info[k]), "zh_TW": translate_key(k)} for k in keys if k in info}, warnings
    if args.command == "quote":
        f = t.fast_info
        names = ["currency", "day_high", "day_low", "exchange", "fifty_day_average", "last_price", "market_cap", "open", "previous_close", "quote_type", "ten_day_average_volume", "three_month_average_volume", "timezone", "two_hundred_day_average", "volume", "year_change", "year_high", "year_low"]
        data = {}
        for name in names:
            try:
                val = f.get(name) if hasattr(f, "get") else getattr(f, name)
                if val is not None:
                    data[name] = clean(val)
            except Exception as exc:
                warnings.append(f"{name}: {type(exc).__name__}")
        return data, warnings
    if args.command == "history":
        if args.start and args.period != "1mo":
            warnings.append("--start overrides --period")
        kw = {"interval": args.interval, "auto_adjust": args.adjust == "auto", "actions": True}
        if args.start:
            kw.update({"start": args.start})
            if args.end:
                kw["end"] = args.end
        else:
            kw["period"] = args.period
        df = t.history(**kw)
        if df is None or df.empty:
            warnings.append("No price records returned")
        return {"auto_adjust": kw["auto_adjust"], "interval": args.interval, "period": args.period if not args.start else None, "total_rows": len(df), "returned_rows": len(df) if args.limit == 0 else min(len(df), args.limit), "truncated": args.limit > 0 and len(df) > args.limit, "prices": object_table(df, args.limit)}, warnings
    if args.command == "financials":
        mapping = {"income": "income_stmt", "balance": "balance_sheet", "cashflow": "cashflow"}
        attr = mapping[args.statement]
        if args.frequency == "quarterly":
            attr = "quarterly_" + attr
        data = optional_attr(t, attr)
        if data is None or getattr(data, "empty", False):
            warnings.append("Statement unavailable")
        return {"statement": args.statement, "frequency": args.frequency, "table": object_table(data, args.limit)}, warnings
    if args.command == "shares":
        series = t.get_shares_full()
        records = []
        invalid_dates = 0
        if pd is not None and isinstance(series, pd.Series):
            for index, value in series.items():
                try:
                    if pd.isna(index):
                        raise ValueError
                    if isinstance(index, (dt.datetime, dt.date)):
                        date = index.date() if isinstance(index, dt.datetime) else index
                    elif isinstance(index, str):
                        date = dt.datetime.fromisoformat(index.strip().replace("Z", "+00:00")).date()
                    else:
                        raise ValueError
                    if not isinstance(date, dt.date):
                        raise ValueError
                except (TypeError, ValueError, OverflowError):
                    invalid_dates += 1
                    continue
                records.append({"index": date.isoformat(), "value": clean(value)})
        elif series is not None:
            warnings.append("Unsupported shares data format")
        if invalid_dates:
            warnings.append(f"Excluded {invalid_dates} shares records without a valid source date")
        records.sort(key=lambda record: record["index"], reverse=True)
        total = len(records)
        if args.limit:
            records = records[:args.limit]
        if not records:
            warnings.append("Dated shares data unavailable")
        return {"shares": records, "total_rows": total, "returned_rows": len(records), "truncated": len(records) < total}, warnings
    if args.command == "actions":
        return {args.kind: object_table(optional_attr(t, args.kind), args.limit)}, warnings
    if args.command == "analysis":
        mapping = {"targets": "analyst_price_targets", "recommendations": "recommendations", "recommendations_summary": "recommendations_summary", "upgrades": "upgrades_downgrades", "earnings": "earnings_estimate", "revenue": "revenue_estimate", "growth": "growth_estimates", "eps_trend": "eps_trend", "eps_revisions": "eps_revisions"}
        return {args.kind: object_table(optional_attr(t, mapping[args.kind]), args.limit)}, warnings
    if args.command == "holders":
        mapping = {"major": "major_holders", "institutional": "institutional_holders", "mutualfund": "mutualfund_holders", "insider": "insider_transactions", "insider_purchases": "insider_purchases"}
        return {args.kind: object_table(optional_attr(t, mapping[args.kind]), args.limit)}, warnings
    if args.command == "fund":
        funds = t.funds_data
        return {args.kind: object_table(optional_attr(funds, args.kind), args.limit)}, warnings
    if args.command == "options":
        dates = list(t.options or [])
        if args.kind == "expirations":
            return {"expirations": dates}, warnings
        if not dates:
            return {"expirations": [], args.kind: []}, ["No option expirations returned"]
        expiry = args.expiration or dates[0]
        if expiry not in dates:
            raise ValueError(f"Invalid expiration {expiry}; available: {', '.join(dates)}")
        chain = t.option_chain(expiry)
        return {"expiration": expiry, "expirations": dates, args.kind: object_table(getattr(chain, args.kind), args.limit)}, warnings
    if args.command == "news":
        try:
            items = t.get_news(count=args.limit, tab=args.tab)
        except TypeError:
            warnings.append("get_news(count, tab) unsupported; fallback to news property")
            items = t.news
        return {"items": object_table(items or [], args.limit)}, warnings
    raise ValueError(f"Unknown command {args.command}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Structured yfinance CLI for agents. JSON on stdout.")
    sub = p.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("symbols", nargs="+", help="Yahoo Finance tickers, e.g. 2330.TW AAPL BTC-USD")
    common.add_argument("--limit", type=int, default=100, help="Maximum rows per returned table (0=all)")
    common.add_argument("--output", type=str, help="Write identical JSON payload to a file")
    info = sub.add_parser("info", parents=[common]); info.add_argument("--fields", default="", help="Comma-separated keys"); info.add_argument("--all", action="store_true")
    sub.add_parser("quote", parents=[common])
    hist = sub.add_parser("history"); hist.add_argument("symbols", nargs="+", help="Yahoo Finance tickers"); hist.add_argument("--limit", type=int, default=0, help="Maximum rows (0=all, default for history)"); hist.add_argument("--output", type=str, help="Write full JSON payload to a file"); hist.add_argument("--csv", help="Export all retrieved history rows to CSV (single symbol) or per-symbol CSV files (multiple symbols)"); hist.add_argument("--period", default="1mo"); hist.add_argument("--interval", default="1d"); hist.add_argument("--start"); hist.add_argument("--end"); hist.add_argument("--adjust", choices=["auto", "raw"], default="auto")
    fin = sub.add_parser("financials", parents=[common]); fin.add_argument("--statement", choices=["income", "balance", "cashflow"], default="income"); fin.add_argument("--frequency", choices=["annual", "quarterly"], default="annual")
    sub.add_parser("shares", parents=[common], help="Dated shares outstanding from Yahoo Finance")
    act = sub.add_parser("actions", parents=[common]); act.add_argument("--kind", choices=["actions", "dividends", "splits", "capital_gains"], default="actions")
    ana = sub.add_parser("analysis", parents=[common]); ana.add_argument("--kind", choices=["targets", "recommendations", "recommendations_summary", "upgrades", "earnings", "revenue", "growth", "eps_trend", "eps_revisions"], default="targets")
    holders = sub.add_parser("holders", parents=[common]); holders.add_argument("--kind", choices=["major", "institutional", "mutualfund", "insider", "insider_purchases"], default="major")
    fund = sub.add_parser("fund", parents=[common]); fund.add_argument("--kind", choices=["description", "fund_overview", "fund_operations", "asset_classes", "top_holdings", "equity_holdings", "bond_holdings", "bond_ratings", "sector_weightings"], default="top_holdings")
    opt = sub.add_parser("options", parents=[common]); opt.add_argument("--kind", choices=["expirations", "calls", "puts"], default="expirations"); opt.add_argument("--expiration", help="YYYY-MM-DD")
    news = sub.add_parser("news", parents=[common]); news.add_argument("--tab", choices=["news", "all", "press releases"], default="news");
    fields = sub.add_parser("fields"); fields.add_argument("--search", default=""); fields.add_argument("--output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    if args.command == "fields":
        rows = field_mapping()
        search = args.search.casefold()
        rows = [r for r in rows if search in " ".join(r.values()).casefold()]
        envelope = {"ok": True, "command": "fields", "retrieved_at_utc": now, "source": "local translation dictionary", "count": len(rows), "data": rows, "warnings": ["Candidate dictionary only, not guaranteed yfinance response schema"]}
    elif yf is None or pd is None:
        envelope = {"ok": False, "command": args.command, "retrieved_at_utc": now, "source": "Yahoo Finance via yfinance", "error": {"type": "DependencyError", "message": "Create a virtual environment, run python -m pip install -r requirements.txt, then python scripts/yf_query.py ..."}}
    else:
        if args.limit < 0:
            envelope = {"ok": False, "command": args.command, "retrieved_at_utc": now, "error": {"type": "ValidationError", "message": "--limit must be >= 0"}}
        else:
            results = []
            for symbol in args.symbols:
                try:
                    data, warnings = query(yf.Ticker(symbol), args)
                    results.append({"ok": True, "command": args.command, "symbol": symbol, "retrieved_at_utc": now, "source": "Yahoo Finance via yfinance", "data": data, "warnings": warnings})
                except Exception as exc:
                    results.append({"ok": False, "command": args.command, "symbol": symbol, "retrieved_at_utc": now, "source": "Yahoo Finance via yfinance", "error": {"type": type(exc).__name__, "message": str(exc)}, "warnings": ["No data should be inferred from a failed lookup"]})
            envelope = results[0] if len(results) == 1 else {"ok": all(x["ok"] for x in results), "command": args.command, "retrieved_at_utc": now, "results": results}
    if args.command == "history" and getattr(args, "csv", None) and envelope.get("ok"):
        history_results = envelope.get("results", [envelope])
        destination = Path(args.csv)
        for result in history_results:
            if not result.get("ok"):
                continue
            prices = result["data"]["prices"]
            if not isinstance(prices, dict) or "records" not in prices:
                continue
            records = prices["records"]
            target = destination if len(history_results) == 1 else destination.with_name(f"{destination.stem}_{result['symbol'].replace('/', '_')}{destination.suffix or '.csv'}")
            target.parent.mkdir(parents=True, exist_ok=True)
            columns = ["index"] + [x for x in prices.get("columns", []) if x != "index"]
            with target.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(records)
            result["data"]["csv_file"] = str(target)
    output = json.dumps(clean(envelope), ensure_ascii=False, indent=2, allow_nan=False)
    if getattr(args, "output", None):
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    if getattr(args, "output", None) and args.command == "history":
        print(json.dumps({"ok": envelope["ok"], "command": args.command, "output_file": str(args.output), "summary": [{"symbol": x.get("symbol"), "total_rows": x.get("data", {}).get("total_rows"), "returned_rows": x.get("data", {}).get("returned_rows"), "truncated": x.get("data", {}).get("truncated"), "csv_file": x.get("data", {}).get("csv_file")} for x in envelope.get("results", [envelope])]}, ensure_ascii=False, indent=2))
    else:
        print(output)
    return 0 if envelope["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
