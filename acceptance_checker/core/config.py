# -*- coding: utf-8 -*-
"""判斷門檻設定。可依現場標準調整，並可存/讀 JSON 設定檔。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict


@dataclass
class Thresholds:
    """驗收判斷門檻（8-bit 尺度 0~255）。

    每個欄位都可在建立物件時覆寫，例如：
        Thresholds(mean_gray_fail=25, cnr_warn=4.0)

    也可透過 JSON 設定檔載入/存檔（見 load_json / save_json），
    讓現場人員不改程式即可調門檻。
    """

    # 平均灰階
    mean_gray_fail: float = 30.0
    mean_gray_warn: float = 50.0

    # 分區均勻性 min zone mean / max zone mean
    uniformity_fail: float = 0.50
    uniformity_warn: float = 0.70
    uniformity_good: float = 0.85

    # clipping 百分比（低灰階 / 高灰階）
    clipping_fail_pct: float = 1.0
    clipping_warn_pct: float = 0.1

    # 缺陷/背景 contrast-to-noise ratio
    cnr_fail: float = 3.0
    cnr_warn: float = 5.0

    # 全圖 signal-to-noise ratio，使用平均灰階 / robust noise sigma
    snr_fail: float = 10.0
    snr_warn: float = 20.0

    # 背景 std（8-bit）
    bg_std_warn: float = 6.0
    bg_std_fail: float = 10.0

    # Laplacian variance，僅為粗略清晰度 proxy，場景相依，主要用於比較
    sharpness_fail: float = 20.0
    sharpness_warn: float = 50.0

    # 灰階展開 P99-P01
    hist_spread_fail: float = 15.0
    hist_spread_warn: float = 30.0

    # ---------- JSON 設定檔 ----------

    def to_dict(self) -> Dict[str, float]:
        """轉成可 JSON 序列化的 dict。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Thresholds":
        """由 dict 建立；忽略未知欄位、缺欄位沿用預設值。

        未知欄位在此忽略而非報錯，讓舊/新版設定檔可互通；
        欄位型別一律轉 float，字串或整數皆可接受。
        """
        known = {f.name for f in fields(cls)}
        kwargs: Dict[str, float] = {}
        for key, value in data.items():
            if key not in known:
                continue
            try:
                kwargs[key] = float(value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"門檻欄位 {key!r} 不是數值：{value!r}") from e
        return cls(**kwargs)

    def save_json(self, path: str) -> None:
        """存成 JSON 設定檔（UTF-8，含縮排）。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2, sort_keys=True)

    @classmethod
    def load_json(cls, path: str) -> "Thresholds":
        """從 JSON 設定檔載入門檻。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("門檻設定檔內容必須是 JSON 物件（key-value）")
        return cls.from_dict(data)
