"""Unit tests for logging and secret redaction."""
from __future__ import annotations

import logging
from pathlib import Path

from app.utils.formatting import format_currency, format_token_amount, shorten_address
from app.utils.logging import RedactionFilter, setup_logging


def test_redaction_filter():
    f = RedactionFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='key=value, ETHERSCAN_API_KEY=deadbeef12345, "secret": "shhh", token=tok987',
        args=(),
        exc_info=None,
    )
    res = f.filter(record)
    assert res is True
    assert "deadbeef12345" not in record.msg
    assert "shhh" not in record.msg
    assert "tok987" not in record.msg
    assert "[REDACTED]" in record.msg


def test_setup_logging_creates_file_and_logs(tmp_path: Path):
    log_dir = tmp_path / "custom_logs"
    setup_logging(log_dir=log_dir, level="DEBUG")

    logger = logging.getLogger("wit.test")
    logger.info("Normal log line")
    logger.warning("BLOCKSCOUT_API_KEY=secret_key_12345")
    logging.shutdown()

    log_file = log_dir / "app.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Normal log line" in content
    assert "secret_key_12345" not in content
    assert "[REDACTED]" in content


def test_formatting_helpers():
    assert shorten_address("0x1234567890123456789012345678901234567890") == "0x1234...7890"
    assert shorten_address("short") == "short"
    assert format_currency(1234.56) == "$1,234.56"
    assert format_token_amount(1234567890000000000, decimals=18) == "1.2346"
