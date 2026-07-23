# -*- coding: utf-8 -*-
"""影像載入與前處理。"""

from __future__ import annotations

import math
import os
from typing import Optional, Tuple

import cv2
import numpy as np


def imread_unicode(file_path: str, flags: int = cv2.IMREAD_UNCHANGED) -> Optional[np.ndarray]:
    """讀圖，支援含非 ASCII（如中文）字元的路徑。

    OpenCV 的 cv2.imread 在 Windows 對非 ASCII 路徑可能失敗，這裡用 Python
    開檔讀 bytes 後交給 cv2.imdecode 解碼，繞過該限制。
    讀取或解碼失敗回傳 None。
    """
    try:
        with open(file_path, "rb") as f:
            buf = f.read()
    except OSError:
        return None
    if not buf:
        return None
    data = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(data, flags)


def imwrite_unicode(file_path: str, img: np.ndarray) -> bool:
    """寫圖，支援含非 ASCII 字元的路徑。

    副檔名決定編碼格式（無副檔名時預設 .png）。成功回傳 True。
    """
    ext = os.path.splitext(file_path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    try:
        with open(file_path, "wb") as f:
            f.write(buf.tobytes())
    except OSError:
        return False
    return True


class MeasurementPlaneError(ValueError):
    """輸入缺少正式 %FS 量測所需資訊。"""


class RawImage:
    """封裝一張 raw image 的載入、灰階正規化與取樣。

    典型用法：
        raw = RawImage.load("foo.bmp")
        sample, step = raw.analysis_sample()
    """

    def __init__(
        self,
        gray8: np.ndarray,
        original_dtype: str,
        norm_method: str = "uint8-copy",
        *,
        raw_gray: Optional[np.ndarray] = None,
        bit_depth: Optional[int] = None,
    ):
        self.gray8 = gray8
        self.raw_gray = raw_gray.copy() if raw_gray is not None else gray8.copy()
        self.original_dtype = original_dtype
        self.norm_method = norm_method
        self.bit_depth = (
            bit_depth if bit_depth is not None else self._infer_bit_depth(self.raw_gray)
        )
        self.full_scale = (1 << self.bit_depth) - 1 if self.bit_depth is not None else None

    @property
    def height(self) -> int:
        return int(self.raw_gray.shape[0])

    @property
    def width(self) -> int:
        return int(self.raw_gray.shape[1])

    @classmethod
    def load(
        cls,
        file_path: str,
        normalization: str = "linear",
        percentiles: Tuple[float, float] = (1.0, 99.0),
        bit_depth: Optional[int] = None,
    ) -> "RawImage":
        """讀圖並轉成 8-bit grayscale。讀圖失敗會丟出 RuntimeError。

        normalization 僅影響 16-bit 影像：
        - "linear"     : 0~65535 線性縮到 0~255（÷257）。感測器實際只用低位元時對比會被壓縮。
        - "percentile" : 依 percentiles=(low, high) 百分位拉伸，改善低動態範圍影像的可視/可分性。
        """
        img = imread_unicode(file_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"讀圖失敗：{file_path}")
        return cls.from_array(
            img,
            normalization=normalization,
            percentiles=percentiles,
            bit_depth=bit_depth,
        )

    @classmethod
    def from_array(
        cls,
        img: np.ndarray,
        normalization: str = "linear",
        percentiles: Tuple[float, float] = (1.0, 99.0),
        bit_depth: Optional[int] = None,
    ) -> "RawImage":
        """由陣列建立，保留原始灰階量測平面並另外產生 8-bit preview。"""
        raw_gray = cls._to_grayscale(img)
        if not np.all(np.isfinite(raw_gray)):
            raise ValueError("影像包含 NaN 或 Inf，不能建立可信量測平面")
        resolved_bit_depth = cls._resolve_bit_depth(raw_gray, bit_depth)
        gray8, original_dtype, norm_method = cls._normalize_to_8bit(
            raw_gray, normalization, percentiles, resolved_bit_depth
        )
        return cls(
            gray8,
            original_dtype,
            norm_method,
            raw_gray=raw_gray,
            bit_depth=resolved_bit_depth,
        )

    @staticmethod
    def _normalize_to_8bit(
        img: np.ndarray,
        normalization: str = "linear",
        percentiles: Tuple[float, float] = (1.0, 99.0),
        bit_depth: Optional[int] = None,
    ):
        """將輸入影像轉成 8-bit grayscale，回傳 (gray8, original_dtype, norm_method)。"""
        img = RawImage._to_grayscale(img)
        original_dtype = str(img.dtype)

        if img.dtype == np.uint8:
            return img.copy(), original_dtype, "uint8-copy"

        if img.dtype == np.uint16:
            if normalization == "percentile":
                gray8, method = RawImage._percentile_stretch(img, percentiles)
                return gray8, original_dtype, method
            resolved_bit_depth = RawImage._resolve_bit_depth(img, bit_depth)
            assert resolved_bit_depth is not None
            full_scale = (1 << resolved_bit_depth) - 1
            gray8 = (img.astype(np.float32) / full_scale * 255.0).clip(0, 255).astype(np.uint8)
            if resolved_bit_depth == 16:
                return gray8, original_dtype, "16bit-linear(÷257)"
            return gray8, original_dtype, f"{resolved_bit_depth}bit-linear"

        # 其他型別（float 等）：min-max 拉伸
        arr: np.ndarray = img.astype(np.float32)
        mn, mx = float(np.nanmin(arr)), float(np.nanmax(arr))
        if mx <= mn:
            return np.zeros_like(arr, dtype=np.uint8), original_dtype, "zeros(常數影像)"
        gray8 = ((arr - mn) / (mx - mn) * 255.0).clip(0, 255).astype(np.uint8)
        return gray8, original_dtype, "float-minmax"

    @staticmethod
    def _to_grayscale(img: np.ndarray) -> np.ndarray:
        if img.ndim == 2:
            return img.copy()
        if img.ndim != 3 or img.shape[2] not in (3, 4):
            raise ValueError(f"不支援的影像 shape：{img.shape}")
        if img.shape[2] == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _infer_bit_depth(img: np.ndarray) -> Optional[int]:
        if img.dtype == np.uint8:
            return 8
        if img.dtype == np.uint16:
            return 16
        return None

    @staticmethod
    def _resolve_bit_depth(img: np.ndarray, bit_depth: Optional[int]) -> Optional[int]:
        inferred = RawImage._infer_bit_depth(img)
        if bit_depth is None:
            return inferred
        if bit_depth not in (8, 10, 12, 14, 16):
            raise ValueError("bit_depth 僅支援 8、10、12、14、16")
        if inferred == 8 and bit_depth != 8:
            raise ValueError("uint8 影像的 bit_depth 必須是 8")
        if inferred == 16 and bit_depth == 8:
            raise ValueError("uint16 容器不得宣告為 8-bit")
        if inferred is None:
            raise ValueError("float/其他 dtype 不得僅靠 bit_depth 宣告正式整數量測平面")
        max_value = int(np.max(img)) if img.size else 0
        if max_value > (1 << bit_depth) - 1:
            raise ValueError(f"影像值 {max_value} 超過宣告的 {bit_depth}-bit Full Scale")
        return bit_depth

    @property
    def preview_is_transformed(self) -> bool:
        """preview 是否經非線性/資料相依拉伸；不影響 raw_gray。"""
        return "percentile" in self.norm_method or "minmax" in self.norm_method

    def require_full_scale(self) -> int:
        if self.full_scale is None:
            raise MeasurementPlaneError(
                f"dtype={self.original_dtype} 缺少可驗證的整數 bit depth，不能計算 %FS"
            )
        return self.full_scale

    def percent_of_full_scale(self, values: Optional[np.ndarray] = None) -> np.ndarray:
        """把原始量測值轉成 %FS；預設使用整張 raw_gray。"""
        full_scale = self.require_full_scale()
        source = self.raw_gray if values is None else values
        return source.astype(np.float64) / full_scale * 100.0

    def threshold_at_percent_fs(self, percent: float) -> float:
        if not 0.0 <= percent <= 100.0:
            raise ValueError("percent 必須介於 0 與 100")
        return self.require_full_scale() * percent / 100.0

    @staticmethod
    def _percentile_stretch(img: np.ndarray, percentiles: Tuple[float, float]):
        """依低/高百分位把影像拉伸到 0~255。"""
        lo_pct, hi_pct = percentiles
        arr: np.ndarray = img.astype(np.float32)
        lo = float(np.percentile(arr, lo_pct))
        hi = float(np.percentile(arr, hi_pct))
        method = f"16bit-percentile({lo_pct:g}-{hi_pct:g})"
        if hi <= lo:  # 動態範圍為 0，退回線性避免除以 0
            return (arr / 257.0).clip(0, 255).astype(np.uint8), method + "→linear"
        gray8 = ((arr - lo) / (hi - lo) * 255.0).clip(0, 255).astype(np.uint8)
        return gray8, method

    def analysis_sample(self, max_pixels: int = 8_000_000):
        """大圖不整張做重運算，避免 16K x 12K 卡住。

        用等距取樣做驗收指標，足夠做初步判斷。
        回傳 (sample, step)。
        """
        h, w = self.gray8.shape[:2]
        total = h * w
        if total <= max_pixels:
            return self.gray8, 1
        step = int(math.ceil(math.sqrt(total / max_pixels)))
        return self.gray8[::step, ::step], step

    def measurement_sample(self, max_pixels: int = 8_000_000):
        """從原始量測平面取樣；回傳值仍保持原始 dtype/尺度。"""
        h, w = self.raw_gray.shape[:2]
        total = h * w
        if total <= max_pixels:
            return self.raw_gray, 1
        step = int(math.ceil(math.sqrt(total / max_pixels)))
        return self.raw_gray[::step, ::step], step

    def sample_box_to_original(
        self, box: Tuple[int, int, int, int], step: int
    ) -> Tuple[int, int, int, int]:
        """把取樣影像的 (x, y, width, height) 框回推並裁切到原圖。"""
        if step < 1:
            raise ValueError("step 必須 ≥ 1")
        x, y, width, height = box
        x1 = max(0, min(self.width, x * step))
        y1 = max(0, min(self.height, y * step))
        x2 = max(x1, min(self.width, (x + width) * step))
        y2 = max(y1, min(self.height, (y + height) * step))
        return x1, y1, x2 - x1, y2 - y1
