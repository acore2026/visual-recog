from __future__ import annotations

import time

from .base import BaseClient


class GestureRecognitionClient(BaseClient):
    """
    Gesture recognition client (YOLOv8 placeholder).
    Emits one gesture result every 0.2s as required.
    """

    def __init__(self, emit_interval_sec: float = 0.2) -> None:
        super().__init__(name="gesture-recognition-client")
        self._emit_interval_sec = emit_interval_sec
        self._last_emit_ts = 0.0
        self._mock_labels = ("open_palm", "fist", "point")
        self._idx = 0

    async def _process_frame(self, frame: bytes) -> bytes | None:
        del frame
        now = time.monotonic()
        if now - self._last_emit_ts < self._emit_interval_sec:
            return None
        self._last_emit_ts = now
        label = self._mock_labels[self._idx % len(self._mock_labels)]
        self._idx += 1
        return f"GESTURE:{label}".encode("utf-8")

