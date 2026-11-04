"""Logging configuration with secret redaction for Wallet Intelligence Tracker."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Sensitive key patterns: matches keys like ETHERSCAN_API_KEY, api_key, secret, token, etc.
REDACT_PATTERNS = [
    # KEY=value
    re.compile(
        r"(?i)\b([a-z0-9_]*(?:api[_-]?key|token|secret|password|private[_-]?key|authorization))\s*=\s*([^\s,;'\"]+)"
    ),
    # KEY: value (unquoted)
    re.compile(
        r"(?i)\b([a-z0-9_]*(?:api[_-]?key|token|secret|password|private[_-]?key|authorization))\s*:\s*([^\s,;'\"]+)"
    ),
    # "key": "value" or 'key': 'value' or key: "value"
    re.compile(
        r"""(?i)(["']?[a-z0-9_]*(?:api[_-]?key|token|secret|password|private[_-]?key|authorization)["']?\s*[:=]\s*["'])([^"'\r\n]+)(["'])"""
    ),
    # Bearer tokens
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9_\-\.]{8,})"),
]


def redact_text(text: str) -> str:
    """Mask sensitive values in text with [REDACTED]."""
    if not text:
        return text

    res = text
    # Pattern 1: KEY=value
    res = REDACT_PATTERNS[0].sub(r"\g<1>=[REDACTED]", res)
    # Pattern 2: KEY: value
    res = REDACT_PATTERNS[1].sub(r"\g<1>: [REDACTED]", res)
    # Pattern 3: "key": "value"
    res = REDACT_PATTERNS[2].sub(r"\g<1>[REDACTED]\g<3>", res)
    # Pattern 4: Bearer token
    res = REDACT_PATTERNS[3].sub(r"\g<1>[REDACTED]", res)
    return res


class RedactionFilter(logging.Filter):
    """Logging filter that redacts secrets and credentials from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            # Format message with args first, then redact the complete text
            try:
                formatted = record.getMessage()
                record.msg = redact_text(formatted)
                record.args = None
            except (TypeError, ValueError):
                if isinstance(record.msg, str):
                    record.msg = redact_text(record.msg)
        else:
            if isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
            else:
                record.msg = redact_text(str(record.msg))

        return True


def setup_logging(
    log_dir: str | Path = "logs",
    level: str = "INFO",
    console: bool = False,
) -> logging.Logger:
    """Configure rotating file handler and secret redaction filter."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "app.log"

    num_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(num_level)

    wit_logger = logging.getLogger("wit")
    wit_logger.setLevel(num_level)

    # Clear existing handlers to avoid duplicates on re-init
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    for h in list(wit_logger.handlers):
        wit_logger.removeHandler(h)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redaction_filter = RedactionFilter()

    # File handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(num_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redaction_filter)
    root_logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(num_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(redaction_filter)
        root_logger.addHandler(console_handler)

    return wit_logger
