"""Opt-in, bounded internal diagnostics for one desktop input request."""

import json
import logging
import os


_LOGGER = logging.getLogger("cognitive_world.player.input_diagnostics")
_SETTING = "COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS"


def enabled() -> bool:
    try:
        return os.environ.get(_SETTING) == "1"
    except Exception:
        return False


def emit(request_id: str, stage: str, **fields: object) -> None:
    """Write caller-selected safe fields; diagnostics must never affect execution."""
    if not enabled():
        return
    try:
        record = {"schema": "desktop-input-diagnostic/v1", "request_id": request_id,
                  "stage": stage, **fields}
        _LOGGER.warning("CW_INPUT_DIAGNOSTIC %s", json.dumps(record, ensure_ascii=False))
    except Exception:
        pass
