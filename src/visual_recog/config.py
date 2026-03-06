from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(slots=True)
class AppConfig:
    mode: str
    protocol: str
    listen_host: str
    listen_port: int
    downstream_protocol: str
    downstream_host: str
    downstream_port: int


def parse_args() -> AppConfig:
    parser = argparse.ArgumentParser(
        description="视觉识别服务：接收 UDP/WebRTC 视频流并转发识别结果。"
    )
    parser.add_argument(
        "--mode",
        choices=["object", "gesture"],
        required=True,
        help="运行模式：object=物体识别, gesture=手势识别",
    )
    parser.add_argument(
        "--protocol",
        choices=["udp", "webrtc"],
        required=True,
        help="上游输入协议",
    )
    parser.add_argument("--listen-host", default="0.0.0.0", help="服务监听地址")
    parser.add_argument("--listen-port", type=int, required=True, help="服务监听端口")
    parser.add_argument(
        "--downstream-protocol",
        choices=["udp", "websocket", "http-mjpeg"],
        default="udp",
        help="下游输出协议 (default: udp)",
    )
    parser.add_argument(
        "--downstream-host", default="127.0.0.1", help="下游设备 IP 或主机名 (default: 127.0.0.1)"
    )
    parser.add_argument("--downstream-port", type=int, required=True, help="下游端口")
    args = parser.parse_args()
    return AppConfig(
        mode=args.mode,
        protocol=args.protocol,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        downstream_protocol=args.downstream_protocol,
        downstream_host=args.downstream_host,
        downstream_port=args.downstream_port,
    )

