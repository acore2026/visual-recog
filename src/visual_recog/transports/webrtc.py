from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription

logger = logging.getLogger(__name__)

# 延迟导入的可选依赖
_cv2 = None
_np = None


def _get_cv2():
    """延迟导入 cv2"""
    global _cv2
    if _cv2 is None:
        import cv2 as cv2_lib
        _cv2 = cv2_lib
    return _cv2


def _get_np():
    """延迟导入 numpy"""
    global _np
    if _np is None:
        import numpy as np_lib
        _np = np_lib
    return _np


@dataclass(slots=True)
class InboundFrame:
    stream_id: str
    payload: bytes


class WebRTCIngress:
    """
    WebRTC接收器 - 接收视频流并输出JPEG编码的帧。
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
                frame_count = 0
                cv2 = _get_cv2()
                while True:
                    try:
                        frame = await track.recv()
                        frame_count += 1
                    except Exception:
                        break

                    # 将帧转换为BGR格式的numpy数组
                    try:
                        img = frame.to_ndarray(format="bgr24")
                        # 编码为JPEG
                        success, encoded = cv2.imencode(".jpg", img)
                        if success:
                            self.queue.put_nowait(
                                InboundFrame(stream_id=stream_id, payload=encoded.tobytes())
                            )
                            if frame_count % 30 == 0:
                                logger.debug(f"Received {frame_count} frames from {stream_id}")
                        else:
                            logger.warning("Failed to encode frame to JPEG")
                    except Exception as e:
                        logger.warning(f"Frame processing error: {e}")

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

