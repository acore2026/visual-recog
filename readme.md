# 视觉识别服务
## 描述
可以接收从上游设备通过webrtc或udp协议传来的视频流，并实时地将视频流通过不同client交给不同模型服务处理，再由client进行后续业务回复下游设备。

例子1：
指定用“物体识别模式”启动本服务。上游设备A通过udp传来它的实时摄像头视频流，本服务将使用“物体识别client”来通过yolo模型处理源视频流，并把识别的结果（只包含目标框的视频流）实时发往下游设备B。

例子2：
指定用“手势识别模式”启动本服务。上游设备A通过webrtc传来它的实时摄像头视频流，本服务将使用“手势识别client”来使用yolov8模型处理源视频流，并每0.2秒将当前手势类型发往下游设备B。

## 实现要求
1. 启动服务时可以配置：
    - 模式，即client实例实例类型
    - 本服务的监听端口
    - client目标下游设备的ip端口接口
2. 每个client应当每次同时最多处理1个视频流
3. 已知需要支持的client有“物体识别client”和“手势识别client”，它们的能力与例子中一致。

## 已生成工程结构
```
.
├── pyproject.toml
├── readme.md
└── src
    └── visual_recog
        ├── clients
        │   ├── base.py
        │   ├── gesture_client.py
        │   └── object_client.py
        ├── config.py
        ├── downstream
        │   └── udp_sender.py
        ├── main.py
        ├── service.py
        └── transports
            ├── udp.py
            └── webrtc.py
```

## 启动方式
1. 安装依赖
```bash
python3 -m pip install -e .
```

2. UDP 输入 + 物体识别模式
```bash
visual-recog \
  --mode object \
  --protocol udp \
  --listen-host 0.0.0.0 \
  --listen-port 9000 \
  --downstream-host 127.0.0.1 \
  --downstream-port 9100
```

3. WebRTC 输入 + 手势识别模式
```bash
visual-recog \
  --mode gesture \
  --protocol webrtc \
  --listen-host 0.0.0.0 \
  --listen-port 9001 \
  --downstream-host 127.0.0.1 \
  --downstream-port 9100
```

## 当前实现说明
- `object` 模式：每帧输出模拟“目标框结果”（占位逻辑，待替换 YOLO 推理）。
- `gesture` 模式：每 0.2 秒输出一次手势标签（占位逻辑，待替换 YOLOv8 推理）。
- 单实例 client 并发限制：同一时刻仅允许 1 路 `stream_id` 被处理，其他流会被拒绝并记录日志。
- WebRTC 信令接口：`POST /offer`，请求体为 `{ "sdp": "...", "type": "offer" }`，返回 answer。

