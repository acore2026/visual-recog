from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(slots=True)
class InboundPacket:
    stream_id: str
    payload: bytes


class _UDPIngressProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[InboundPacket]) -> None:
        self.queue = queue

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        stream_id = f"udp://{addr[0]}:{addr[1]}"
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

