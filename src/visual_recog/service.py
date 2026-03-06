from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from typing import Any

from .clients import ClientBusyError, GestureRecognitionClient, ObjectRecognitionClient, PassthroughClient
from .config import AppConfig
from .downstream import UDPSender, WebSocketSender, HTTPMJPEGSender
from .transports import UDPIngress

logger = logging.getLogger(__name__)


def _build_client(mode: str) -> ObjectRecognitionClient | GestureRecognitionClient | PassthroughClient:
    if mode == "object":
        return ObjectRecognitionClient()
    if mode == "gesture":
        return GestureRecognitionClient()
    if mode == "passthrough":
        return PassthroughClient()
    raise ValueError(f"unsupported mode: {mode}")


def _build_sender(config: AppConfig) -> UDPSender | WebSocketSender | HTTPMJPEGSender:
    if config.downstream_protocol == "udp":
        return UDPSender(config.downstream_host, config.downstream_port)
    if config.downstream_protocol == "websocket":
        return WebSocketSender(config.downstream_host, config.downstream_port)
    if config.downstream_protocol == "http-mjpeg":
        return HTTPMJPEGSender(config.downstream_host, config.downstream_port)
    raise ValueError(f"unsupported downstream protocol: {config.downstream_protocol}")


async def _run_pipeline(config: AppConfig) -> None:
    client = _build_client(config.mode)
    sender = _build_sender(config)
    if config.protocol == "udp":
        ingress: Any = UDPIngress(config.listen_host, config.listen_port)
    else:
        try:
            from .transports.webrtc import WebRTCIngress
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "WebRTC mode requires optional dependencies. Run: python3 -m pip install -e ."
            ) from exc

        ingress = WebRTCIngress(config.listen_host, config.listen_port)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    await ingress.start()
    await sender.start()
    logger.info(
        "service started: mode=%s protocol=%s listen=%s:%s downstream=%s:%s (%s)",
        config.mode,
        config.protocol,
        config.listen_host,
        config.listen_port,
        config.downstream_host,
        config.downstream_port,
        config.downstream_protocol,
    )

    try:
        frame_count = 0
        last_log_time = 0
        import time

        while not stop_event.is_set():
            try:
                item = await asyncio.wait_for(ingress.queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            frame_count += 1
            now = time.time()

            # 定期输出管道统计
            if now - last_log_time > 5:
                logger.info(f"Pipeline stats: {frame_count} frames received from ingress")
                last_log_time = now

            try:
                output = await client.process(item.stream_id, item.payload)
            except ClientBusyError as exc:
                logger.warning("%s", exc)
                continue
            except Exception as exc:
                logger.error(f"Client processing error: {exc}")
                continue

            if output:
                try:
                    await sender.send(output)
                    logger.debug(f"Frame sent to downstream: {len(output)} bytes")
                except Exception as exc:
                    logger.error(f"Failed to send to downstream: {exc}")
            else:
                logger.debug("Client returned no output")
    finally:
        await ingress.stop()
        await sender.stop()
        logger.info("service stopped")


async def run_service(config: AppConfig) -> None:
    await _run_pipeline(config)
