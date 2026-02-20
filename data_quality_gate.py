"""Genesis DMP — Retail Data Quality Gate
=========================================
Validates retail product records before they are forwarded to the
data warehouse.  Three dimensions are measured:

  • Completeness  – all required fields are populated
  • Validity      – values satisfy business rules (positive price, etc.)
  • Consistency   – values match expected formats / patterns (SKU regex, etc.)

Each dimension has a configurable floor (minimum acceptable %) and ceiling
(maximum acceptable %).  The overall upload is APPROVED only when every
dimension score falls within [floor, ceiling].
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Sample upload
# ---------------------------------------------------------------------------
uploaded_data = [
    {"sku": "SKU001", "name": "Chef's Knife",  "price":  89.99, "category": "Cutlery",  "stock": 45},
    {"sku": "SKU002", "name": "",              "price":  34.99, "category": "Kitchen",  "stock": 12},
    {"sku": "SKU003", "name": "Mixing Bowl",   "price": -10.00, "category": "Bakeware", "stock":  8},
    {"sku": "",       "name": "Spatula",        "price":  12.99, "category": "Utensils", "stock": 30},
    {"sku": "SKU005", "name": "Cutting Board", "price":  49.99, "category": "Cutlery",  "stock": None},
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = ["sku", "name", "price", "category", "stock"]

# Floors: minimum acceptable score to pass.
# Ceilings: maximum acceptable score (catches suspiciously "perfect" batches
#   that may indicate upstream filter bugs or synthetic/test data leaking in).
THRESHOLDS: dict[str, dict[str, float]] = {
    "completeness": {"floor": 80.0, "ceiling": 100.0},
    "validity":     {"floor": 80.0, "ceiling": 100.0},
    "consistency":  {"floor": 90.0, "ceiling": 100.0},
}

VALID_CATEGORIES = {"Bakeware", "Cookware", "Cutlery", "Kitchen", "Storage", "Utensils"}
SKU_PATTERN = re.compile(r"^SKU\d{3,}$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class RecordIssue:
    record_index: int   # 0-based position in the submitted batch
    sku: str            # resolved SKU (or '(missing)')
    dimension: str      # 'completeness' | 'validity' | 'consistency'
    field_name: str
    description: str
    suggestion: str


@dataclass
class DimensionResult:
    name: str
    score: float        # percentage 0–100
    floor: float
    ceiling: float
    passed: bool
    issues: list[RecordIssue] = field(default_factory=list)


@dataclass
class QualityReport:
    total_records: int
    approved_records: list[dict]
    rejected_records: list[dict]
    dimensions: dict[str, DimensionResult]
    overall_passed: bool


# ---------------------------------------------------------------------------
# Individual dimension checks
# ---------------------------------------------------------------------------

def _check_completeness(records: list[dict]) -> tuple[list[int], list[RecordIssue]]:
    """Flag any record missing or empty required fields."""
    passing: set[int] = set(range(len(records)))
    issues: list[RecordIssue] = []

    for i, rec in enumerate(records):
        for fname in REQUIRED_FIELDS:
            value = rec.get(fname)
            if value is None or (isinstance(value, str) and not value.strip()):
                passing.discard(i)
                issues.append(RecordIssue(
                    record_index=i,
                    sku=rec.get("sku") or "(missing)",
                    dimension="completeness",
                    field_name=fname,
                    description=f"Required field '{fname}' is missing or blank.",
                    suggestion=f"Populate '{fname}' before re-uploading this record.",
                ))

    return sorted(passing), issues


def _check_validity(records: list[dict]) -> tuple[list[int], list[RecordIssue]]:
    """Flag records whose values violate business rules."""
    passing: set[int] = set(range(len(records)))
    issues: list[RecordIssue] = []

    for i, rec in enumerate(records):
        sku_label = rec.get("sku") or "(missing)"

        # --- Price: must be a positive number ---
        price = rec.get("price")
        if price is not None:
            try:
                if float(price) <= 0:
                    passing.discard(i)
                    issues.append(RecordIssue(
                        record_index=i, sku=sku_label,
                        dimension="validity", field_name="price",
                        description=f"Price {price!r} is not positive.",
                        suggestion="Set price to a value greater than 0.00.",
                    ))
            except (TypeError, ValueError):
                passing.discard(i)
                issues.append(RecordIssue(
                    record_index=i, sku=sku_label,
                    dimension="validity", field_name="price",
                    description=f"Price {price!r} is not a valid number.",
                    suggestion="Provide a numeric price value (e.g. 12.99).",
                ))

        # --- Stock: must be a non-negative integer ---
        stock = rec.get("stock")
        if stock is not None:
            try:
                if int(stock) < 0:
                    passing.discard(i)
                    issues.append(RecordIssue(
                        record_index=i, sku=sku_label,
                        dimension="validity", field_name="stock",
                        description=f"Stock {stock!r} is negative.",
                        suggestion="Set stock to 0 or a positive integer.",
                    ))
            except (TypeError, ValueError):
                passing.discard(i)
                issues.append(RecordIssue(
                    record_index=i, sku=sku_label,
                    dimension="validity", field_name="stock",
                    description=f"Stock {stock!r} is not a valid integer.",
                    suggestion="Provide an integer stock value (e.g. 10).",
                ))

        # --- Category: must be from the approved set ---
        category = rec.get("category")
        if category and category not in VALID_CATEGORIES:
            passing.discard(i)
            issues.append(RecordIssue(
                record_index=i, sku=sku_label,
                dimension="validity", field_name="category",
                description=f"Category {category!r} is not in the approved list.",
                suggestion=f"Use one of: {', '.join(sorted(VALID_CATEGORIES))}.",
            ))

    return sorted(passing), issues


def _check_consistency(records: list[dict]) -> tuple[list[int], list[RecordIssue]]:
    """Flag records whose values don't conform to expected formats."""
    passing: set[int] = set(range(len(records)))
    issues: list[RecordIssue] = []

    for i, rec in enumerate(records):
        sku_label = rec.get("sku") or "(missing)"

        # --- SKU: must match SKUnnn (3+ digits) if present ---
        sku = rec.get("sku", "")
        if sku and not SKU_PATTERN.match(sku):
            passing.discard(i)
            issues.append(RecordIssue(
                record_index=i, sku=sku_label,
                dimension="consistency", field_name="sku",
                description=f"SKU {sku!r} does not match format 'SKUnnn'.",
                suggestion="Reformat SKU as 'SKU' followed by 3+ digits (e.g. 'SKU001').",
            ))

        # --- Price: at most 2 decimal places (currency format) ---
        price = rec.get("price")
        if price is not None:
            try:
                price_str = f"{float(price):.10f}".rstrip("0")
                decimal_places = (
                    len(price_str.split(".")[-1]) if "." in price_str else 0
                )
                if decimal_places > 2:
                    passing.discard(i)
                    issues.append(RecordIssue(
                        record_index=i, sku=sku_label,
                        dimension="consistency", field_name="price",
                        description=(
                            f"Price {price!r} has {decimal_places} decimal places; "
                            "currency values must have at most 2."
                        ),
                        suggestion="Round price to 2 decimal places (e.g. 12.999 → 13.00).",
                    ))
            except (TypeError, ValueError):
                pass  # already caught by validity check


    return sorted(passing), issues


