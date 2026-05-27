"""Public error contract for migration-workbench.

Re-exports from ``workbench.exceptions`` are available at package level;
see that module for the full API.
"""

from workbench.exceptions import UserFacingError, command_error

__all__ = [
    "UserFacingError",
    "command_error",
]
