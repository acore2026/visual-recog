from __future__ import annotations

import abc
import asyncio


class ClientBusyError(RuntimeError):
    """Raised when another stream is already being processed."""


class BaseClient(abc.ABC):
    def __init__(self, name: str) -> None:
        self.name = name
        self._active_stream_id: str | None = None
        self._state_lock = asyncio.Lock()

    async def process(self, stream_id: str, frame: bytes) -> bytes | None:
        async with self._state_lock:
            if self._active_stream_id is None:
                self._active_stream_id = stream_id
            elif self._active_stream_id != stream_id:
                raise ClientBusyError(
                    f"{self.name} is busy with stream={self._active_stream_id}, reject stream={stream_id}"
                )
        return await self._process_frame(frame)

    async def release_stream(self, stream_id: str) -> None:
        async with self._state_lock:
            if self._active_stream_id == stream_id:
                self._active_stream_id = None

    @abc.abstractmethod
    async def _process_frame(self, frame: bytes) -> bytes | None:
        """Process one frame and return payload for downstream."""

