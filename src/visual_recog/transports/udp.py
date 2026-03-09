from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InboundPacket:
    stream_id: str
    payload: bytes


class _JPEGFrameAssembler:
    """JPEG 帧组装器 - 将多个 UDP 包组装成完整的 JPEG 帧"""

    def __init__(self) -> None:
        self._buffer: bytes = b""
        self._frame_count = 0
        self._packet_count = 0

    def add_packet(self, data: bytes) -> bytes | None:
        """
        添加一个 UDP 包，如果组装成完整帧则返回帧数据
        """
        self._packet_count += 1

        # 检查是否是新的帧开始 (SOI: FF D8)
        is_new_frame = len(data) >= 2 and data[0] == 0xFF and data[1] == 0xD8

        # 诊断日志：每个包的关键信息
        header = data[:4].hex() if len(data) >= 4 else data.hex()
        tail = data[-4:].hex() if len(data) >= 4 else data.hex()
        logger.info(f"[Assembler] Packet #{self._packet_count}: size={len(data)}, header={header}, tail={tail}, is_new_frame={is_new_frame}")

        if is_new_frame:
            if self._buffer:
                # 新帧开始但旧帧未结束 - 可能是丢包或上一帧不完整
                has_eoi = b"\xFF\xD9" in self._buffer
                logger.warning(f"[Assembler] New SOI detected but previous frame not closed. Buffer={len(self._buffer)}, has_eoi={has_eoi}")
                if not has_eoi:
                    self._buffer += b"\xFF\xD9"  # 强制结束
                result = self._buffer
                self._buffer = data
                return result
            else:
                self._buffer = data
        else:
            self._buffer += data

        # 检查是否包含 EOI (FF D9)
        if b"\xFF\xD9" in self._buffer:
            eoi_pos = self._buffer.find(b"\xFF\xD9") + 2
            result = self._buffer[:eoi_pos]
            remaining = self._buffer[eoi_pos:]

            self._frame_count += 1

            # 检查EOI位置是否合理（不应该在帧开头附近）
            if eoi_pos < 1000:
                logger.warning(f"[Assembler] Frame #{self._frame_count}: EOI at position {eoi_pos} seems too early! Frame size: {len(result)}")

            logger.info(f"[Assembler] Frame #{self._frame_count} complete: {len(result)} bytes from {self._packet_count} packets, EOI at {eoi_pos}")

            # 处理剩余数据
            if len(remaining) >= 2 and remaining[0] == 0xFF and remaining[1] == 0xD8:
                self._buffer = remaining
                logger.info(f"[Assembler] Remaining data kept: {len(remaining)} bytes")
            else:
                if remaining:
                    logger.warning(f"[Assembler] Discarding {len(remaining)} bytes after EOI")
                self._buffer = b""

            return result

        return None


class _UDPIngressProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[InboundPacket]) -> None:
        self.queue = queue
        self._packet_count = 0
        self._frame_count = 0
        self._last_log_time = 0
        self._assemblers: Dict[str, _JPEGFrameAssembler] = {}

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._packet_count += 1
        stream_id = f"udp://{addr[0]}:{addr[1]}"

        # 为每个源地址创建组装器
        if stream_id not in self._assemblers:
            self._assemblers[stream_id] = _JPEGFrameAssembler()
            logger.info(f"New stream detected: {stream_id}")

        assembler = self._assemblers[stream_id]
        frame = assembler.add_packet(data)

        if frame:
            self._frame_count += 1
            is_jpeg = len(frame) >= 3 and frame[0] == 0xFF and frame[1] == 0xD8
            logger.info(f"[UDP] Frame #{self._frame_count} assembled: {len(frame)} bytes, is_jpeg={is_jpeg}")
            self.queue.put_nowait(InboundPacket(stream_id=stream_id, payload=frame))

        import time
        now = time.time()
        if self._frame_count == 1:
            logger.info(f"First frame received from {stream_id}")
        elif self._frame_count % 30 == 0 or (now - self._last_log_time) > 5:
            logger.info(f"UDP stats: {self._packet_count} packets, {self._frame_count} frames")
            self._last_log_time = now


class UDPIngress:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        self.queue: asyncio.Queue[InboundPacket] = asyncio.Queue(maxsize=1024)

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPIngressProtocol(self.queue),
            local_addr=(self.host, self.port),
        )
        self._transport = transport

    async def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None
