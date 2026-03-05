from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from .base import BaseClient

logger = logging.getLogger(__name__)

# 可选依赖检查
_np = None
_cv2 = None
_ort = None


def _check_dependencies() -> bool:
    """检查是否安装了必要的依赖"""
    global _np, _cv2, _ort
    if _np is not None and _cv2 is not None and _ort is not None:
        return True
    try:
        import numpy as np_lib
        import cv2 as cv2_lib
        import onnxruntime as ort_lib
        _np = np_lib
        _cv2 = cv2_lib
        _ort = ort_lib
        return True
    except ImportError:
        return False


def _get_np():
    """延迟导入 numpy"""
    global _np
    if _np is None:
        import numpy as np_lib
        _np = np_lib
    return _np


def _get_cv2():
    """延迟导入 cv2"""
    global _cv2
    if _cv2 is None:
        import cv2 as cv2_lib
        _cv2 = cv2_lib
    return _cv2


def _get_ort():
    """延迟导入 onnxruntime"""
    global _ort
    if _ort is None:
        import onnxruntime as ort_lib
        _ort = ort_lib
    return _ort


class Det:
    """检测结果"""

    def __init__(
        self,
        cls_id: int,
        score: float,
        xyxy: Tuple[float, float, float, float],
        label: Optional[str] = None,
    ):
        self.cls_id = cls_id
        self.score = score
        self.xyxy = xyxy
        self.label = label


class Shape:
    """图像尺寸"""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height

    @property
    def wh(self) -> Tuple[int, int]:
        return (self.width, self.height)

    @property
    def hw(self) -> Tuple[int, int]:
        return (self.height, self.width)


def _letterbox(
    img,
    new_shape: Tuple[int, int] = (640, 640),
    color: Tuple[int, int, int] = (114, 114, 114),
    auto: bool = True,
    scaleFill: bool = False,
    scaleup: bool = True,
):
    """Letterbox resize - 保持宽高比的缩放"""
    np = _get_np()
    cv2 = _get_cv2()

    shape = img.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    # Scale ratio (new / old)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    if not scaleup:
        r = min(r, 1.0)

    # Compute padding
    ratio = r, r
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    if auto:
        dw, dh = np.mod(dw, 32), np.mod(dh, 32)
    elif scaleFill:
        dw, dh = 0.0, 0.0
        new_unpad = (new_shape[1], new_shape[0])
        ratio = new_shape[1] / shape[1], new_shape[0] / shape[0]

    dw /= 2
    dh /= 2

    if shape[::-1] != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)


def _preprocess_frame(
    img,
    input_size: Tuple[int, int] = (640, 640),
    normalize: bool = True,
):
    """预处理图像帧"""
    np = _get_np()

    # Letterbox resize
    img_resized, scale, (pad_w, pad_h) = _letterbox(img, new_shape=input_size)

    # HWC -> CHW
    if normalize:
        img_transposed = img_resized.transpose(2, 0, 1).astype(np.float32) / 255.0
    else:
        img_transposed = img_resized.transpose(2, 0, 1)

    # 添加batch维度: (1, 3, H, W)
    img_batch = img_transposed[np.newaxis, :]

    return img_batch, scale, (pad_w, pad_h)


def _xywh2xyxy(x):
    """Convert boxes from [x, y, w, h] to [x1, y1, x2, y2]"""
    np = _get_np()
    y = np.empty_like(x)
    half_w = x[:, 2] * 0.5
    half_h = x[:, 3] * 0.5
    y[:, 0] = x[:, 0] - half_w
    y[:, 1] = x[:, 1] - half_h
    y[:, 2] = x[:, 0] + half_w
    y[:, 3] = x[:, 1] + half_h
    return y


def _nms(boxes, scores, iou_threshold: float = 0.45):
    """Non-Maximum Suppression"""
    np = _get_np()
    if len(boxes) == 0:
        return np.array([], dtype=np.int32)

    order = scores.argsort()[::-1]
    keep = []

    while len(order) > 0:
        i = order[0]
        keep.append(i)

        if len(order) == 1:
            break

        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h

        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_others = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (boxes[order[1:], 3] - boxes[order[1:], 1])
        iou = inter / (area_i + area_others - inter + 1e-7)

        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return np.array(keep, dtype=np.int32)


