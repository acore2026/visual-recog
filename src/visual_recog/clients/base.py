from __future__ import annotations

import abc
import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class ClientBusyError(RuntimeError):
    """Raised when another stream is already being processed."""


class BaseClient(abc.ABC):
    def __init__(self, name: str, stream_timeout: float = 10.0) -> None:
        self.name = name
        self._stream_timeout = stream_timeout
        self._active_stream_id: str | None = None
        self._last_frame_time: float = 0
        self._state_lock = asyncio.Lock()

    async def process(self, stream_id: str, frame: bytes) -> bytes | None:
        async with self._state_lock:
            now = time.time()

            # 检查是否超时，如果是则释放旧流
            if self._active_stream_id is not None and self._active_stream_id != stream_id:
                if now - self._last_frame_time > self._stream_timeout:
                    logger.warning(
                        f"{self.name}: Stream {self._active_stream_id} timed out (inactive for {now - self._last_frame_time:.1f}s), releasing"
                    )
                    self._active_stream_id = None
                else:
                    raise ClientBusyError(
                        f"{self.name} is busy with stream={self._active_stream_id}, reject stream={stream_id}"
                    )

            # 设置当前流
            if self._active_stream_id is None:
                self._active_stream_id = stream_id
                logger.info(f"{self.name}: Acquired stream {stream_id}")

            self._last_frame_time = now

        return await self._process_frame(frame)

    async def release_stream(self, stream_id: str) -> None:
        async with self._state_lock:
            if self._active_stream_id == stream_id:
                logger.info(f"{self.name}: Released stream {stream_id}")
                self._active_stream_id = None

    @abc.abstractmethod
    async def _process_frame(self, frame: bytes) -> bytes | None:
        """Process one frame and return payload for downstream."""

