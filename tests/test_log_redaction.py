"""SecretRedactingFilter must mask secrets without breaking uvicorn's access formatter."""

import logging

from uvicorn.logging import AccessFormatter

from app.config import SecretRedactingFilter

SECRET = "sk-test-supersecret-1234567890"


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", path, "1.1", 200), None,
    )


def test_access_log_formats_and_masks_secret_in_args() -> None:
    record = _access_record(f"/api/x?key={SECRET}")
    flt = SecretRedactingFilter(secret=SECRET)
    assert flt.filter(record) is True
    assert isinstance(record.args, tuple) and len(record.args) == 5
    out = AccessFormatter("%(client_addr)s - %(request_line)s %(status_code)s").format(record)
    assert SECRET not in out
    assert "200" in out


def test_plain_record_still_masked() -> None:
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "token %s", (SECRET,), None)
    SecretRedactingFilter(secret=SECRET).filter(record)
    assert SECRET not in record.getMessage()
