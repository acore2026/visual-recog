from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription


@dataclass(slots=True)
class InboundFrame:
    stream_id: str
    payload: bytes


class WebRTCIngress:
    """
    Minimal WebRTC receiver.
    Signaling endpoint: POST /offer with JSON {"sdp": "...", "type": "offer"}.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.queue: asyncio.Queue[InboundFrame] = asyncio.Queue(maxsize=1024)
        self._pcs: set[RTCPeerConnection] = set()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def _on_offer(self, request: web.Request) -> web.Response:
        payload = await request.json()
        offer = RTCSessionDescription(sdp=payload["sdp"], type=payload["type"])
        pc = RTCPeerConnection()
        self._pcs.add(pc)
        stream_id = f"webrtc://{id(pc)}"

        @pc.on("track")
        def on_track(track) -> None:  # type: ignore[no-untyped-def]
            if track.kind != "video":
                return

            async def recv_video() -> None:
                while True:
                    try:
                        frame = await track.recv()
                    except Exception:
                        break
                    # Keep representation generic: textual metadata + raw plane bytes.
                    plane = frame.planes[0]
                    raw = bytes(plane)
                    header = f"{frame.width}x{frame.height}:{frame.format.name}|".encode(
                        "utf-8"
                    )
                    self.queue.put_nowait(
                        InboundFrame(stream_id=stream_id, payload=header + raw)
                    )

            asyncio.create_task(recv_video())

        @pc.on("connectionstatechange")
        async def on_state_change() -> None:
            if pc.connectionState in {"failed", "closed", "disconnected"}:
                await pc.close()
                self._pcs.discard(pc)

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        response = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        return web.Response(text=json.dumps(response), content_type="application/json")

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/offer", self._on_offer)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self.host, port=self.port)
        await self._site.start()

    async def stop(self) -> None:
        for pc in list(self._pcs):
            await pc.close()
        self._pcs.clear()
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

