from copy import deepcopy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "Skills" / "buffett-stock-screen" / "scripts" / "screen.py"
spec = importlib.util.spec_from_file_location("buffett_screen", SCRIPT)
screen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen)


@pytest.fixture
def data():
    return {
        "symbol": "2330.TW", "source": "yfinance", "financial_currency": "TWD", "price_currency": "TWD",
        "annual": [{"end": f"{year}-12-31", "basic_eps": 2, "gross_profit": 20, "revenue": 100}
                   for year in range(2021, 2026)],
        "quarters": [{"end": d, "revenue": 20, "net_income": 10, "parent_equity": 500, "standalone": True}
                     for d in ("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30")],
        "shares": {"value": 20, "as_of": "2026-09-30"},
        "price_to_book": {"value": 1.2, "as_of": "2026-11-16"},
    }


def test_all_rules_and_provenance(data):
    result = screen.evaluate(data)
    assert result["status"] == "pass"
    assert result["source"] == "yfinance"
    rules = result["conditions"]
    assert rules["annual_eps"]["periods"][0]["end"] == "2025-12-31"
    assert rules["revenue_per_share"]["value"] == 4
    assert rules["revenue_per_share"]["shares_as_of"] == "2026-09-30"
    assert rules["price_to_book"]["as_of"] == "2026-11-16"
    assert rules["roe"]["percent"] == 8
    assert rules["roe"]["start_equity"]["end"] == "2025-09-30"
    assert all(item["percent"] == 20 for item in rules["gross_margin"]["periods"])


@pytest.mark.parametrize("condition,mutate", [
    ("annual_eps", lambda d: d["annual"][0].update(basic_eps=1)),
    ("gross_margin", lambda d: d["annual"][0].update(gross_profit=10)),
    ("price_to_book", lambda d: d["price_to_book"].update(value=1.5)),
    ("revenue_per_share", lambda d: [row.update(revenue=Decimal("7.5")) for row in d["quarters"]]),
    ("roe", lambda d: [row.update(net_income=Decimal("6.25")) for row in d["quarters"]]),
])
def test_exact_threshold_fails(data, condition, mutate):
    mutate(data)
    result = screen.evaluate(data)
    assert result["conditions"][condition]["status"] == "fail"
    assert result["status"] == "fail"


def test_gross_margin_uses_decimal_before_display(data):
    data["annual"][0]["gross_profit"] = Decimal("10.00000000000000000000000000000000001")
    result = screen.evaluate(data)["conditions"]["gross_margin"]
    assert result["status"] == "pass"
    assert Decimal(result["periods"][-1]["exact_percent"]) > 10


def test_missing_dates_and_non_standalone_quarters_are_not_inferred(data):
    del data["shares"]["as_of"]
    data["price_to_book"]["as_of"] = None
    data["quarters"][-1].pop("standalone")
    result = screen.evaluate(data)
    assert result["status"] == "insufficient"
    for key in ("revenue_per_share", "price_to_book", "roe"):
        assert result["conditions"][key]["status"] == "insufficient"


def test_nonpositive_equity_and_missing_gross_are_indeterminate(data):
    data["quarters"][-1]["parent_equity"] = -500
    data["quarters"][0]["parent_equity"] = 500
    data["annual"][0]["gross_profit"] = None
    result = screen.evaluate(data)
    assert result["conditions"]["roe"]["status"] == "insufficient"
    assert result["conditions"]["gross_margin"]["status"] == "insufficient"
    assert result["status"] == "insufficient"


def test_known_failure_takes_precedence_over_other_missing_data(data):
    data["annual"][0]["basic_eps"] = 1
    data["shares"]["as_of"] = None
    assert screen.evaluate(data)["status"] == "fail"


@pytest.mark.parametrize("mutation,conditions", [
    (lambda d: d["annual"].pop(), ["annual_eps", "gross_margin"]),
    (lambda d: d["quarters"].pop(2), ["revenue_per_share", "roe"]),
    (lambda d: d["annual"].append(deepcopy(d["annual"][0])), ["annual_eps", "gross_margin"]),
    (lambda d: d.update(financial_currency="USD"), ["annual_eps", "gross_margin", "revenue_per_share", "roe"]),
    (lambda d: d.update(source="unknown"), ["annual_eps", "gross_margin", "revenue_per_share", "roe", "price_to_book"]),
])
def test_incomplete_periods_or_provenance_are_not_guessed(data, mutation, conditions):
    mutation(data)
    result = screen.evaluate(data)
    for condition in conditions:
        assert result["conditions"][condition]["status"] == "insufficient"


def test_invalid_symbol_rejected(data):
    data["symbol"] = "2330"
    with pytest.raises(ValueError, match="ticker"):
        screen.evaluate(data)


def test_cli_emits_json_from_automatic_data(data):
    process = subprocess.run([sys.executable, str(SCRIPT), "--data", json.dumps(data)],
                             check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(process.stdout)["status"] == "pass"
