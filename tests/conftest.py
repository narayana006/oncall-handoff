from datetime import datetime, timezone
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "shift"
NOW = "2026-03-03T09:00:00Z"


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def examples():
    return EXAMPLES
