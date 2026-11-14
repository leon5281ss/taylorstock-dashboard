"""Compare separately sourced company-action disclosures for research."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

TERMS = {
    "cashDividend": ("cashPerShareTwd", "recordDate", "paymentDate"),
    "stockDividend": ("newSharesPerOldShare", "recordDate", "distributionDate"),
    "cashRightsIssue": ("subscriptionPriceTwd", "newSharesPerOldShare",
                        "subscriptionStartDate", "subscriptionEndDate"),
    "capitalReduction": ("newSharesPerOldShare", "cashReturnedPerOldShareTwd",
                         "reductionReason"),
    "split": ("newSharesPerOldShare",),
    "reverseSplit": ("newSharesPerOldShare",),
}


def compare(issuer, exchange, *, evaluated_at):
    """Inputs must be transcribed from separate issuer and exchange documents."""
    issues = []
    kind = issuer.get("kind")
    required = TERMS.get(kind, ())
    if not required:
        issues.append("unsupported_event_type")
    for field in ("market", "code", "kind", "exDate", "effectiveDate"):
        a, b = issuer.get(field), exchange.get(field)
        if a is None or b is None:
            issues.append("missing_" + field)
        elif a != b:
            issues.append("mismatch_" + field)
    effective = None
    try:
        effective = date.fromisoformat(issuer.get("effectiveDate"))
        ex_date = date.fromisoformat(issuer.get("exDate"))
        if ex_date > effective:
            issues.append("invalid_effective_date_order")
    except (TypeError, ValueError):
        issues.append("invalid_event_dates")
    sources = (issuer.get("source"), exchange.get("source"))
    if not all(isinstance(url, str) and url.startswith("https://") for url in sources):
        issues.append("missing_source")
    elif sources[0] == sources[1]:
        issues.append("duplicate_source")
    available_at = None
    try:
        available_at = datetime.fromisoformat(issuer.get("announcedAt"))
        if available_at.utcoffset() is None or evaluated_at.utcoffset() is None:
            raise ValueError("time zone required")
        if available_at > evaluated_at:
            issues.append("announcement_after_evaluation")
        if effective and available_at.date() > effective:
            issues.append("announcement_after_effective_date")
    except (TypeError, ValueError):
        available_at = None
        issues.append("announcement_time_unverified")
    for field in required:
        a = issuer.get("terms", {}).get(field)
        b = exchange.get("terms", {}).get(field)
        if a is None or b is None:
            issues.append("missing_" + field)
        elif a != b:
            issues.append("mismatch_" + field)
        elif field.endswith("Date"):
            try:
                date.fromisoformat(a)
            except (ValueError, TypeError):
                issues.append("invalid_" + field)
        elif field != "reductionReason":
            try:
                value = Decimal(str(a))
                if not value.is_finite() or value < 0 or (
                    value == 0 and field != "cashReturnedPerOldShareTwd"
                ):
                    raise ValueError("invalid entitlement")
                if ((kind == "split" and value <= 1)
                        or (kind == "reverseSplit" and value >= 1)):
                    raise ValueError("invalid split ratio")
            except (InvalidOperation, ValueError):
                issues.append("invalid_" + field)
    return {"status": "blocked" if issues else "matched_inputs_pending_source_review",
            "issues": issues,
            "announcementAvailableAt": available_at.isoformat() if available_at else None,
            "effectiveDate": effective.isoformat() if effective else None,
            "candidateAdjustmentFactor": None, "adjustedPriceReturn": None,
            "reinvestedTotalReturn": None, "top10": None, "publishable": False}
