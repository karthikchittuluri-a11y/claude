"""Tests for data_quality_gate.py
Covers:
  - 3 positive use cases
  - 3 negative use cases
  - 8 edge cases
"""

import unittest
from data_quality_gate import run_quality_gate, QualityReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    sku="SKU001", name="Widget", price=9.99, category="Cutlery", stock=10
):
    """Return a minimally valid product record, overrideable per field."""
    return {"sku": sku, "name": name, "price": price,
            "category": category, "stock": stock}


def _good() -> dict:
    return _make_record()


# ---------------------------------------------------------------------------
# POSITIVE USE CASES
# ---------------------------------------------------------------------------

class TestPositiveUseCases(unittest.TestCase):

    # ── Positive 1 ──────────────────────────────────────────────────────────
    def test_clean_batch_all_approved(self):
        """All records valid → 100 % on every dimension → gate APPROVED."""
        records = [
            _make_record("SKU001", "Chef's Knife",  89.99, "Cutlery",  45),
            _make_record("SKU002", "Mixing Bowl",   34.99, "Bakeware", 12),
            _make_record("SKU003", "Wooden Spoon",   4.99, "Utensils", 30),
        ]
        report = run_quality_gate(records)

        self.assertTrue(report.overall_passed)
        self.assertEqual(report.total_records, 3)
        self.assertEqual(len(report.approved_records), 3)
        self.assertEqual(len(report.rejected_records), 0)
        for dim in report.dimensions.values():
            self.assertAlmostEqual(dim.score, 100.0)
            self.assertTrue(dim.passed)

    # ── Positive 2 ──────────────────────────────────────────────────────────
    def test_partial_batch_gate_approved_good_records_forwarded(self):
        """Majority valid batch: gate APPROVED; only bad records quarantined."""
        records = [
            _make_record("SKU001", "Chef's Knife",  89.99, "Cutlery",  45),  # good
            _make_record("SKU002", "Mixing Bowl",   34.99, "Bakeware", 12),  # good
            _make_record("SKU003", "Cutting Board", 49.99, "Cutlery",  20),  # good
            _make_record("SKU004", "Spatula",       12.99, "Utensils", 30),  # good
            _make_record("SKU005", "Bad Item",      -5.00, "Cutlery",  10),  # invalid price
        ]
        report = run_quality_gate(records)

        # 4/5 pass completeness & consistency; 4/5 pass validity → all dims ≥ 80 %
        self.assertTrue(report.overall_passed)
        self.assertEqual(len(report.approved_records), 4)
        self.assertEqual(len(report.rejected_records), 1)
        self.assertEqual(report.rejected_records[0]["sku"], "SKU005")

    # ── Positive 3 ──────────────────────────────────────────────────────────
    def test_category_valid_values_accepted(self):
        """All approved categories pass validity without issue."""
        from data_quality_gate import VALID_CATEGORIES
        records = [
            _make_record(f"SKU{str(i).zfill(3)}", "Item", 9.99, cat, 5)
            for i, cat in enumerate(sorted(VALID_CATEGORIES), start=1)
        ]
        report = run_quality_gate(records)

        self.assertTrue(report.overall_passed)
        self.assertEqual(len(report.approved_records), len(VALID_CATEGORIES))
        validity_issues = report.dimensions["validity"].issues
        category_issues = [iss for iss in validity_issues if iss.field_name == "category"]
        self.assertEqual(category_issues, [])


# ---------------------------------------------------------------------------
# NEGATIVE USE CASES
# ---------------------------------------------------------------------------

class TestNegativeUseCases(unittest.TestCase):

    # ── Negative 1 ──────────────────────────────────────────────────────────
    def test_negative_and_zero_price_blocked(self):
        """Negative price and zero price both fail validity."""
        records = [
            _make_record("SKU001", "Free Item",  0.00, "Cutlery", 5),   # zero
            _make_record("SKU002", "Refund Item", -9.99, "Cutlery", 5), # negative
        ]
        report = run_quality_gate(records)

        self.assertFalse(report.overall_passed)
        self.assertEqual(len(report.approved_records), 0)
        self.assertEqual(len(report.rejected_records), 2)

        price_issues = [
            i for i in report.dimensions["validity"].issues
            if i.field_name == "price"
        ]
        self.assertEqual(len(price_issues), 2)

    # ── Negative 2 ──────────────────────────────────────────────────────────
    def test_missing_sku_blocked_by_completeness(self):
        """Blank SKU fails completeness; record is quarantined."""
        records = [
            _make_record("",       "Spatula", 12.99, "Utensils", 30),  # no SKU
            _make_record("SKU002", "Ladle",   19.99, "Kitchen",   8),  # good
        ]
        report = run_quality_gate(records)

        sku_issues = [
            i for i in report.dimensions["completeness"].issues
            if i.field_name == "sku"
        ]
        self.assertEqual(len(sku_issues), 1)
        self.assertIn("SKU002", [r["sku"] for r in report.approved_records])
        self.assertNotIn("SKU002", [r["sku"] for r in report.rejected_records])

    # ── Negative 3 ──────────────────────────────────────────────────────────
    def test_null_stock_blocked_by_completeness(self):
        """None stock fails completeness; record is quarantined."""
        records = [
            _make_record("SKU001", "Cutting Board", 49.99, "Cutlery", None),
            _good(),
        ]
        report = run_quality_gate(records)

        stock_issues = [
            i for i in report.dimensions["completeness"].issues
            if i.field_name == "stock"
        ]
        self.assertEqual(len(stock_issues), 1)
        self.assertEqual(len(report.approved_records), 1)
        self.assertEqual(report.approved_records[0]["sku"], "SKU001")


