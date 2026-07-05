# -*- coding: utf-8 -*-
"""判斷門檻設定。可依現場標準調整。"""

from dataclasses import dataclass


@dataclass
class Thresholds:
    """驗收判斷門檻（8-bit 尺度 0~255）。

    每個欄位都可在建立物件時覆寫，例如：
        Thresholds(mean_gray_fail=25, cnr_warn=4.0)
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

    # 背景 std（8-bit）
    bg_std_warn: float = 6.0
    bg_std_fail: float = 10.0

    # Laplacian variance，僅為粗略清晰度 proxy，場景相依，主要用於比較
    sharpness_fail: float = 20.0
    sharpness_warn: float = 50.0

    # 灰階展開 P99-P01
    hist_spread_fail: float = 15.0
    hist_spread_warn: float = 30.0
