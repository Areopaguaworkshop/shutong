"""Shared error utilities for Shutong MCP tools.

Per v4 spec §17 invariant #4: every tool error returns
{status: "error", error_code, message, next_action}.
"""


class ShutongError(Exception):
    """Structured error that carries error_code and next_action."""

    def __init__(self, error_code: str, message: str, next_action: str = ""):
        self.error_code = error_code
        self.message = message
        self.next_action = next_action
        super().__init__(message)


def error_response(error_code: str, message: str, next_action: str = "") -> dict:
    """Structured error response per v4 spec §17 invariant #4."""
    return {
        "status": "error",
        "error_code": error_code,
        "message": message,
        "next_action": next_action,
    }