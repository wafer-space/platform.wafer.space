"""Template tags for showing a bounded part of a check's log (issue #308)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import log_tail_expressions

if TYPE_CHECKING:
    from collections.abc import Mapping

register = template.Library()


@register.simple_tag
def check_log_tail(check: ManufacturabilityCheck) -> Mapping[str, object]:
    """The check's log tail, length and truncation, computed in SQL.

    One small query, whatever query loaded ``check``: the whole log is never
    read into Python. Usage::

        {% check_log_tail check as log %}{{ log.processing_logs_tail }}
    """
    if not check.pk:
        return {
            "processing_logs_tail": "",
            "processing_logs_length": 0,
            "processing_logs_truncated": False,
        }
    return (
        ManufacturabilityCheck.objects.filter(pk=check.pk)
        .values(**log_tail_expressions())
        .get()
    )
