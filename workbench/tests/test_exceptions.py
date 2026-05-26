from django.core.management.base import CommandError

from workbench.exceptions import UserFacingError, command_error


def test_user_facing_error_str_with_all_fields():
    err = UserFacingError(
        "unknown keys found",
        action="Replace 'include' with 'add' or 'replace'.",
        valid_values=["add", "remove", "replace", "tabs"],
        check_id="PROFILER-OVERRIDE-001",
    )
    text = str(err)
    assert "unknown keys found" in text
    assert "Valid values: add, remove, replace, tabs." in text
    assert "Action: Replace 'include' with 'add' or 'replace'." in text


def test_user_facing_error_str_minimal():
    err = UserFacingError("something went wrong")
    assert str(err) == "something went wrong"


def test_command_error_returns_command_error_instance():
    err = command_error("bad config", check_id="TEST-001")
    assert isinstance(err, CommandError)
    assert "bad config" in str(err)
