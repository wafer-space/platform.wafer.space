"""Page Object Models for E2E tests."""

from .base import BasePage
from .file_submit import FileSubmitPage
from .login import LoginPage
from .project_create import ProjectCreatePage
from .project_detail import ProjectDetailPage
from .project_list import ProjectListPage

__all__ = [
    "BasePage",
    "FileSubmitPage",
    "LoginPage",
    "ProjectCreatePage",
    "ProjectDetailPage",
    "ProjectListPage",
]
