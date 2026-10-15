"""Prod and stage log wafer_space.* INFO and up, and email only errors (#434).

From 15 Jul 2026 the wafer_space logger was at ERROR in prod and stage. A
logger's level is checked before its records propagate, so every INFO and
WARNING record from wafer_space.* was dropped: production's worker log had
no "Queued do_analyzing" line after 16 Jul, which made check 809's duplicate
(#426) hard to trace. These tests apply the deployed LOGGING and check where
each level goes.
"""

from __future__ import annotations

import ast
import io
import logging
import logging.config
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.utils.log import configure_logging

from config.settings.base import deployed_logging

if TYPE_CHECKING:
    from collections.abc import Iterator

SETTINGS_DIR = Path(__file__).resolve().parents[1] / "settings"


@contextmanager
def deployed_logging_applied() -> Iterator[io.StringIO]:
    """Apply the deployed LOGGING; yield what its console handler writes.

    On the way out the test LOGGING comes back. It names only root, and
    dictConfig leaves loggers it doesn't name as they are, so the loggers
    the deployed LOGGING set are reset too: otherwise wafer_space would keep
    mailing ADMINS in every later test.
    """
    cache.clear()  # RateLimitedAdminEmailHandler's keys
    logging.config.dictConfig(deployed_logging())
    stream = io.StringIO()
    handlers = [h for h in logging.getLogger().handlers if h.name == "console"]
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    handler.setStream(stream)
    try:
        yield stream
    finally:
        configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)
        for name in deployed_logging()["loggers"]:
            named = logging.getLogger(name)
            named.handlers.clear()
            named.setLevel(logging.NOTSET)
            named.propagate = True
        cache.clear()


@pytest.fixture
def console() -> Iterator[io.StringIO]:
    with deployed_logging_applied() as stream:
        yield stream


def test_the_test_logging_comes_back_afterwards() -> None:
    """No later test inherits the deployed loggers or their ADMINS email."""
    with deployed_logging_applied():
        pass

    app_logger = logging.getLogger("wafer_space")
    assert (app_logger.handlers, app_logger.level) == ([], logging.NOTSET)


@pytest.mark.parametrize("level", [logging.INFO, logging.WARNING, logging.ERROR])
def test_an_app_record_reaches_the_console(console: io.StringIO, level: int) -> None:
    """The console is the web log and, in a worker, the Celery worker log."""
    logging.getLogger("wafer_space.projects.tasks_checks").log(
        level, "Queued do_analyzing for check %s", 809
    )

    assert "Queued do_analyzing for check 809" in console.getvalue()


@pytest.mark.parametrize("level", [logging.INFO, logging.WARNING])
def test_below_error_emails_no_one(console: io.StringIO, level: int) -> None:
    logging.getLogger("wafer_space.projects.tasks_checks").log(level, "routine")

    assert mail.outbox == []


def test_an_error_emails_admins(console: io.StringIO) -> None:
    """#293's alerting stays."""
    logging.getLogger("wafer_space.projects.tasks_revisions").error(
        "Metadata fetch failed for %s", "sha256:abc"
    )

    assert len(mail.outbox) == 1


def test_debug_stays_out(console: io.StringIO) -> None:
    logging.getLogger("wafer_space.projects.tasks_checks").debug("noisy detail")

    assert "noisy detail" not in console.getvalue()


@pytest.mark.parametrize("module", ["prod.py", "stage.py"])
def test_prod_and_stage_use_the_deployed_logging(module: str) -> None:
    """Read from the source: these modules need secrets to import."""
    tree = ast.parse((SETTINGS_DIR / module).read_text())
    assignments = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "LOGGING"
            for target in node.targets
        )
    ]

    assert len(assignments) == 1
    call = assignments[0]
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Name)
    assert call.func.id == "deployed_logging"