# ---------------------------------------------------------------------------
# EDGE CASES
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    # ── Edge 1 ──────────────────────────────────────────────────────────────
    def test_price_as_string_coerced_and_passes(self):
        """String price '89.99' is coerced by float() and passes validity."""
        records = [_make_record("SKU001", "Widget", "89.99", "Cutlery", 5)]
        report = run_quality_gate(records)

        price_issues = [
            i for i in report.dimensions["validity"].issues
            if i.field_name == "price"
        ]
        self.assertEqual(price_issues, [], "String price should coerce and pass validity")
        self.assertEqual(len(report.approved_records), 1)

    # ── Edge 2 ──────────────────────────────────────────────────────────────
    def test_zero_stock_is_valid(self):
        """stock=0 is intentionally valid (out-of-stock item, not an error)."""
        records = [_make_record("SKU001", "Widget", 9.99, "Cutlery", 0)]
        report = run_quality_gate(records)

        stock_issues = [
            i for i in report.dimensions["validity"].issues
            if i.field_name == "stock"
        ]
        self.assertEqual(stock_issues, [])
        self.assertEqual(len(report.approved_records), 1)

    # ── Edge 3 ──────────────────────────────────────────────────────────────
    def test_float_stock_truncated_silently(self):
        """stock=0.5 → int(0.5)=0, passes validity (documents silent truncation)."""
        records = [_make_record("SKU001", "Widget", 9.99, "Cutlery", 0.5)]
        report = run_quality_gate(records)

        # Documents current behaviour: no error raised, record is approved
        stock_issues = [
            i for i in report.dimensions["validity"].issues
            if i.field_name == "stock"
        ]
        self.assertEqual(stock_issues, [], "Float stock is silently truncated — document this behaviour")

    # ── Edge 4 ──────────────────────────────────────────────────────────────
    def test_price_more_than_two_decimal_places_blocked(self):
        """price=0.001 (3 dp) fails consistency."""
        records = [_make_record("SKU001", "Widget", 0.001, "Cutlery", 5)]
        report = run_quality_gate(records)

        dp_issues = [
            i for i in report.dimensions["consistency"].issues
            if i.field_name == "price"
        ]
        self.assertEqual(len(dp_issues), 1)
        self.assertIn("decimal", dp_issues[0].description.lower())

    # ── Edge 5 ──────────────────────────────────────────────────────────────
    def test_empty_batch_raises_value_error(self):
        """Empty record list must raise ValueError immediately."""
        with self.assertRaises(ValueError):
            run_quality_gate([])

    # ── Edge 6 ──────────────────────────────────────────────────────────────
    def test_all_records_rejected_approved_list_empty(self):
        """Gate returns an empty approved list when every record fails."""
        records = [
            _make_record("",       "Item A", -1.00, "Cutlery", None),
            _make_record("",       "Item B", -2.00, "Cutlery", None),
        ]
        report = run_quality_gate(records)

        self.assertFalse(report.overall_passed)
        self.assertEqual(report.approved_records, [])
        self.assertEqual(len(report.rejected_records), 2)

    # ── Edge 7 ──────────────────────────────────────────────────────────────
    def test_duplicate_skus_evaluated_independently(self):
        """Two records with the same SKU are each evaluated on their own merits."""
        records = [
            _make_record("SKU001", "Good Widget", 9.99,  "Cutlery", 10),  # passes
            _make_record("SKU001", "Bad Widget",  -1.00, "Cutlery", 10),  # fails validity
        ]
        report = run_quality_gate(records)

        approved_skus = [r["sku"] for r in report.approved_records]
        rejected_skus = [r["sku"] for r in report.rejected_records]

        # Both share the same SKU string — one approved, one rejected
        self.assertEqual(len(report.approved_records), 1)
        self.assertEqual(len(report.rejected_records), 1)
        self.assertEqual(approved_skus, ["SKU001"])
        self.assertEqual(rejected_skus, ["SKU001"])

    # ── Edge 8 ──────────────────────────────────────────────────────────────
    def test_none_price_caught_by_completeness_not_validity(self):
        """price=None fails completeness first; validity skips None gracefully."""
        records = [_make_record("SKU001", "Widget", None, "Cutlery", 5)]
        report = run_quality_gate(records)

        completeness_price_issues = [
            i for i in report.dimensions["completeness"].issues
            if i.field_name == "price"
        ]
        validity_price_issues = [
            i for i in report.dimensions["validity"].issues
            if i.field_name == "price"
        ]

        self.assertEqual(len(completeness_price_issues), 1)
        self.assertEqual(validity_price_issues, [], "Validity must skip None price — completeness owns that check")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
