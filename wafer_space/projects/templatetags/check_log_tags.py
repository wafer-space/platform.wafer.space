"""Template tags for showing a bounded part of a check's log (issue #308)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import log_tail_expressions
from wafer_space.projects.models import whole_log_lines

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
    tail = log_tail_expressions()
    values = (
        ManufacturabilityCheck.objects.filter(pk=check.pk)
        .values(
            processing_logs_tail=tail["processing_logs_tail"],
            processing_logs_length=tail["processing_logs_length"],
            processing_logs_truncated=tail["processing_logs_truncated"],
        )
        .get()
    )
    truncated = bool(values["processing_logs_truncated"])
    return {
        "processing_logs_tail": whole_log_lines(
            str(values["processing_logs_tail"] or ""), truncated=truncated
        ),
        "processing_logs_length": values["processing_logs_length"],
        "processing_logs_truncated": truncated,
    }
