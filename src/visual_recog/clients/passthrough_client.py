from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict

from .base import BaseClient

logger = logging.getLogger(__name__)


class PassthroughClient(BaseClient):
    """
    透传客户端 - 直接转发原始视频流，不做任何处理。
    用于调试网络连通性和流状态。
    """

    def __init__(self) -> None:
        super().__init__(name="passthrough-client")
        self._stats: Dict[str, int] = {
            "frames_received": 0,
            "frames_sent": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
        }
        self._last_log_time = time.time()
        self._log_interval = 5.0  # 每5秒输出一次统计

    async def _process_frame(self, frame: bytes) -> bytes:
        """
        处理单帧：直接透传，记录统计信息

        输入: JPEG 图像字节
        输出: 同样的 JPEG 图像字节（原样返回）
        """
        self._stats["frames_received"] += 1
        self._stats["bytes_received"] += len(frame)
        self._stats["frames_sent"] += 1
        self._stats["bytes_sent"] += len(frame)

        # 定期输出统计
        now = time.time()
        if now - self._last_log_time >= self._log_interval:
            await self._print_stats()
            self._last_log_time = now

        # 记录每帧的详细信息（DEBUG级别）
        logger.debug(
            f"Frame passed through: {len(frame)} bytes, "
            f"total frames={self._stats['frames_received']}"
        )

        return frame

    async def _print_stats(self) -> None:
        """输出统计信息"""
        elapsed = time.time() - self._start_time if hasattr(self, '_start_time') else 0
        fps = self._stats["frames_received"] / elapsed if elapsed > 0 else 0

        logger.info(
            f"[Passthrough Stats] Frames: {self._stats['frames_received']} received, "
            f"{self._stats['frames_sent']} sent | "
            f"Bytes: {self._format_bytes(self._stats['bytes_received'])} received, "
            f"{self._format_bytes(self._stats['bytes_sent'])} sent | "
            f"Avg FPS: {fps:.1f}"
        )

    @staticmethod
    def _format_bytes(size: int) -> str:
        """格式化字节大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
