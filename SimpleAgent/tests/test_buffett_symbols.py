import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "examples/Skills/buffett-stock-screen/scripts/resolve_symbols.py"


def run(code, data=None):
    command = [sys.executable, str(SCRIPT), code]
    if data is not None:
        command += ["--data", json.dumps(data)]
    return json.loads(subprocess.check_output(command, encoding="utf-8"))


def info(code, exchange, quote_type="EQUITY"):
    return {"ok": True, "command": "info", "symbol": code, "data": {
        "symbol": {"value": code}, "exchange": {"value": exchange}, "quoteType": {"value": quote_type}}}


def test_code_requires_lookup_and_full_code_is_format_only():
    assert run("2330")["candidates"] == ["2330.TW", "2330.TWO"]
    assert run("2330.tw")["status"] == "provided"
    assert run("123")["status"] == "invalid"
    assert run("AAPL")["status"] == "invalid"


def test_unique_equity_with_conclusive_ineligible_alternative():
    payload = {"results": [info("2330.TW", "TAI"), info("2330.TWO", "TWO", "ETF")]}
    assert run("2330", payload)["symbol"] == "2330.TW"


def test_full_symbol_verification_requires_matching_taiwan_equity():
    assert run("2330.TW", info("2330.TW", "TAI"))["status"] == "resolved"
    assert run("6488.TWO", info("6488.TWO", "TWO"))["status"] == "resolved"
    assert run("2330.TW", info("2330.TW", "NMS"))["status"] == "inconclusive"
    assert run("2330.TW", info("2330.TW", "TWO"))["status"] == "ineligible"
    assert run("2330.TW", {"ok": False, "symbol": "2330.TW"})["status"] == "inconclusive"


def test_ambiguity_and_missing_or_failed_data_never_guess():
    both = {"results": [info("2330.TW", "TAI"), info("2330.TWO", "TWO")]}
    assert run("2330", both)["status"] == "ambiguous"
    for other in ({"ok": False, "symbol": "2330.TWO"},
                  {"ok": True, "command": "info", "symbol": "2330.TWO", "data": {}},
                  info("2330.TWO", ""),
                  info("2330.TWO", "UNKNOWN"),
                  info("2330.TWO", "TWO", "UNKNOWN")):
        assert run("2330", {"results": [info("2330.TW", "TAI"), other]})["status"] == "inconclusive"
