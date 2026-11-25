"""
Structured Application Logger
==============================
Provides a consistent log format across all backend modules.
Replaces the scattered print() calls throughout the codebase.

Usage:
    from app.core.logger import get_logger
    log = get_logger(__name__)
    log.info("ColPali search returned %d results", len(results))

Log levels:
  - DEBUG   : fine-grained, verbose (ColPali internals, cache hits)
  - INFO    : normal operational events (query received, model loaded)
  - WARNING : non-fatal anomalies (no results, image missing from disk)
  - ERROR   : failures that need attention (API key missing, DB error)
"""

from __future__ import annotations

import logging
import sys
from typing import Optional


_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

# Root application logger — all child loggers inherit this handler
_root = logging.getLogger("diadoc")
if not _root.handlers:
    _root.addHandler(_handler)
    _root.setLevel(logging.INFO)
    _root.propagate = False  # don't double-log via root Python logger


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """
    Returns a child logger under the 'diadoc' namespace.

    Args:
        name:  Typically __name__ of the calling module.
        level: Override log level (defaults to INFO inherited from root).

    Example:
        log = get_logger(__name__)
    """
    logger = logging.getLogger(f"diadoc.{name}")
    if level is not None:
        logger.setLevel(level)
    return logger
