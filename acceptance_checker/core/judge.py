# -*- coding: utf-8 -*-
"""依門檻對 Metrics 做 100 分加權判定。"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .config import Thresholds
from .metrics import Metrics


class AcceptanceJudge:
    """把計算好的 Metrics 依 Thresholds 轉成加權總分與 PASS / WARNING / FAIL。"""

    SCORE_WEIGHTS: Dict[str, float] = {
        "平均灰階": 15.0,
        "均勻性": 15.0,
        "低灰階 clipping": 10.0,
        "高灰階 clipping": 10.0,
        "灰階展開": 10.0,
        "CNR": 20.0,
        "SNR": 10.0,
        "背景 std": 5.0,
        "清晰度": 5.0,
    }
    PASS_SCORE = 80.0
    WARNING_SCORE = 60.0

    def __init__(self, thresholds: Thresholds | None = None):
        self.thresholds = thresholds or Thresholds()

    def judge(self, m: Metrics) -> Metrics:
        """就地更新 m 的 score/status/reasons 並回傳。"""
        t = self.thresholds
        fail: List[str] = []
        warn: List[str] = []
        score_items: List[Tuple[str, float, float]] = []

        if m.mean_gray < t.mean_gray_fail:
            fail.append(f"平均灰階過低：{m.mean_gray:.1f} < {t.mean_gray_fail}")
            self._add_score(score_items, "平均灰階", "fail")
        elif m.mean_gray < t.mean_gray_warn:
            warn.append(f"平均灰階偏低：{m.mean_gray:.1f} < {t.mean_gray_warn}")
            self._add_score(score_items, "平均灰階", "warn")
        else:
            self._add_score(score_items, "平均灰階", "pass")

        if m.uniformity_ratio < t.uniformity_fail:
            fail.append(f"左右/分區均勻性不合格：{m.uniformity_ratio:.2f} < {t.uniformity_fail}")
            self._add_score(score_items, "均勻性", "fail")
        elif m.uniformity_ratio < t.uniformity_warn:
            warn.append(f"左右/分區均勻性偏低：{m.uniformity_ratio:.2f} < {t.uniformity_warn}")
            self._add_score(score_items, "均勻性", "warn")
        else:
            self._add_score(score_items, "均勻性", "pass")

        if m.low_clip_pct > t.clipping_fail_pct:
            fail.append(f"低灰階 clipping 過高：{m.low_clip_pct:.2f}% > {t.clipping_fail_pct}%")
            self._add_score(score_items, "低灰階 clipping", "fail")
        elif m.low_clip_pct > t.clipping_warn_pct:
            warn.append(f"低灰階 clipping 偏高：{m.low_clip_pct:.2f}% > {t.clipping_warn_pct}%")
            self._add_score(score_items, "低灰階 clipping", "warn")
        else:
            self._add_score(score_items, "低灰階 clipping", "pass")

        if m.high_clip_pct > t.clipping_fail_pct:
            fail.append(f"高灰階 clipping 過高：{m.high_clip_pct:.2f}% > {t.clipping_fail_pct}%")
            self._add_score(score_items, "高灰階 clipping", "fail")
        elif m.high_clip_pct > t.clipping_warn_pct:
            warn.append(f"高灰階 clipping 偏高：{m.high_clip_pct:.2f}% > {t.clipping_warn_pct}%")
            self._add_score(score_items, "高灰階 clipping", "warn")
        else:
            self._add_score(score_items, "高灰階 clipping", "pass")

        if m.hist_spread_p99_p01 < t.hist_spread_fail:
            fail.append(f"灰階分布太窄：P99-P01={m.hist_spread_p99_p01:.1f} < {t.hist_spread_fail}")
            self._add_score(score_items, "灰階展開", "fail")
        elif m.hist_spread_p99_p01 < t.hist_spread_warn:
            warn.append(f"灰階分布偏窄：P99-P01={m.hist_spread_p99_p01:.1f} < {t.hist_spread_warn}")
            self._add_score(score_items, "灰階展開", "warn")
        else:
            self._add_score(score_items, "灰階展開", "pass")

        if m.auto_defect_count > 0:
            if m.auto_defect_cnr_est < t.cnr_fail:
                fail.append(f"自動估算缺陷 CNR 過低：{m.auto_defect_cnr_est:.2f} < {t.cnr_fail}")
                self._add_score(score_items, "CNR", "fail")
            elif m.auto_defect_cnr_est < t.cnr_warn:
                warn.append(f"自動估算缺陷 CNR 偏低：{m.auto_defect_cnr_est:.2f} < {t.cnr_warn}")
                self._add_score(score_items, "CNR", "warn")
            else:
                self._add_score(score_items, "CNR", "pass")
        else:
            warn.append("未找到明顯異常候選區；若這是 NG 圖，代表缺陷訊號可能不足")
            self._add_score(score_items, "CNR", "warn")

        if m.signal_to_noise_ratio < t.snr_fail:
            fail.append(f"整體 SNR 過低：{m.signal_to_noise_ratio:.2f} < {t.snr_fail}")
            self._add_score(score_items, "SNR", "fail")
        elif m.signal_to_noise_ratio < t.snr_warn:
            warn.append(f"整體 SNR 偏低：{m.signal_to_noise_ratio:.2f} < {t.snr_warn}")
            self._add_score(score_items, "SNR", "warn")
        else:
            self._add_score(score_items, "SNR", "pass")

        if m.bg_std_est > t.bg_std_fail:
            fail.append(f"背景 std / 紋理偏高：{m.bg_std_est:.2f} > {t.bg_std_fail}")
            self._add_score(score_items, "背景 std", "fail")
        elif m.bg_std_est > t.bg_std_warn:
            warn.append(f"背景 std / 紋理偏高：{m.bg_std_est:.2f} > {t.bg_std_warn}")
            self._add_score(score_items, "背景 std", "warn")
        else:
            self._add_score(score_items, "背景 std", "pass")

        if m.sharpness_laplacian_var < t.sharpness_fail:
            fail.append(f"清晰度 proxy 過低：Laplacian Var={m.sharpness_laplacian_var:.1f}")
            self._add_score(score_items, "清晰度", "fail")
        elif m.sharpness_laplacian_var < t.sharpness_warn:
            warn.append(f"清晰度 proxy 偏低：Laplacian Var={m.sharpness_laplacian_var:.1f}")
            self._add_score(score_items, "清晰度", "warn")
        else:
            self._add_score(score_items, "清晰度", "pass")

        m.quality_score = round(sum(points for _, points, _ in score_items), 1)
        m.score_breakdown = "；".join(
            f"{name} {points:g}/{weight:g}" for name, points, weight in score_items
        )
        if m.quality_score >= self.PASS_SCORE:
            m.overall_status = "PASS"
        elif m.quality_score >= self.WARNING_SCORE:
            m.overall_status = "WARNING"
        else:
            m.overall_status = "FAIL"

        m.fail_reasons = "；".join(fail)
        m.warn_reasons = "；".join(warn)
        return m

    def _add_score(
        self, score_items: List[Tuple[str, float, float]], label: str, state: str
    ) -> None:
        weight = self.SCORE_WEIGHTS[label]
        if state == "pass":
            points = weight
        elif state == "warn":
            points = weight * 0.5
        else:
            points = 0.0
        score_items.append((label, points, weight))
