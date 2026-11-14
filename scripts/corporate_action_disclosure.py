"""Compare separately sourced company-action disclosures for research."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re

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


TAIPEI = timezone(timedelta(hours=8), "Asia/Taipei")
# Vet each original document before extending this registry. Exact URL matching
# rejects lookalike hosts, redirects encoded in parameters and generic portals.
DOCUMENTS = {
    ("issuer", "TWSE", "2330", "3287"): "https://pr.tsmc.com/english/news/3287",
    ("exchange", "TWSE", "2330", "8a8216d69e6379f4019eb0d03b0101de"):
        "https://wwwc.twse.com.tw/staticFiles/news/news/tsecnews/"
        "8a8216d69e6379f4019eb0d03b0101de.pdf",
}


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("ISO date required")
    return date.fromisoformat(value)


def release_time(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})",
        value,
    ):
        raise ValueError("time and timezone required")
    return datetime.fromisoformat(value).astimezone(TAIPEI)


def document_evidence(record, role, cutoff, effective, issues):
    values = [record.get(k) for k in ("market", "code", "documentId")]
    url = DOCUMENTS.get((role, *values)) if all(isinstance(v, str) for v in values) else None
    if url is None or record.get("source") != url:
        issues.append(role + "_untrusted_document")
    stamp = None
    try:
        stamp = release_time(record.get("announcedAt"))
        if cutoff is not None and stamp > cutoff:
            issues.append(role + "_announcement_after_evaluation")
        if effective and stamp.date() > effective:
            issues.append(role + "_announcement_after_effective_date")
    except ValueError:
        issues.append(role + "_announcement_time_unverified")
    revisions = record.get("revisions")
    version = record.get("version")
    try:
        if not isinstance(revisions, list) or not revisions or type(version) is not int:
            raise ValueError
        times = []
        for number, revision in enumerate(revisions, 1):
            if (not isinstance(revision, dict) or type(revision.get("version")) is not int
                    or revision["version"] != number or revision.get("source") != url
                    or url is None):
                raise ValueError
            times.append(release_time(revision.get("publishedAt")))
        if (version != len(times) or times[-1] != stamp
                or any(a >= b for a, b in zip(times, times[1:]))):
            raise ValueError
    except ValueError:
        issues.append(role + "_revision_history_unverified")
    return {"documentId": record.get("documentId"), "source": record.get("source"),
            "publicationTimeTaipei": stamp.isoformat() if stamp else None,
            "version": version, "revisions": revisions}


def entitlement(field, value, kind):
    if field.endswith("Date"):
        return iso_date(value)
    if field == "reductionReason":
        if not isinstance(value, str) or not value.strip():
            raise ValueError
        return value
    if (not isinstance(value, str)
            or not re.fullmatch(r"[0-9]+(?:[.][0-9]+)?", value)):
        raise ValueError
    number = Decimal(value)
    if field == "cashReturnedPerOldShareTwd":
        return number
    if number == 0:
        raise ValueError
    if field == "newSharesPerOldShare":
        if kind == "split" and number <= 1:
            raise ValueError
        if kind in ("reverseSplit", "capitalReduction") and number >= 1:
            raise ValueError
    return number


def compare(issuer, exchange, *, evaluated_at):
    """Compare publication evidence and entitlement terms without pricing."""
    issues = []
    if not isinstance(issuer, dict) or not isinstance(exchange, dict):
        issues.append("invalid_document_record")
        issuer, exchange = {}, {}
    kind = issuer.get("kind")
    required = TERMS.get(kind, ()) if isinstance(kind, str) else ()
    if not required:
        issues.append("unsupported_event_type")
    for field in ("market", "code", "kind", "exDate", "effectiveDate"):
        a, b = issuer.get(field), exchange.get(field)
        if a is None or b is None:
            issues.append("missing_" + field)
        elif not isinstance(a, str) or not isinstance(b, str):
            issues.append("invalid_" + field)
        elif a != b:
            issues.append("mismatch_" + field)
    effective = None
    try:
        effective = iso_date(issuer.get("effectiveDate"))
        if iso_date(issuer.get("exDate")) > effective:
            issues.append("invalid_effective_date_order")
    except ValueError:
        issues.append("invalid_event_dates")
    cutoff = None
    if isinstance(evaluated_at, datetime) and evaluated_at.utcoffset() is not None:
        cutoff = evaluated_at.astimezone(TAIPEI)
    else:
        issues.append("evaluation_time_unverified")
    docs = {role: document_evidence(record, role, cutoff, effective, issues)
            for role, record in (("issuer", issuer), ("exchange", exchange))}
    left, right = issuer.get("terms"), exchange.get("terms")
    if not isinstance(left, dict) or not isinstance(right, dict):
        issues.append("invalid_entitlement_record")
        left, right = {}, {}
    for field in required:
        a, b = left.get(field), right.get(field)
        if a is None or b is None:
            issues.append("missing_" + field)
            continue
        try:
            if entitlement(field, a, kind) != entitlement(field, b, kind):
                issues.append("mismatch_" + field)
        except (InvalidOperation, ValueError):
            issues.append("invalid_" + field)
    # Structural checks do not independently certify timestamp or revision
    # claims. A verified evidence ingestion step is needed before pricing.
    return {"status": "blocked" if issues else "matched_inputs_pending_source_review",
            "issues": issues, "documents": docs,
            "announcementAvailableAt": None,
            "effectiveDate": effective.isoformat() if effective else None,
            "candidateAdjustmentFactor": None, "adjustedPriceReturn": None,
            "reinvestedTotalReturn": None, "top10": None, "publishable": False}