# ---------------------------------------------------------------------------
# Quality gate runner
# ---------------------------------------------------------------------------

def run_quality_gate(
    records: list[dict],
    thresholds: dict[str, dict[str, float]] | None = None,
) -> QualityReport:
    """Run all quality checks against *records* and return a QualityReport.

    Args:
        records:    List of product dicts to validate.
        thresholds: Optional override for floor/ceiling per dimension.
                    Defaults to the module-level THRESHOLDS constant.

    Returns:
        A QualityReport containing per-dimension results, approved /
        rejected record lists, and an overall pass/fail verdict.
    """
    thresholds = thresholds or THRESHOLDS
    n = len(records)
    if n == 0:
        raise ValueError("No records to evaluate.")

    completeness_passing, completeness_issues = _check_completeness(records)
    validity_passing,     validity_issues     = _check_validity(records)
    consistency_passing,  consistency_issues  = _check_consistency(records)

    def _make_dim(name: str, passing_indices: list[int], dim_issues: list[RecordIssue]) -> DimensionResult:
        score = (len(passing_indices) / n) * 100
        cfg   = thresholds[name]
        passed = cfg["floor"] <= score <= cfg["ceiling"]
        return DimensionResult(
            name=name,
            score=score,
            floor=cfg["floor"],
            ceiling=cfg["ceiling"],
            passed=passed,
            issues=dim_issues,
        )

    dimensions = {
        "completeness": _make_dim("completeness", completeness_passing, completeness_issues),
        "validity":     _make_dim("validity",     validity_passing,     validity_issues),
        "consistency":  _make_dim("consistency",  consistency_passing,  consistency_issues),
    }

    # A record is approved only if it passes ALL three dimensions
    approved_set = (
        set(completeness_passing)
        & set(validity_passing)
        & set(consistency_passing)
    )
    approved = [records[i] for i in sorted(approved_set)]
    rejected = [records[i] for i in range(n) if i not in approved_set]

    overall_passed = all(d.passed for d in dimensions.values())

    return QualityReport(
        total_records=n,
        approved_records=approved,
        rejected_records=rejected,
        dimensions=dimensions,
        overall_passed=overall_passed,
    )


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------

