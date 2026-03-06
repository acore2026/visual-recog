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
        │   ├── udp_sender.py
        │   ├── ws_sender.py
        │   └── http_mjpeg_sender.py
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

2. UDP 输入 + 物体识别模式 + WebSocket 输出（浏览器可直接连接）
```bash
visual-recog \
  --mode object \
  --protocol udp \
  --listen-host 0.0.0.0 \
  --listen-port 9000 \
  --downstream-protocol websocket \
  --downstream-host 0.0.0.0 \
  --downstream-port 8765
```

3. UDP 输入 + 物体识别模式 + HTTP MJPEG 输出（浏览器 `<img>` 标签直接显示）
```bash
visual-recog \
  --mode object \
  --protocol udp \
  --listen-host 0.0.0.0 \
  --listen-port 9000 \
  --downstream-protocol http-mjpeg \
  --downstream-host 0.0.0.0 \
  --downstream-port 8080
```

4. WebRTC 输入 + 手势识别模式
```bash
visual-recog \
  --mode gesture \
  --protocol webrtc \
  --listen-host 0.0.0.0 \
  --listen-port 9001 \
  --downstream-host 127.0.0.1 \
  --downstream-port 9100
```

5. **透传模式（用于调试）**
```bash
visual-recog \
  --mode passthrough \
  --protocol udp \
  --listen-host 0.0.0.0 \
  --listen-port 9000 \
  --downstream-protocol websocket \
  --downstream-host 0.0.0.0 \
  --downstream-port 8765
```

透传模式会：
- 原样转发收到的视频流，不做任何处理
- 输出详细的收发统计日志
- 用于排查网络连通性问题

## 下游输出协议说明

服务支持三种下游输出协议，通过 `--downstream-protocol` 参数指定：

| 协议 | 说明 | 适用场景 |
|------|------|----------|
| `udp` | 原始 UDP 发送 JPEG 帧 | 传统下游设备、局域网传输 |
| `websocket` | WebSocket 服务器，支持多客户端 | Web 前端、PWA、移动 App |
| `http-mjpeg` | HTTP MJPEG 流 | 浏览器 `<img>` 标签直接显示 |

### WebSocket 输出
```bash
visual-recog --downstream-protocol websocket --downstream-port 8765
```
- 支持多客户端同时观看
- 浏览器使用 `new WebSocket('ws://host:8765')` 连接
- 二进制帧格式：JPEG 图像数据

### HTTP MJPEG 输出
```bash
visual-recog --downstream-protocol http-mjpeg --downstream-port 8080
```
- 浏览器直接用 `<img src="http://host:8080/mjpeg">` 显示
- 支持多客户端
- 跨域支持（CORS 已启用）

### UDP 输出（默认）
```bash
visual-recog --downstream-protocol udp --downstream-port 9100
```
- 单播 UDP 发送
- 适合传统下游设备接收

## 当前实现说明
- `object` 模式：使用 YOLO ONNX 模型进行物体检测，在每帧上绘制检测框后输出到下游。
- `gesture` 模式：每 0.2 秒输出一次手势标签（占位逻辑，待替换 YOLOv8 推理）。
- 单实例 client 并发限制：同一时刻仅允许 1 路 `stream_id` 被处理，其他流会被拒绝并记录日志。
- WebRTC 信令接口：`POST /offer`，请求体为 `{ "sdp": "...", "type": "offer" }`，返回 answer。

## 物体识别模式配置
物体识别客户端 (`object_client`) 支持以下环境变量配置：

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `YOLO_MODEL_PATH` | ONNX 模型文件路径（必需） | - |
| `YOLO_DEVICE` | 运行设备，`cpu` 或 `cuda` | `cpu` |
| `YOLO_INPUT_SIZE` | 模型输入尺寸，格式 `640,640` | `640,640` |
| `YOLO_CONF_THRESHOLD` | 置信度阈值 | `0.5` |
| `YOLO_IOU_THRESHOLD` | NMS IoU 阈值 | `0.45` |
| `YOLO_LABELS` | 类别标签，逗号分隔 | - |

### 物体识别模式启动示例
```bash
# 设置模型路径（必需）
export YOLO_MODEL_PATH=/path/to/yolov8n.onnx

# 可选：设置类别标签
export YOLO_LABELS="person,car,bicycle,motorcycle,bus,truck"

# 启动服务
visual-recog \
  --mode object \
  --protocol webrtc \
  --listen-host 0.0.0.0 \
  --listen-port 9000 \
  --downstream-host 127.0.0.1 \
  --downstream-port 9100
```

### 输入输出格式
- **输入**：JPEG 编码的视频帧（WebRTC 或 UDP）
- **输出**：带有检测框的 JPEG 编码视频帧（通过 UDP 发送到下游）

### 模型准备
1. 从 [Ultralytics](https://github.com/ultralytics/ultralytics) 导出 YOLO ONNX 模型：
```bash
yolo export model=yolov8n.pt format=onnx opset=12
```
2. 或使用 YOLO-World 模型进行开放词汇检测。

### 上游设备推流（Linux + ffmpeg）
对于 Linux 环境的上游设备，推荐使用 ffmpeg 将摄像头画面通过 UDP 推送到本服务。

#### 基础推流命令
```bash
ffmpeg -f v4l2 -i /dev/video0 \
    -vf "fps=15,scale=640:480" \
    -c:v mjpeg -q:v 3 \
    -f mjpeg udp://127.0.0.1:9000
```

参数说明：
- `-f v4l2 -i /dev/video0`: 从摄像头设备读取（`/dev/video0` 为默认摄像头）
- `-vf "fps=15,scale=640:480"`: 限制 15fps，分辨率 640x480（降低带宽）
- `-c:v mjpeg`: 使用 MJPEG 编码
- `-q:v 3`: JPEG 质量（1-31，数值越小质量越高）
- `-f mjpeg udp://127.0.0.1:9000`: 以 JPEG 流格式发送到 UDP

#### 带缓冲的优化版本（网络不稳定时推荐）
```bash
ffmpeg -f v4l2 -i /dev/video0 \
    -thread_queue_size 512 \
    -vf "fps=10,scale=640:480,format=yuv420p" \
    -c:v mjpeg -q:v 5 \
    -buffer_size 65536 \
    -pkt_size 1400 \
    -f mjpeg udp://127.0.0.1:9000?pkt_size=1400
```

#### 查看可用摄像头
```bash
# 列出摄像头设备
ls -l /dev/video*

# 查看摄像头支持的格式
ffmpeg -f v4l2 -list_formats all -i /dev/video0
```

#### 跨机器推流
如果 visual-recog 服务运行在另一台机器（如 192.168.1.100）：
```bash
ffmpeg -f v4l2 -i /dev/video0 \
    -vf "fps=15,scale=640:480" \
    -c:v mjpeg -q:v 3 \
    -f mjpeg udp://192.168.1.100:9000
```

#### 注意事项
- **UDP 帧大小限制**：如果画面太大导致 UDP 包超过 MTU（1500字节），会出现丢帧。建议降低分辨率（`scale=640:480`）或提高 JPEG 压缩率（`-q:v 10`）
- **多摄像头**：如果有多个摄像头，尝试 `/dev/video1`、`/dev/video2` 等
- **WebRTC 限制**：ffmpeg 对 WebRTC 支持有限，如需使用 WebRTC，建议使用 GStreamer 或编写 Python 客户端

