"""Smoke test: every Streamlit page runs without an exception against the built warehouse."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from pulseiq import config

APP = Path(__file__).resolve().parent.parent / "app"
PAGES = [APP / "Home.py", *sorted((APP / "pages").glob("*.py"))]


@pytest.mark.skipif(not config.WAREHOUSE.exists(), reason="warehouse not built")
@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_page_runs(page):
    at = AppTest.from_file(str(page), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