def _postprocess_detections(
    outputs,
    original_shape: Shape,
    input_shape: Tuple[int, int],
    scale: float,
    pad: Tuple[float, float],
    conf_threshold: float = 0.5,
    iou_threshold: float = 0.45,
    labels: Optional[List[str]] = None,
) -> List[Det]:
    """后处理检测结果"""
    np = _get_np()

    if len(outputs.shape) == 3:
        outputs = outputs[0]

    if outputs.shape[0] < outputs.shape[1] and outputs.shape[0] >= 4:
        outputs = outputs.T

    if outputs.shape[1] < 5:
        return []

    boxes = outputs[:, :4]
    scores = outputs[:, 4:]

    if scores.shape[1] > 1:
        first_col_max = np.max(scores[:, 0]) if len(scores) > 0 else 0
        if first_col_max <= 1.1:
            class_scores = np.max(scores[:, 1:], axis=1)
            class_ids = np.argmax(scores[:, 1:], axis=1)
            final_scores = scores[:, 0] * class_scores
        else:
            class_scores = np.max(scores, axis=1)
            class_ids = np.argmax(scores, axis=1)
            final_scores = class_scores
    else:
        final_scores = scores[:, 0]
        class_ids = np.zeros(len(scores), dtype=np.int32)

    mask = final_scores >= conf_threshold
    boxes = boxes[mask]
    scores = final_scores[mask]
    class_ids = class_ids[mask]

    if len(boxes) == 0:
        return []

    boxes_xyxy = _xywh2xyxy(boxes)

    scale_inv = 1.0 / scale
    pad_w, pad_h = pad
    boxes_xyxy[:, 0] = np.clip((boxes_xyxy[:, 0] - pad_w) * scale_inv, 0, original_shape.width)
    boxes_xyxy[:, 1] = np.clip((boxes_xyxy[:, 1] - pad_h) * scale_inv, 0, original_shape.height)
    boxes_xyxy[:, 2] = np.clip((boxes_xyxy[:, 2] - pad_w) * scale_inv, 0, original_shape.width)
    boxes_xyxy[:, 3] = np.clip((boxes_xyxy[:, 3] - pad_h) * scale_inv, 0, original_shape.height)

    keep = _nms(boxes_xyxy, scores, iou_threshold)

    detections = []
    for idx in keep:
        label = labels[class_ids[idx]] if labels and class_ids[idx] < len(labels) else None
        detections.append(
            Det(
                cls_id=int(class_ids[idx]),
                score=float(scores[idx]),
                xyxy=tuple(boxes_xyxy[idx].tolist()),
                label=label,
            )
        )

    return detections