def print_quality_report(report: QualityReport) -> None:
    """Print a human-readable quality report to stdout."""
    BAR  = "=" * 65
    LINE = "-" * 65

    verdict = "APPROVED" if report.overall_passed else "BLOCKED"

    print(BAR)
    print("  GENESIS DMP — RETAIL DATA QUALITY GATE REPORT")
    print(BAR)
    print(f"  Total records submitted : {report.total_records}")
    print(f"  Approved for warehouse  : {len(report.approved_records)}")
    print(f"  Rejected                : {len(report.rejected_records)}")
    print(f"  Overall decision        : {verdict}")
    print(BAR)

    # --- Per-dimension breakdown ---
    for dim in report.dimensions.values():
        status = "PASS" if dim.passed else "FAIL"
        print(
            f"\n  {dim.name.upper():<15s}  "
            f"score={dim.score:5.1f}%  "
            f"floor={dim.floor:.0f}%  "
            f"ceiling={dim.ceiling:.0f}%  "
            f"[{status}]"
        )
        print(LINE)
        if not dim.issues:
            print("    No issues found.")
        else:
            for issue in dim.issues:
                print(f"    Record #{issue.record_index + 1} (SKU: {issue.sku})")
                print(f"      Issue : {issue.description}")
                print(f"      Fix   : {issue.suggestion}")

    # --- Approved records ---
    print()
    print(BAR)
    if report.approved_records:
        print("  APPROVED RECORDS  (forwarded to data warehouse)")
        print(BAR)
        for rec in report.approved_records:
            print(f"    {rec}")
    else:
        print("  APPROVED RECORDS  — none")
        print(BAR)

    # --- Rejected records ---
    print()
    print(BAR)
    if report.rejected_records:
        print("  REJECTED RECORDS  (must be corrected and re-uploaded)")
        print(BAR)
        for rec in report.rejected_records:
            print(f"    {rec}")
    else:
        print("  REJECTED RECORDS  — none")
        print(BAR)

    # --- Final verdict ---
    print()
    if report.overall_passed:
        print("  >> Upload APPROVED. Approved records sent to the data warehouse.")
    else:
        print("  >> Upload BLOCKED. Fix the issues listed above and re-upload.")
    print(BAR)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    report = run_quality_gate(uploaded_data)
    print_quality_report(report)
