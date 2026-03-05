from __future__ import annotations

from .base import BaseClient


class ObjectRecognitionClient(BaseClient):
    """
    Object recognition client (YOLO placeholder).
    In production replace this stub with real model inference.
    """

    def __init__(self) -> None:
        super().__init__(name="object-recognition-client")

    async def _process_frame(self, frame: bytes) -> bytes:
        # Placeholder: pretend model added bounding boxes to frame.
        return b"OBJECT_DETECTED_FRAME:" + frame

