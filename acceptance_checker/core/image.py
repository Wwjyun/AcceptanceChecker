# -*- coding: utf-8 -*-
"""影像載入與前處理。"""

from __future__ import annotations

import math

import cv2
import numpy as np


class RawImage:
    """封裝一張 raw image 的載入、灰階正規化與取樣。

    典型用法：
        raw = RawImage.load("foo.bmp")
        sample, step = raw.analysis_sample()
    """

    def __init__(self, gray8: np.ndarray, original_dtype: str):
        self.gray8 = gray8
        self.original_dtype = original_dtype

    @property
    def height(self) -> int:
        return int(self.gray8.shape[0])

    @property
    def width(self) -> int:
        return int(self.gray8.shape[1])

    @classmethod
    def load(cls, file_path: str) -> "RawImage":
        """讀圖並轉成 8-bit grayscale。讀圖失敗會丟出 RuntimeError。"""
        img = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"讀圖失敗：{file_path}")
        gray8, original_dtype = cls._normalize_to_8bit(img)
        return cls(gray8, original_dtype)

    @staticmethod
    def _normalize_to_8bit(img: np.ndarray):
        """將輸入影像轉成 8-bit grayscale。

        注意：若原圖是 16-bit，本工具會用 0~65535 線性縮到 0~255。
        """
        original_dtype = str(img.dtype)

        if img.ndim == 3:
            if img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if img.dtype == np.uint8:
            gray8 = img.copy()
        elif img.dtype == np.uint16:
            gray8 = (img.astype(np.float32) / 257.0).clip(0, 255).astype(np.uint8)
        else:
            arr = img.astype(np.float32)
            mn, mx = float(np.nanmin(arr)), float(np.nanmax(arr))
            if mx <= mn:
                gray8 = np.zeros_like(arr, dtype=np.uint8)
            else:
                gray8 = ((arr - mn) / (mx - mn) * 255.0).clip(0, 255).astype(np.uint8)

        return gray8, original_dtype

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
