"""On GitHub Actions, report each failing test as an error annotation, so failures are readable
from the run summary (and the public checks API) without downloading logs."""
import os

import pytest


@pytest.hookimpl(trylast=True)
def pytest_runtest_logreport(report):
    if not os.environ.get("GITHUB_ACTIONS") or not report.failed:
        return
    text = str(report.longreprtext or "")
    tail = "\n".join(text.splitlines()[-25:])[-3500:]
    message = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"\n::error title={report.nodeid} ({report.when})::{message}")
