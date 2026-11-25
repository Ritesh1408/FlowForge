"""Application logging setup based on the standard library."""

import logging

_LOGGER_NAME = "flowforge"
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level: str) -> None:
    """Configure the ``flowforge`` logger hierarchy.

    Only the application's own logger is configured (not the root logger) so that
    uvicorn's and pytest's logging setups are left intact. Safe to call repeatedly.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    if not any(getattr(h, "_flowforge", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._flowforge = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
