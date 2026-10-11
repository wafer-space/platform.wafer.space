"""Template filters for the projects list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from wafer_space.projects.list_state import list_state

if TYPE_CHECKING:
    from django_stubs_ext import WithAnnotations

    from wafer_space.projects.list_state import ListState
    from wafer_space.projects.list_state import ListStateAnnotations
    from wafer_space.projects.models import Project

register = template.Library()


@register.filter
def project_list_state(
    project: WithAnnotations[Project, ListStateAnnotations],
) -> ListState:
    """The list state of a project from ``annotate_list_state``'s queryset."""
    return list_state(project)