def _draw_detections(
    img,
    detections: List[Det],
    box_thickness: int = 2,
    font_scale: float = 0.6,
    font_thickness: int = 1,
):
    """在图像上绘制检测框"""
    cv2 = _get_cv2()

    default_colors = [
        (0, 255, 0),
        (255, 0, 0),
        (0, 0, 255),
        (255, 255, 0),
        (255, 0, 255),
        (0, 255, 255),
    ]

    for det in detections:
        x1, y1, x2, y2 = det.xyxy
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        color = default_colors[det.cls_id % len(default_colors)]

        cv2.rectangle(img, (x1, y1), (x2, y2), color, box_thickness)

        if det.label:
            label_text = f"{det.label}: {det.score:.2f}"
        else:
            label_text = f"cls_{det.cls_id}: {det.score:.2f}"

        (text_width, text_height), baseline = cv2.getTextSize(
            label_text,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            font_thickness,
        )

        cv2.rectangle(
            img,
            (x1, y1 - text_height - baseline - 5),
            (x1 + text_width, y1),
            color,
            -1,
        )

        cv2.putText(
            img,
            label_text,
            (x1, y1 - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            font_thickness,
            cv2.LINE_AA,
        )

    return img


class ONNXDetector:
    """ONNX Runtime检测器 - 从YOLO项目适配"""

    def __init__(
        self,
        model_path: str,
        device: str = "cpu",
        input_size: Tuple[int, int] = (640, 640),
        conf_threshold: float = 0.5,
        iou_threshold: float = 0.45,
        labels: Optional[List[str]] = None,
    ):
        ort = _get_ort()

        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.labels = labels or []

        providers = []
        if device == "cuda":
            if "CUDAExecutionProvider" in ort.get_available_providers():
                providers.append("CUDAExecutionProvider")
                logger.info("Using CUDA execution provider")
            else:
                logger.warning("CUDA not available, falling back to CPU")
                providers.append("CPUExecutionProvider")
        else:
            providers.append("CPUExecutionProvider")

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        logger.info(f"Loading ONNX model: {model_path}")
        self.session = ort.InferenceSession(
            str(self.model_path),
            sess_options=sess_options,
            providers=providers,
        )

        self.input_name = self.session.get_inputs()[0].name
        input_shape = self.session.get_inputs()[0].shape
        logger.info(f"Model input: {self.input_name}, shape: {input_shape}")

    def infer(self, img) -> List[Det]:
        """对单帧进行推理"""
        original_shape = Shape(width=img.shape[1], height=img.shape[0])

        preprocessed, scale, (pad_w, pad_h) = _preprocess_frame(
            img, input_size=self.input_size, normalize=True
        )

        outputs = self.session.run(None, {self.input_name: preprocessed})

        detections = _postprocess_detections(
            outputs=outputs[0] if isinstance(outputs, list) else outputs,
            original_shape=original_shape,
            input_shape=self.input_size,
            scale=scale,
            pad=(pad_w, pad_h),
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
            labels=self.labels,
        )

        return detections


class ObjectRecognitionClient(BaseClient):
    """
    物体识别客户端 - 使用YOLO模型进行物体检测并在帧上绘制检测框。

    环境变量:
        YOLO_MODEL_PATH: ONNX模型路径 (必需)
        YOLO_DEVICE: 运行设备，"cpu" 或 "cuda" (默认: cpu)
        YOLO_INPUT_SIZE: 模型输入尺寸，格式 "640,640" (默认: 640,640)
        YOLO_CONF_THRESHOLD: 置信度阈值 (默认: 0.5)
        YOLO_IOU_THRESHOLD: NMS IoU阈值 (默认: 0.45)
        YOLO_LABELS: 类别标签，逗号分隔 (默认: 空)
    """

    def __init__(self) -> None:
        super().__init__(name="object-recognition-client")
        self._detector: Optional[ONNXDetector] = None
        self._init_detector()

    def _init_detector(self) -> None:
        """初始化检测器"""
        import os

        model_path = os.environ.get("YOLO_MODEL_PATH")
        if not model_path:
            logger.warning(
                "YOLO_MODEL_PATH not set, object detection will be disabled. "
                "Set it to enable YOLO inference."
            )
            return

        device = os.environ.get("YOLO_DEVICE", "cpu")
        input_size_str = os.environ.get("YOLO_INPUT_SIZE", "640,640")
        input_size = tuple(int(x) for x in input_size_str.split(","))
        conf_threshold = float(os.environ.get("YOLO_CONF_THRESHOLD", "0.5"))
        iou_threshold = float(os.environ.get("YOLO_IOU_THRESHOLD", "0.45"))
        labels_str = os.environ.get("YOLO_LABELS", "")
        labels = [l.strip() for l in labels_str.split(",") if l.strip()] if labels_str else None

        try:
            self._detector = ONNXDetector(
                model_path=model_path,
                device=device,
                input_size=input_size,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
                labels=labels,
            )
            logger.info(f"Object recognition client initialized with model: {model_path}")
        except Exception as e:
            logger.error(f"Failed to initialize detector: {e}")
            self._detector = None

    async def _process_frame(self, frame: bytes) -> bytes:
        """
        处理单帧：解码 -> 推理 -> 绘制检测框 -> 编码

        输入帧格式支持:
        - 原始图像字节 (JPEG/PNG等，通过cv2.imdecode解码)
        - 如果解码失败，直接返回原帧
        """
        if not _check_dependencies():
            logger.warning("opencv-python or onnxruntime not installed, skipping detection")
            return frame

        np = _get_np()
        cv2 = _get_cv2()

        # 解码帧
        try:
            img_array = np.frombuffer(frame, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is None:
                logger.debug("Failed to decode frame, returning original")
                return frame
        except Exception as e:
            logger.debug(f"Frame decode error: {e}")
            return frame

        # 推理和绘制
        if self._detector is not None:
            try:
                # 在事件循环的线程池中运行推理（避免阻塞）
                loop = asyncio.get_event_loop()
                detections = await loop.run_in_executor(
                    None, self._detector.infer, img
                )

                # 绘制检测框
                if detections:
                    img = _draw_detections(img, detections)
                    logger.debug(f"Detected {len(detections)} objects")
            except Exception as e:
                logger.warning(f"Inference error: {e}")

        # 编码回字节
        try:
            success, encoded = cv2.imencode(".jpg", img)
            if success:
                return encoded.tobytes()
        except Exception as e:
            logger.debug(f"Frame encode error: {e}")

        return frame

