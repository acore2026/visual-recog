from __future__ import annotations

import asyncio
import logging
from typing import Set

logger = logging.getLogger(__name__)


class HTTPMJPEGSender:
    """HTTP MJPEG 下游发送器，浏览器可直接用 <img> 标签显示"""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._clients: Set[asyncio.StreamWriter] = set()
        self._server: asyncio.Server | None = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._running = False
        self._broadcast_task: asyncio.Task | None = None
        self._boundary = "--mjpeg-boundary-xyz123"

    async def start(self) -> None:
        """启动 HTTP MJPEG 服务器"""
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port
        )
        self._running = True
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        logger.info(f"HTTP MJPEG server started on http://{self.host}:{self.port}")
        logger.info(f"  Stream URL: http://{self.host}:{self.port}/mjpeg")

    async def stop(self) -> None:
        """停止 HTTP MJPEG 服务器"""
        self._running = False

        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass

        # 关闭所有客户端连接
        for writer in list(self._clients):
            writer.close()
            await writer.wait_closed()
        self._clients.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        logger.info("HTTP MJPEG server stopped")

    async def send(self, payload: bytes) -> None:
        """将帧放入广播队列"""
        if not self._running:
            raise RuntimeError("HTTPMJPEGSender is not started")

        # 非阻塞放入队列，满时丢弃旧帧
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()  # 丢弃最旧的帧
                self._queue.put_nowait(payload)
            except asyncio.QueueEmpty:
                pass

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        """处理 HTTP 客户端连接"""
        addr = writer.get_extra_info('peername')

        try:
            # 读取 HTTP 请求
            request_line = await reader.readline()
            if not request_line:
                return

            request = request_line.decode('utf-8', errors='ignore').strip()
            logger.debug(f"HTTP request from {addr}: {request}")

            # 读取请求头
            headers = {}
            while True:
                line = await reader.readline()
                if line == b'\r\n' or line == b'':
                    break
                parts = line.decode('utf-8', errors='ignore').strip().split(':', 1)
                if len(parts) == 2:
                    headers[parts[0].lower()] = parts[1].strip()

            # 解析请求路径
            parts = request.split()
            if len(parts) < 2:
                return

            path = parts[1]

            if path == '/mjpeg' or path == '/':
                await self._serve_mjpeg_stream(writer, addr)
            elif path == '/info':
                await self._serve_info(writer)
            else:
                await self._serve_404(writer)

        except Exception as e:
            logger.debug(f"Client {addr} error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _serve_mjpeg_stream(
        self,
        writer: asyncio.StreamWriter,
        addr: tuple
    ) -> None:
        """提供 MJPEG 视频流"""
        logger.info(f"MJPEG client connected: {addr}")

        # 发送 HTTP 响应头
        response = (
            "HTTP/1.0 200 OK\r\n"
            "Content-Type: multipart/x-mixed-replace; boundary=" + self._boundary + "\r\n"
            "Cache-Control: no-cache, no-store, must-revalidate\r\n"
            "Pragma: no-cache\r\n"
            "Expires: 0\r\n"
            "Connection: close\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "\r\n"
        )
        writer.write(response.encode())
        await writer.drain()

        self._clients.add(writer)

        try:
            # 保持连接，直到客户端断开
            while self._running and writer in self._clients:
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.debug(f"MJPEG stream error for {addr}: {e}")
        finally:
            self._clients.discard(writer)
            logger.info(f"MJPEG client disconnected: {addr}")

    async def _serve_info(self, writer: asyncio.StreamWriter) -> None:
        """提供流信息（JSON）"""
        import json

        info = {
            "stream_type": "mjpeg",
            "url": f"/mjpeg",
            "clients": len(self._clients),
        }

        body = json.dumps(info).encode()

        response = (
            "HTTP/1.0 200 OK\r\n"
            "Content-Type: application/json\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            f"Content-Length: {len(body)}\r\n"
            "\r\n"
        )
        writer.write(response.encode())
        writer.write(body)
        await writer.drain()

    async def _serve_404(self, writer: asyncio.StreamWriter) -> None:
        """返回 404"""
        body = b"Not Found"
        response = (
            "HTTP/1.0 404 Not Found\r\n"
            "Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            "\r\n"
        )
        writer.write(response.encode())
        writer.write(body)
        await writer.drain()

    async def _broadcast_loop(self) -> None:
        """广播循环，将队列中的帧发送给所有客户端"""
        frame_count = 0

        while self._running:
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if not self._clients:
                continue

            # 构建 MJPEG 帧
            header = (
                f"{self._boundary}\r\n"
                "Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(frame)}\r\n"
                "\r\n"
            ).encode()

            frame_data = header + frame + b"\r\n"

            # 发送给所有客户端
            disconnected = set()
            for writer in self._clients:
                try:
                    writer.write(frame_data)
                    await writer.drain()
                except Exception:
                    disconnected.add(writer)

            # 清理断开的连接
            for writer in disconnected:
                self._clients.discard(writer)

            frame_count += 1
            if frame_count % 100 == 0:
                logger.debug(f"Broadcast frame #{frame_count} to {len(self._clients)} clients")
