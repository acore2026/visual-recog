from __future__ import annotations

import asyncio
import logging
from typing import Set

logger = logging.getLogger(__name__)


class WebSocketSender:
    """WebSocket 下游发送器，支持多客户端连接"""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._clients: Set[asyncio.StreamWriter] = set()
        self._server: asyncio.Server | None = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._running = False
        self._broadcast_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动 WebSocket 服务器"""
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port
        )
        self._running = True
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """停止 WebSocket 服务器"""
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

        logger.info("WebSocket server stopped")

    async def send(self, payload: bytes) -> None:
        """将帧放入广播队列"""
        if not self._running:
            raise RuntimeError("WebSocketSender is not started")

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
        """处理 WebSocket 客户端连接"""
        addr = writer.get_extra_info('peername')
        logger.info(f"WebSocket client connected: {addr}")

        # 等待 WebSocket 握手
        try:
            if not await self._perform_handshake(reader, writer):
                logger.warning(f"WebSocket handshake failed for {addr}")
                writer.close()
                await writer.wait_closed()
                return
        except Exception as e:
            logger.error(f"WebSocket handshake error: {e}")
            writer.close()
            return

        self._clients.add(writer)

        try:
            # 保持连接并处理客户端消息（如 ping/pong）
            while self._running:
                try:
                    # 读取 WebSocket 帧
                    frame = await self._read_ws_frame(reader)
                    if frame is None:
                        break

                    opcode, data = frame
                    if opcode == 0x8:  # Close frame
                        break
                    elif opcode == 0x9:  # Ping
                        await self._send_pong(writer)
                    elif opcode == 0x1:  # Text frame - 可能是 JSON 控制命令
                        await self._handle_client_message(data.decode('utf-8', errors='ignore'))

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.debug(f"Client {addr} error: {e}")
                    break
        finally:
            self._clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"WebSocket client disconnected: {addr}")

    async def _perform_handshake(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> bool:
        """执行 WebSocket 握手"""
        # 读取 HTTP 请求头
        headers = []
        while True:
            line = await reader.readline()
            if line == b'\r\n' or line == b'':
                break
            headers.append(line.decode('utf-8', errors='ignore'))

        if not headers:
            return False

        # 检查是否是有效的 WebSocket 升级请求
        request_line = headers[0]
        if 'GET' not in request_line or 'HTTP/1.1' not in request_line:
            return False

        # 提取 key 并生成 accept
        ws_key = None
        for header in headers:
            if header.lower().startswith('sec-websocket-key:'):
                ws_key = header.split(':', 1)[1].strip()
                break

        if not ws_key:
            return False

        import hashlib
        import base64

        GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        accept_key = base64.b64encode(
            hashlib.sha1((ws_key + GUID).encode()).digest()
        ).decode()

        # 发送握手响应
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n"
            "\r\n"
        )
        writer.write(response.encode())
        await writer.drain()

        return True

    async def _read_ws_frame(
        self,
        reader: asyncio.StreamReader
    ) -> tuple[int, bytes] | None:
        """读取 WebSocket 帧"""
        # 读取帧头
        header = await reader.read(2)
        if len(header) < 2:
            return None

        fin = (header[0] & 0x80) != 0
        opcode = header[0] & 0x0f
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7f

        # 读取扩展长度
        if length == 126:
            ext_len = await reader.read(2)
            length = int.from_bytes(ext_len, 'big')
        elif length == 127:
            ext_len = await reader.read(8)
            length = int.from_bytes(ext_len, 'big')

        # 读取 mask key
        if masked:
            mask_key = await reader.read(4)

        # 读取 payload
        payload = await reader.read(length)
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        return opcode, payload

    async def _send_ws_frame(
        self,
        writer: asyncio.StreamWriter,
        opcode: int,
        data: bytes
    ) -> None:
        """发送 WebSocket 帧"""
        length = len(data)

        # 构建帧头
        if length < 126:
            header = bytes([0x80 | opcode, length])
        elif length < 65536:
            header = bytes([0x80 | opcode, 126]) + length.to_bytes(2, 'big')
        else:
            header = bytes([0x80 | opcode, 127]) + length.to_bytes(8, 'big')

        # Debug: log first few bytes of data
        data_preview = data[:20].hex()
        is_jpeg = len(data) >= 3 and data[0] == 0xFF and data[1] == 0xD8 and data[2] == 0xFF
        logger.info(f"[WebSocket] Sending frame: opcode={opcode}, length={length}, is_jpeg={is_jpeg}, header={data_preview}")

        writer.write(header + data)
        await writer.drain()

    async def _send_pong(self, writer: asyncio.StreamWriter) -> None:
        """发送 pong 响应"""
        await self._send_ws_frame(writer, 0xA, b"")

    async def _handle_client_message(self, message: str) -> None:
        """处理客户端消息"""
        try:
            import json
            data = json.loads(message)
            if data.get("action") == "ping":
                # pong 会在连接循环中处理
                pass
        except json.JSONDecodeError:
            pass

    async def _broadcast_loop(self) -> None:
        """广播循环，将队列中的帧发送给所有客户端"""
        frame_count = 0
        last_log_time = 0
        import time

        while self._running:
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            frame_count += 1

            # 如果没有客户端连接，输出提示
            if not self._clients:
                now = time.time()
                if now - last_log_time > 5:
                    logger.warning(f"No WebSocket clients connected. Frame {frame_count} queued but not sent.")
                    last_log_time = now
                continue

            # 发送给所有客户端
            disconnected = set()
            for writer in list(self._clients):  # 使用list复制避免修改集合
                try:
                    await self._send_ws_frame(writer, 0x2, frame)  # 0x2 = binary
                    logger.debug(f"Frame sent to client, size={len(frame)} bytes")
                except Exception as e:
                    logger.debug(f"Failed to send frame to client: {e}")
                    disconnected.add(writer)

            # 清理断开的连接
            for writer in disconnected:
                self._clients.discard(writer)
                try:
                    writer.close()
                except Exception:
                    pass

            # 定期输出统计
            now = time.time()
            if now - last_log_time > 5:
                logger.info(f"WebSocket broadcast: {frame_count} frames sent to {len(self._clients)} clients")
                last_log_time = now
