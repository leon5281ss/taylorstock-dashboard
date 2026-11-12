from datetime import datetime, time
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
PUBLICATION_CUTOFF = time(15, 30)


def taipei_time(value=None):
    value = value or datetime.now(TAIPEI)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_required")
    return value.astimezone(TAIPEI)
