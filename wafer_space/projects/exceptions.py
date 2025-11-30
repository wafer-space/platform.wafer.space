"""Exceptions for the projects app."""

from __future__ import annotations


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted.

    Attributes:
        from_status: The current status
        to_status: The attempted new status
        model_name: Name of the model (for error messages)
    """

    def __init__(
        self,
        from_status: str,
        to_status: str,
        model_name: str = "ManufacturabilityCheck",
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.model_name = model_name
        msg = (
            f"Invalid {model_name} state transition: "
            f"cannot transition from {from_status} to {to_status}"
        )
        super().__init__(msg)
