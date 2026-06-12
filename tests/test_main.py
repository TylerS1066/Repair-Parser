"""
Tests for the Repair class parsing/pricing logic in main.py.

These tests only exercise pure functions (Repair.parse, Repair.total_cost,
Repair.json) and do not start the Discord client.
"""

import datetime
import json
import sys

import pytest

# Allow `import main` from the repo root when running pytest from the
# project root.
sys.path.insert(0, ".")

from main import Repair, SplitError, PricingError  # noqa: E402


SAMPLE_LOG_LINES = [
    "[12:00:00] [CHAT] Total damaged blocks: 100",
    "[12:00:01] [CHAT] Percent damaged: 12.5",
    "[12:00:02] [CHAT] Materials required:",
    "[12:00:03] [CHAT] STONE : 50",
    "[12:00:04] [CHAT] IRON_INGOT : 10",
    "[12:00:05] [CHAT] Time until completion: 3600",
    "[12:00:06] [CHAT] Money to complete repair: 500",
    "[12:00:07] [CHAT] Repairs underway: 0/1",
]


def test_parse_basic_repair():
    repair = Repair.parse(SAMPLE_LOG_LINES, 0, 6)

    assert repair.start_time == datetime.time(12, 0, 0)
    assert repair.block_count == 100
    assert repair.percent_damaged == 12.5
    assert repair.materials == {"STONE": 50, "IRON_INGOT": 10}
    assert repair.time_delay == 3600
    assert repair.cost == 500
    assert repair.started is True


def test_parse_not_started():
    # Remove the "Repairs underway: 0/1" line so `started` should be False
    lines = SAMPLE_LOG_LINES[:-1]
    repair = Repair.parse(lines, 0, 6)
    assert repair.started is False


def test_total_cost_with_prices():
    repair = Repair.parse(SAMPLE_LOG_LINES, 0, 6)
    prices = {"STONE": 1, "IRON_INGOT": 5}

    # 500 (base cost) + 50*1 + 10*5 = 600
    assert repair.total_cost(prices) == 600


def test_total_cost_missing_material_raises():
    repair = Repair.parse(SAMPLE_LOG_LINES, 0, 6)
    prices = {"STONE": 1}  # IRON_INGOT missing

    with pytest.raises(PricingError):
        repair.total_cost(prices)


def test_json_output():
    repair = Repair.parse(SAMPLE_LOG_LINES, 0, 6)
    data = json.loads(repair.json())

    assert data["block_count"] == 100
    assert data["percent_damaged"] == 12.5
    assert data["materials"] == {"STONE": 50, "IRON_INGOT": 10}
    assert data["time_delay"] == 3600
    assert data["cost"] == 500
    assert data["started"] is True


def test_split_chat_line_error():
    with pytest.raises(SplitError):
        # Missing '[CHAT] ' prefix
        Repair.parse(["[12:00:00] Total damaged blocks: 100"] + SAMPLE_LOG_LINES[1:], 0, 6)