"""
AegisOps Unified Structured Logging
All modules should call: from aegisops_logging import get_logger
Logger name should be __name__.
"""
import logging
import os
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Returns a logger configured with structured output.
    In production (AEGISOPS_ENV=production) uses JSON format.
    In dev mode uses human-readable format.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    env = os.getenv("AEGISOPS_ENV", "dev")
    level = logging.DEBUG if env == "dev" else logging.INFO
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if env == "production":
        try:
            from pythonjsonlogger import jsonlogger
            formatter = jsonlogger.JsonFormatter(
                fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S"
            )
        except ImportError:
            formatter = logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S"
            )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S"
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
