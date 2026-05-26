"""User-facing error contract for migration-workbench.

All exceptions that the user must act on carry enough context to fix the
problem without reading source code.
"""

from __future__ import annotations


class UserFacingError(Exception):
    """Base for exceptions that carry enough context for the user to fix
    the problem without reading source code.
    """

    def __init__(
        self,
        message: str,
        *,
        action: str | None = None,
        valid_values: list[str] | None = None,
        check_id: str | None = None,
    ):
        super().__init__(message)
        self.action = action
        self.valid_values = valid_values
        self.check_id = check_id

    def __str__(self) -> str:
        parts = [self.args[0]]
        if self.valid_values:
            parts.append(f"Valid values: {', '.join(self.valid_values)}.")
        if self.action:
            parts.append(f"Action: {self.action}")
        return " ".join(parts)


def command_error(
    message: str,
    *,
    action: str | None = None,
    valid_values: list[str] | None = None,
    check_id: str | None = None,
) -> Exception:
    """Return a Django CommandError with a fully-explained message.

    This helper must be called, not raised, inside management commands so
    that the caller can still ``raise`` the returned value.
    """
    from django.core.management.base import CommandError

    err = UserFacingError(
        message, action=action, valid_values=valid_values, check_id=check_id
    )
    return CommandError(str(err))
