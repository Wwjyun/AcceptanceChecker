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


class RawImage:
    """封裝一張 raw image 的載入、灰階正規化與取樣。

    典型用法：
        raw = RawImage.load("foo.bmp")
        sample, step = raw.analysis_sample()
    """

    def __init__(self, gray8: np.ndarray, original_dtype: str, norm_method: str = "uint8-copy"):
        self.gray8 = gray8
        self.original_dtype = original_dtype
        self.norm_method = norm_method

    @property
    def height(self) -> int:
        return int(self.gray8.shape[0])

    @property
    def width(self) -> int:
        return int(self.gray8.shape[1])

    @classmethod
    def load(
        cls,
        file_path: str,
        normalization: str = "linear",
        percentiles: Tuple[float, float] = (1.0, 99.0),
    ) -> "RawImage":
        """讀圖並轉成 8-bit grayscale。讀圖失敗會丟出 RuntimeError。

        normalization 僅影響 16-bit 影像：
        - "linear"     : 0~65535 線性縮到 0~255（÷257）。感測器實際只用低位元時對比會被壓縮。
        - "percentile" : 依 percentiles=(low, high) 百分位拉伸，改善低動態範圍影像的可視/可分性。
        """
        img = imread_unicode(file_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"讀圖失敗：{file_path}")
        gray8, original_dtype, norm_method = cls._normalize_to_8bit(
            img, normalization, percentiles
        )
        return cls(gray8, original_dtype, norm_method)

    @staticmethod
    def _normalize_to_8bit(
        img: np.ndarray,
        normalization: str = "linear",
        percentiles: Tuple[float, float] = (1.0, 99.0),
    ):
        """將輸入影像轉成 8-bit grayscale，回傳 (gray8, original_dtype, norm_method)。"""
        original_dtype = str(img.dtype)

        if img.ndim == 3:
            if img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if img.dtype == np.uint8:
            return img.copy(), original_dtype, "uint8-copy"

        if img.dtype == np.uint16:
            if normalization == "percentile":
                gray8, method = RawImage._percentile_stretch(img, percentiles)
                return gray8, original_dtype, method
            gray8 = (img.astype(np.float32) / 257.0).clip(0, 255).astype(np.uint8)
            return gray8, original_dtype, "16bit-linear(÷257)"

        # 其他型別（float 等）：min-max 拉伸
        arr = img.astype(np.float32)
        mn, mx = float(np.nanmin(arr)), float(np.nanmax(arr))
        if mx <= mn:
            return np.zeros_like(arr, dtype=np.uint8), original_dtype, "zeros(常數影像)"
        gray8 = ((arr - mn) / (mx - mn) * 255.0).clip(0, 255).astype(np.uint8)
        return gray8, original_dtype, "float-minmax"

    @staticmethod
    def _percentile_stretch(img: np.ndarray, percentiles: Tuple[float, float]):
        """依低/高百分位把影像拉伸到 0~255。"""
        lo_pct, hi_pct = percentiles
        arr = img.astype(np.float32)
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
