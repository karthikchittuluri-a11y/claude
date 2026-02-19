"""Automated order recommendation engine for Sur La Table stores.

Analyzes current stock levels, sales velocity, and lead times to generate
prioritised reorder recommendations across 100+ retail locations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List


# ---------------------------------------------------------------------------
# Priority tiers
# ---------------------------------------------------------------------------

class Priority(str, Enum):
    CRITICAL = "CRITICAL"  # Stock will run out before replenishment arrives
    HIGH = "HIGH"          # Below reorder point (within safety buffer)
    MEDIUM = "MEDIUM"      # Approaching reorder point
    LOW = "LOW"            # Healthy stock levels — monitor only


_PRIORITY_ORDER = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class InventoryItem:
    """A single SKU/store inventory record."""

    sku: str
    store: str
    current_stock: float
    avg_weekly_sales: float
    lead_time_weeks: float

    def __post_init__(self) -> None:
        if self.avg_weekly_sales < 0:
            raise ValueError(f"avg_weekly_sales must be non-negative (got {self.avg_weekly_sales})")
        if self.lead_time_weeks <= 0:
            raise ValueError(f"lead_time_weeks must be positive (got {self.lead_time_weeks})")
        if self.current_stock < 0:
            raise ValueError(f"current_stock must be non-negative (got {self.current_stock})")


@dataclass
class OrderRecommendation:
    """Reorder recommendation produced for one SKU/store combination."""

    sku: str
    store: str
    current_stock: float
    avg_weekly_sales: float
    lead_time_weeks: float
    weeks_of_stock: float        # How many weeks current stock will last
    reorder_point: float         # Stock level that triggers a reorder
    recommended_order_qty: float # Units to order now
    priority: Priority
    reason: str                  # Human-readable explanation


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

def calculate_reorder_recommendations(
    inventory_items: List[dict | InventoryItem],
    safety_weeks: float = 2.0,
    target_weeks_buffer: float = 4.0,
) -> List[OrderRecommendation]:
    """Generate prioritised reorder recommendations for a list of inventory items.

    Algorithm
    ---------
    * **weeks_of_stock**   = current_stock / avg_weekly_sales
    * **reorder_point**    = avg_weekly_sales × (lead_time_weeks + safety_weeks)
    * **order_qty**        = avg_weekly_sales × (lead_time_weeks + target_weeks_buffer)
                             − current_stock   [clamped to 0 if already above target]

    Priority tiers
    ~~~~~~~~~~~~~~
    CRITICAL  weeks_of_stock < lead_time_weeks          → will stock-out before order arrives
    HIGH      current_stock  ≤ reorder_point             → at or below reorder point
    MEDIUM    current_stock  ≤ reorder_point × 1.5       → approaching reorder point
    LOW       otherwise                                   → healthy; monitor only

    Args:
        inventory_items:   Dicts (keys: sku, store, current_stock, avg_weekly_sales,
                           lead_time_weeks) **or** InventoryItem instances.
        safety_weeks:      Buffer weeks added to lead time when computing the
                           reorder point (default 2).
        target_weeks_buffer: Extra weeks of stock beyond lead time used to size
                           the recommended order quantity (default 4).

    Returns:
        List of OrderRecommendation objects sorted by priority
        (CRITICAL → HIGH → MEDIUM → LOW) then by weeks_of_stock ascending
        (most urgent first within each tier).
    """
    recommendations: List[OrderRecommendation] = []

    for raw in inventory_items:
        # Accept both dicts and InventoryItem instances
        if isinstance(raw, dict):
            item = InventoryItem(**raw)
        else:
            item = raw

        # --- Derived metrics ---
        if item.avg_weekly_sales == 0:
            # No sales velocity → stock effectively infinite; skip ordering
            weeks_of_stock = math.inf
            reorder_point = 0.0
            order_qty = 0.0
            priority = Priority.LOW
            reason = "No sales velocity recorded — no order needed."
        else:
            weeks_of_stock = item.current_stock / item.avg_weekly_sales
            reorder_point = item.avg_weekly_sales * (item.lead_time_weeks + safety_weeks)
            target_stock = item.avg_weekly_sales * (item.lead_time_weeks + target_weeks_buffer)
            order_qty = max(0.0, target_stock - item.current_stock)

            if weeks_of_stock < item.lead_time_weeks:
                priority = Priority.CRITICAL
                reason = (
                    f"Only {weeks_of_stock:.1f}w of stock remaining but lead time is "
                    f"{item.lead_time_weeks}w — stock-out imminent."
                )
            elif item.current_stock <= reorder_point:
                priority = Priority.HIGH
                reason = (
                    f"Stock ({item.current_stock:.0f}) at or below reorder point "
                    f"({reorder_point:.0f}). Order now to maintain safety buffer."
                )
            elif item.current_stock <= reorder_point * 1.5:
                priority = Priority.MEDIUM
                reason = (
                    f"Stock ({item.current_stock:.0f}) approaching reorder point "
                    f"({reorder_point:.0f}). Plan order soon."
                )
            else:
                priority = Priority.LOW
                order_qty = 0.0  # No order required yet
                reason = (
                    f"{weeks_of_stock:.1f}w of stock on hand — healthy level, monitor only."
                )

        recommendations.append(
            OrderRecommendation(
                sku=item.sku,
                store=item.store,
                current_stock=item.current_stock,
                avg_weekly_sales=item.avg_weekly_sales,
                lead_time_weeks=item.lead_time_weeks,
                weeks_of_stock=weeks_of_stock,
                reorder_point=reorder_point,
                recommended_order_qty=math.ceil(order_qty),  # round up to whole units
                priority=priority,
                reason=reason,
            )
        )

    # Sort: priority tier first, then most urgent (fewest weeks of stock) first
    recommendations.sort(
        key=lambda r: (
            _PRIORITY_ORDER[r.priority],
            r.weeks_of_stock if r.weeks_of_stock != math.inf else 1e9,
        )
    )

    return recommendations


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def print_recommendations(recommendations: List[OrderRecommendation]) -> None:
    """Pretty-print a sorted list of order recommendations to stdout."""
    sep = "=" * 72
    print(sep)
    print("  AUTOMATED ORDER RECOMMENDATIONS")
    print(sep)

    current_priority: Priority | None = None
    for rec in recommendations:
        if rec.priority != current_priority:
            current_priority = rec.priority
            print(f"\n[{rec.priority.value}]")
            print("-" * 72)

        weeks_display = f"{rec.weeks_of_stock:.1f}w" if rec.weeks_of_stock != math.inf else "∞"
        order_display = f"{rec.recommended_order_qty} units" if rec.recommended_order_qty > 0 else "—"

        print(
            f"  {rec.sku:<10s}  Store: {rec.store:<12s}"
            f"  Stock: {rec.current_stock:>6.0f}"
            f"  Weeks left: {weeks_display:>6s}"
            f"  Order: {order_display}"
        )
        print(f"    ↳ {rec.reason}")

    print()
    print(sep)

    # Summary counts
    by_priority: dict[Priority, int] = {p: 0 for p in Priority}
    for rec in recommendations:
        by_priority[rec.priority] += 1

    print("  SUMMARY")
    for p in Priority:
        print(f"    {p.value:<10s}: {by_priority[p]:>4d} item(s)")
    print(sep)


def get_summary(recommendations: List[OrderRecommendation]) -> dict:
    """Return a summary dict with counts per priority and total order units."""
    summary: dict = {p.value: 0 for p in Priority}
    total_units = 0
    for rec in recommendations:
        summary[rec.priority.value] += 1
        total_units += rec.recommended_order_qty
    summary["total_recommended_units"] = total_units
    return summary


# ---------------------------------------------------------------------------
# Sample data & demo
# ---------------------------------------------------------------------------

SAMPLE_INVENTORY = [
    # SKU,   Store,       Stock,  Avg weekly sales,  Lead time (weeks)
    {"sku": "SKU001", "store": "Store-NYC-01",  "current_stock": 10,  "avg_weekly_sales": 8,  "lead_time_weeks": 3},
    {"sku": "SKU002", "store": "Store-NYC-01",  "current_stock": 120, "avg_weekly_sales": 5,  "lead_time_weeks": 2},
    {"sku": "SKU003", "store": "Store-LA-07",   "current_stock": 30,  "avg_weekly_sales": 12, "lead_time_weeks": 4},
    {"sku": "SKU004", "store": "Store-CHI-03",  "current_stock": 5,   "avg_weekly_sales": 3,  "lead_time_weeks": 2},
    {"sku": "SKU005", "store": "Store-SF-02",   "current_stock": 200, "avg_weekly_sales": 20, "lead_time_weeks": 3},
    {"sku": "SKU006", "store": "Store-SEA-05",  "current_stock": 0,   "avg_weekly_sales": 7,  "lead_time_weeks": 2},
    {"sku": "SKU007", "store": "Store-NYC-01",  "current_stock": 50,  "avg_weekly_sales": 0,  "lead_time_weeks": 1},
    {"sku": "SKU008", "store": "Store-BOS-04",  "current_stock": 18,  "avg_weekly_sales": 6,  "lead_time_weeks": 2},
]


if __name__ == "__main__":
    recommendations = calculate_reorder_recommendations(SAMPLE_INVENTORY)
    print_recommendations(recommendations)
