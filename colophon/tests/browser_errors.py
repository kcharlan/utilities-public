"""Bounded synchronous extraction from repository tools/testkit.py."""
from contextlib import contextmanager
from collections.abc import Sequence

def _install_browser_error_listeners(page):
    errors: list[str] = []

    def record_page_error(error) -> None:
        errors.append(str(error))

    def record_console_error(message) -> None:
        if message.type == "error":
            errors.append(message.text)

    listeners = (
        ("pageerror", record_page_error),
        ("console", record_console_error),
    )
    for event_name, listener in listeners:
        page.on(event_name, listener)
    return errors, listeners


def capture_browser_errors(page) -> list[str]:
    """Attach strict console/page error listeners to a Playwright page."""
    errors, _listeners = _install_browser_error_listeners(page)
    return errors


@contextmanager
def guard_browser_errors(page, expected: Sequence[str] = ()):
    """Fail a browser-test context on any unexpected console/page error."""
    errors, listeners = _install_browser_error_listeners(page)

    def detach() -> None:
        for event_name, listener in listeners:
            page.remove_listener(event_name, listener)

    def browser_failure() -> AssertionError | None:
        if errors == list(expected):
            return None
        return AssertionError(
            f"Unexpected browser errors: {errors}; expected: {list(expected)}"
        )

    try:
        yield errors
    except BaseException as body_error:
        detach()
        captured_browser_failure = browser_failure()
        if captured_browser_failure is not None:
            group_type = (
                ExceptionGroup
                if isinstance(body_error, Exception)
                else BaseExceptionGroup
            )
            raise group_type(
                "Guarded browser body and browser error checks both failed",
                [body_error, captured_browser_failure],
            ) from None
        raise
    else:
        detach()
        captured_browser_failure = browser_failure()
        if captured_browser_failure is not None:
            raise captured_browser_failure
