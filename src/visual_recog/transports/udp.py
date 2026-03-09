from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InboundPacket:
    stream_id: str
    payload: bytes


class _UDPIngressProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[InboundPacket]) -> None:
        self.queue = queue
        self._packet_count = 0
        self._last_log_time = 0

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._packet_count += 1
        stream_id = f"udp://{addr[0]}:{addr[1]}"

        # 检查是否是 JPEG
        is_jpeg = len(data) >= 3 and data[0] == 0xFF and data[1] == 0xD8 and data[2] == 0xFF
        header_hex = data[:20].hex()

        import time
        now = time.time()

        # 每个包都记录（临时调试）
        logger.info(f"[UDP] Packet #{self._packet_count} from {addr[0]}:{addr[1]}, size={len(data)}, is_jpeg={is_jpeg}, header={header_hex}")

        if self._packet_count == 1:
            logger.info(f"First UDP packet received from {addr[0]}:{addr[1]}, size={len(data)} bytes")
        elif self._packet_count % 100 == 0 or (now - self._last_log_time) > 5:
            logger.info(f"UDP packets received: {self._packet_count}, last from {addr[0]}:{addr[1]}, size={len(data)} bytes")
            self._last_log_time = now

        self.queue.put_nowait(InboundPacket(stream_id=stream_id, payload=data))


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

