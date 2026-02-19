"""Tests for the automated order recommendation engine."""

import math
import pytest

from order_recommendations import (
    InventoryItem,
    OrderRecommendation,
    Priority,
    calculate_reorder_recommendations,
    get_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _item(**kwargs) -> dict:
    """Shorthand for building a minimal inventory item dict."""
    defaults = {
        "sku": "SKU000",
        "store": "Store-TEST",
        "current_stock": 100,
        "avg_weekly_sales": 10,
        "lead_time_weeks": 2,
    }
    return {**defaults, **kwargs}


# ---------------------------------------------------------------------------
# InventoryItem validation
# ---------------------------------------------------------------------------

class TestInventoryItemValidation:
    def test_valid_item_accepted(self):
        item = InventoryItem(
            sku="SKU001", store="S1", current_stock=50,
            avg_weekly_sales=5, lead_time_weeks=2
        )
        assert item.sku == "SKU001"

    def test_negative_avg_weekly_sales_raises(self):
        with pytest.raises(ValueError, match="avg_weekly_sales"):
            InventoryItem(sku="X", store="S", current_stock=10,
                          avg_weekly_sales=-1, lead_time_weeks=2)

    def test_zero_lead_time_raises(self):
        with pytest.raises(ValueError, match="lead_time_weeks"):
            InventoryItem(sku="X", store="S", current_stock=10,
                          avg_weekly_sales=5, lead_time_weeks=0)

    def test_negative_current_stock_raises(self):
        with pytest.raises(ValueError, match="current_stock"):
            InventoryItem(sku="X", store="S", current_stock=-5,
                          avg_weekly_sales=5, lead_time_weeks=2)

    def test_zero_current_stock_valid(self):
        item = InventoryItem(sku="X", store="S", current_stock=0,
                             avg_weekly_sales=5, lead_time_weeks=2)
        assert item.current_stock == 0

    def test_zero_avg_weekly_sales_valid(self):
        item = InventoryItem(sku="X", store="S", current_stock=50,
                             avg_weekly_sales=0, lead_time_weeks=2)
        assert item.avg_weekly_sales == 0


# ---------------------------------------------------------------------------
# Priority assignment
# ---------------------------------------------------------------------------

class TestPriorityAssignment:
    def test_critical_when_stock_below_lead_time(self):
        # 5 units / 5 weekly = 1 week of stock, lead time = 3 weeks → CRITICAL
        recs = calculate_reorder_recommendations([
            _item(current_stock=5, avg_weekly_sales=5, lead_time_weeks=3)
        ])
        assert recs[0].priority == Priority.CRITICAL

    def test_critical_when_zero_stock(self):
        recs = calculate_reorder_recommendations([
            _item(current_stock=0, avg_weekly_sales=10, lead_time_weeks=2)
        ])
        assert recs[0].priority == Priority.CRITICAL

    def test_high_when_at_reorder_point(self):
        # reorder_point = 10 * (2 + 2) = 40; stock = 40
        recs = calculate_reorder_recommendations([
            _item(current_stock=40, avg_weekly_sales=10, lead_time_weeks=2)
        ], safety_weeks=2)
        assert recs[0].priority == Priority.HIGH

    def test_high_when_below_reorder_point(self):
        # reorder_point = 10 * (2 + 2) = 40; stock = 35
        recs = calculate_reorder_recommendations([
            _item(current_stock=35, avg_weekly_sales=10, lead_time_weeks=2)
        ], safety_weeks=2)
        assert recs[0].priority == Priority.HIGH

    def test_medium_when_approaching_reorder_point(self):
        # reorder_point = 10 * (2+2) = 40; 1.5× = 60; stock = 55 → MEDIUM
        recs = calculate_reorder_recommendations([
            _item(current_stock=55, avg_weekly_sales=10, lead_time_weeks=2)
        ], safety_weeks=2)
        assert recs[0].priority == Priority.MEDIUM

    def test_low_when_stock_healthy(self):
        # 200 units / 10 weekly = 20 weeks; well above all thresholds
        recs = calculate_reorder_recommendations([
            _item(current_stock=200, avg_weekly_sales=10, lead_time_weeks=2)
        ])
        assert recs[0].priority == Priority.LOW

    def test_low_with_zero_sales_velocity(self):
        recs = calculate_reorder_recommendations([
            _item(current_stock=50, avg_weekly_sales=0, lead_time_weeks=2)
        ])
        assert recs[0].priority == Priority.LOW

    def test_low_order_qty_is_zero(self):
        recs = calculate_reorder_recommendations([
            _item(current_stock=200, avg_weekly_sales=10, lead_time_weeks=2)
        ])
        assert recs[0].recommended_order_qty == 0


# ---------------------------------------------------------------------------
# Order quantity calculation
# ---------------------------------------------------------------------------

class TestOrderQuantity:
    def test_order_qty_covers_lead_time_plus_buffer(self):
        # target = 10 * (2 + 4) = 60; current = 10 → order = 50
        recs = calculate_reorder_recommendations([
            _item(current_stock=10, avg_weekly_sales=10, lead_time_weeks=2)
        ], target_weeks_buffer=4)
        assert recs[0].recommended_order_qty == 50

    def test_order_qty_is_ceiling(self):
        # target = 7 * (2 + 4) = 42; current = 5 → raw order = 37; ceil(37) = 37
        recs = calculate_reorder_recommendations([
            _item(current_stock=5, avg_weekly_sales=7, lead_time_weeks=2)
        ], target_weeks_buffer=4)
        assert recs[0].recommended_order_qty == 37

    def test_order_qty_fractional_rounds_up(self):
        # target = 3 * (1 + 4) = 15; current = 7 → order = 8
        recs = calculate_reorder_recommendations([
            _item(current_stock=7, avg_weekly_sales=3, lead_time_weeks=1)
        ], target_weeks_buffer=4)
        assert recs[0].recommended_order_qty == 8

    def test_order_qty_zero_when_stock_exceeds_target(self):
        # target = 10 * (2 + 4) = 60; current = 100 → max(0, -40) = 0
        recs = calculate_reorder_recommendations([
            _item(current_stock=100, avg_weekly_sales=10, lead_time_weeks=2)
        ], target_weeks_buffer=4)
        assert recs[0].recommended_order_qty == 0

    def test_zero_sales_velocity_gives_zero_order(self):
        recs = calculate_reorder_recommendations([
            _item(current_stock=50, avg_weekly_sales=0, lead_time_weeks=2)
        ])
        assert recs[0].recommended_order_qty == 0


# ---------------------------------------------------------------------------
# Sorting / ordering
# ---------------------------------------------------------------------------

class TestSorting:
    def test_critical_before_high_before_medium_before_low(self):
        items = [
            _item(sku="LOW",      current_stock=200, avg_weekly_sales=5,  lead_time_weeks=2),
            _item(sku="CRITICAL", current_stock=5,   avg_weekly_sales=10, lead_time_weeks=3),
            _item(sku="HIGH",     current_stock=30,  avg_weekly_sales=10, lead_time_weeks=2),
            _item(sku="MEDIUM",   current_stock=55,  avg_weekly_sales=10, lead_time_weeks=2),
        ]
        recs = calculate_reorder_recommendations(items, safety_weeks=2)
        priorities = [r.priority for r in recs]
        assert priorities[0] == Priority.CRITICAL
        # HIGH must come before MEDIUM and LOW
        high_idx = priorities.index(Priority.HIGH)
        medium_idx = priorities.index(Priority.MEDIUM)
        low_idx = priorities.index(Priority.LOW)
        assert high_idx < medium_idx < low_idx

    def test_within_priority_sorted_by_weeks_of_stock_ascending(self):
        items = [
            _item(sku="A", current_stock=6,  avg_weekly_sales=10, lead_time_weeks=3),  # 0.6w
            _item(sku="B", current_stock=15, avg_weekly_sales=10, lead_time_weeks=3),  # 1.5w
            _item(sku="C", current_stock=1,  avg_weekly_sales=10, lead_time_weeks=3),  # 0.1w
        ]
        recs = calculate_reorder_recommendations(items)
        critical = [r for r in recs if r.priority == Priority.CRITICAL]
        assert [r.sku for r in critical] == ["C", "A", "B"]

    def test_empty_input_returns_empty_list(self):
        assert calculate_reorder_recommendations([]) == []


# ---------------------------------------------------------------------------
# Weeks of stock metric
# ---------------------------------------------------------------------------

class TestWeeksOfStock:
    def test_weeks_of_stock_calculated_correctly(self):
        recs = calculate_reorder_recommendations([
            _item(current_stock=30, avg_weekly_sales=6, lead_time_weeks=2)
        ])
        assert recs[0].weeks_of_stock == pytest.approx(5.0)

    def test_weeks_of_stock_infinite_when_no_sales(self):
        recs = calculate_reorder_recommendations([
            _item(current_stock=50, avg_weekly_sales=0, lead_time_weeks=2)
        ])
        assert recs[0].weeks_of_stock == math.inf


# ---------------------------------------------------------------------------
# Reorder point metric
# ---------------------------------------------------------------------------

class TestReorderPoint:
    def test_reorder_point_formula(self):
        # avg_weekly * (lead + safety) = 10 * (3 + 2) = 50
        recs = calculate_reorder_recommendations([
            _item(current_stock=200, avg_weekly_sales=10, lead_time_weeks=3)
        ], safety_weeks=2)
        assert recs[0].reorder_point == pytest.approx(50.0)

    def test_reorder_point_zero_when_no_sales(self):
        recs = calculate_reorder_recommendations([
            _item(current_stock=50, avg_weekly_sales=0, lead_time_weeks=2)
        ])
        assert recs[0].reorder_point == 0.0


# ---------------------------------------------------------------------------
# Input flexibility (dict vs InventoryItem)
# ---------------------------------------------------------------------------

class TestInputTypes:
    def test_accepts_inventory_item_objects(self):
        item = InventoryItem(
            sku="SKU001", store="S1", current_stock=5,
            avg_weekly_sales=10, lead_time_weeks=3
        )
        recs = calculate_reorder_recommendations([item])
        assert len(recs) == 1
        assert recs[0].sku == "SKU001"

    def test_accepts_mixed_dicts_and_objects(self):
        item_obj = InventoryItem(
            sku="OBJ", store="S1", current_stock=5,
            avg_weekly_sales=10, lead_time_weeks=3
        )
        item_dict = _item(sku="DICT")
        recs = calculate_reorder_recommendations([item_obj, item_dict])
        skus = {r.sku for r in recs}
        assert {"OBJ", "DICT"} == skus


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------

class TestGetSummary:
    def test_summary_counts_by_priority(self):
        items = [
            _item(sku="C1", current_stock=5,   avg_weekly_sales=10, lead_time_weeks=3),
            _item(sku="C2", current_stock=0,   avg_weekly_sales=10, lead_time_weeks=2),
            _item(sku="L1", current_stock=200, avg_weekly_sales=5,  lead_time_weeks=2),
        ]
        recs = calculate_reorder_recommendations(items)
        summary = get_summary(recs)
        assert summary["CRITICAL"] == 2
        assert summary["LOW"] == 1
        assert summary["HIGH"] == 0
        assert summary["MEDIUM"] == 0

    def test_summary_total_units(self):
        items = [
            # CRITICAL: target = 10*(3+4)=70; current=5 → order=65
            _item(sku="C1", current_stock=5, avg_weekly_sales=10, lead_time_weeks=3),
            # LOW: order=0
            _item(sku="L1", current_stock=200, avg_weekly_sales=5, lead_time_weeks=2),
        ]
        recs = calculate_reorder_recommendations(items, target_weeks_buffer=4)
        summary = get_summary(recs)
        assert summary["total_recommended_units"] == 65

    def test_empty_summary(self):
        summary = get_summary([])
        for p in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            assert summary[p] == 0
        assert summary["total_recommended_units"] == 0


# ---------------------------------------------------------------------------
# Multi-store scenario
# ---------------------------------------------------------------------------

class TestMultiStore:
    def test_same_sku_different_stores_are_independent(self):
        items = [
            _item(sku="SKU001", store="Store-A", current_stock=5,   avg_weekly_sales=10, lead_time_weeks=3),
            _item(sku="SKU001", store="Store-B", current_stock=200, avg_weekly_sales=10, lead_time_weeks=3),
        ]
        recs = calculate_reorder_recommendations(items)
        store_priorities = {r.store: r.priority for r in recs}
        assert store_priorities["Store-A"] == Priority.CRITICAL
        assert store_priorities["Store-B"] == Priority.LOW

    def test_all_stores_represented_in_output(self):
        stores = [f"Store-{i:02d}" for i in range(10)]
        items = [_item(sku="SKU001", store=s) for s in stores]
        recs = calculate_reorder_recommendations(items)
        assert {r.store for r in recs} == set(stores)
