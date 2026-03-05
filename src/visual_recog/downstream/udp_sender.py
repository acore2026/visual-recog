from __future__ import annotations

import asyncio


class UDPSender:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=(self.host, self.port),
        )
        self._transport = transport

    async def send(self, payload: bytes) -> None:
        if not self._transport:
            raise RuntimeError("UDPSender is not started")
        self._transport.sendto(payload)

    async def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None

