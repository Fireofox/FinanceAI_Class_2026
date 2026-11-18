import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "Skills" / "buffett-stock-screen" / "scripts" / "collect.py"
spec = importlib.util.spec_from_file_location("buffett_collect", SCRIPT)
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)


def envelope(statement, frequency, records):
    return {"ok": True, "command": "financials", "data": {"statement": statement, "frequency": frequency, "table": {"records": records}}}


def test_normalizes_cli_rows_without_inventing_dates_or_parent_values():
    annual = envelope("income", "annual", [
        {"index": "Basic EPS", "2025-12-31 00:00:00": 3.2},
        {"index": "Gross Profit", "2025-12-31 00:00:00": 200},
        {"index": "Total Revenue", "2025-12-31 00:00:00": 1000},
    ])
    income = envelope("income", "quarterly", [
        {"index": "Total Revenue", "2026-03-31 00:00:00": 300},
        {"index": "Net Income Common Stockholders", "2026-03-31 00:00:00": 100},
    ])
    balance = envelope("balance", "quarterly", [
        {"index": "Stockholders Equity", "2026-03-31 00:00:00": 2000},
    ])
    info = {"ok": True, "data": {"currency": {"value": "TWD"}, "financialCurrency": {"value": "TWD"},
                                   "priceToBook": {"value": 1.2}, "regularMarketTime": {"value": 1735689600}}}
    shares = {"ok": True, "command": "shares", "data": {"truncated": False, "shares": [
        {"index": "2024-01-01 00:00:00+08:00", "value": 80},
        {"index": "2025-01-01 00:00:00+08:00", "value": 100},
    ]}}
    result = collect.normalize("2330.TW", annual, income, balance, info, shares)
    assert result["annual"] == [{"end": "2025-12-31", "basic_eps": 3.2, "gross_profit": 200, "revenue": 1000}]
    assert result["quarters"][0] == {"end": "2026-03-31", "standalone": True, "revenue": 300, "net_income": None, "parent_equity": None}
    assert result["shares"] == {"value": 100, "as_of": "2025-01-01"}
    assert result["price_to_book"] == {"value": 1.2, "as_of": None}


def test_rejects_mislabeled_quarters_and_unreliable_share_history():
    wrong = envelope("income", "annual", [{"index": "Total Revenue", "2025-12-31": 100}])
    assert collect.statement_table(wrong, "income", "quarterly") == {}
    for shares in (
        {"ok": True, "command": "shares", "data": {"truncated": True, "shares": [{"index": "2025-01-01", "value": 100}]}},
        {"ok": True, "command": "shares", "data": {"truncated": False, "shares": [{"index": "2025-01-01", "value": 100}, {"index": "2025-01-01", "value": 101}]}},
        {"ok": True, "command": "shares", "data": {"truncated": False, "shares": [{"index": "unknown", "value": 100}]}},
        {"ok": True, "command": "shares", "warnings": ["Excluded 1 shares records without a valid source date"], "data": {"truncated": False, "shares": [{"index": "2025-01-01", "value": 100}]}},
    ):
        assert collect.latest_dated_shares(shares) == {"value": None, "as_of": None}
    assert collect.date_value("index") is None
    assert collect.date_value("2025-12-31 not-a-timestamp") is None


def test_query_rejects_mismatched_symbol_and_explains_failure(monkeypatch, tmp_path):
    result = SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "symbol": "9999.TW"}))
    monkeypatch.setattr(collect.subprocess, "run", lambda *args, **kwargs: result)
    response = collect.query(tmp_path / "yf_query.py", ["info", "2330.TW"], "2330.TW")
    assert response["ok"] is False
    assert "symbol" in response["reason"]


def test_collector_cli_uses_existing_skill_output_and_preserves_provenance(tmp_path):
    skill_scripts = tmp_path / "yfinance-financial-data" / "scripts"
    skill_scripts.mkdir(parents=True)
    yf_script = skill_scripts / "yf_query.py"
    yf_script.write_text(
        "import json, sys\n"
        "cmd, symbol = sys.argv[1:3]\n"
        "if cmd == 'info':\n"
        "    data = {k: {'value': v} for k, v in {'symbol': symbol, 'exchange': 'TAI', 'quoteType': 'EQUITY', 'currency': 'TWD', 'financialCurrency': 'TWD', 'priceToBook': 1.2}.items()}\n"
        "elif cmd == 'shares':\n"
        "    data = {'shares': [{'index':'2025-01-01', 'value':100}], 'truncated':False}\n"
        "else:\n"
        "    statement = sys.argv[sys.argv.index('--statement')+1]\n"
        "    frequency = sys.argv[sys.argv.index('--frequency')+1]\n"
        "    data = {'statement': statement, 'frequency': frequency, 'table': {'records': [{'index':'Total Revenue', '2025-12-31 00:00:00':300}]}}\n"
        "print(json.dumps({'ok':True, 'command':cmd, 'symbol':symbol, 'data':data, 'warnings':[], 'retrieved_at_utc':'2026-01-01T00:00:00+00:00'}))\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(SCRIPT), "--symbol", "2330.TW", "--yf-script", str(yf_script)],
                            capture_output=True, text=True, encoding="utf-8", timeout=20, check=True)
    data = json.loads(result.stdout)
    assert data["identity_verified"] is True
    assert data["shares"] == {"value": 100, "as_of": "2025-01-01"}
    assert data["price_to_book"]["as_of"] is None
    assert data["collection"]["shares"]["retrieved_at_utc"] == "2026-01-01T00:00:00+00:00"
    assert data["quarters"][0]["standalone"] is True
