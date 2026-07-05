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
            fail.append(
                f"曝光裕度風險：平均灰階 {m.mean_gray:.1f} < {t.mean_gray_fail}，"
                "量產時暗部缺陷與背景差異可能被雜訊壓低"
            )
            self._add_score(score_items, "平均灰階", "fail")
        elif m.mean_gray < t.mean_gray_warn:
            warn.append(
                f"曝光裕度觀察：平均灰階 {m.mean_gray:.1f} < {t.mean_gray_warn}，"
                "建議確認光源衰減與曝光批間變動"
            )
            self._add_score(score_items, "平均灰階", "warn")
        else:
            self._add_score(score_items, "平均灰階", "pass")

        if m.uniformity_ratio < t.uniformity_fail:
            fail.append(
                f"視野均勻性風險：min/max={m.uniformity_ratio:.2f} < {t.uniformity_fail}，"
                "量產固定門檻在左右位置可能產生誤判差異"
            )
            self._add_score(score_items, "均勻性", "fail")
        elif m.uniformity_ratio < t.uniformity_warn:
            warn.append(
                f"視野均勻性觀察：min/max={m.uniformity_ratio:.2f} < {t.uniformity_warn}，"
                "建議確認光源平行度與治具高度穩定性"
            )
            self._add_score(score_items, "均勻性", "warn")
        else:
            self._add_score(score_items, "均勻性", "pass")

        if m.low_clip_pct > t.clipping_fail_pct:
            fail.append(
                f"暗部資訊截斷風險：低灰階 clipping {m.low_clip_pct:.2f}% > "
                f"{t.clipping_fail_pct}%，量產時暗缺陷訊號可能被壓平"
            )
            self._add_score(score_items, "低灰階 clipping", "fail")
        elif m.low_clip_pct > t.clipping_warn_pct:
            warn.append(
                f"暗部資訊截斷觀察：低灰階 clipping {m.low_clip_pct:.2f}% > "
                f"{t.clipping_warn_pct}%，建議確認黑位與曝光設定"
            )
            self._add_score(score_items, "低灰階 clipping", "warn")
        else:
            self._add_score(score_items, "低灰階 clipping", "pass")

        if m.high_clip_pct > t.clipping_fail_pct:
            fail.append(
                f"亮部資訊截斷風險：高灰階 clipping {m.high_clip_pct:.2f}% > "
                f"{t.clipping_fail_pct}%，量產時亮缺陷或反光差異可能被截斷"
            )
            self._add_score(score_items, "高灰階 clipping", "fail")
        elif m.high_clip_pct > t.clipping_warn_pct:
            warn.append(
                f"亮部資訊截斷觀察：高灰階 clipping {m.high_clip_pct:.2f}% > "
                f"{t.clipping_warn_pct}%，建議確認曝光與光源峰值"
            )
            self._add_score(score_items, "高灰階 clipping", "warn")
        else:
            self._add_score(score_items, "高灰階 clipping", "pass")

        if m.hist_spread_p99_p01 < t.hist_spread_fail:
            fail.append(
                f"灰階動態範圍風險：P99-P01={m.hist_spread_p99_p01:.1f} < "
                f"{t.hist_spread_fail}，OK/NG 灰階窗口可能過窄"
            )
            self._add_score(score_items, "灰階展開", "fail")
        elif m.hist_spread_p99_p01 < t.hist_spread_warn:
            warn.append(
                f"灰階動態範圍觀察：P99-P01={m.hist_spread_p99_p01:.1f} < "
                f"{t.hist_spread_warn}，建議確認 16-bit 正規化與打光對比"
            )
            self._add_score(score_items, "灰階展開", "warn")
        else:
            self._add_score(score_items, "灰階展開", "pass")

        if m.auto_defect_count > 0:
            if m.auto_defect_cnr_est < t.cnr_fail:
                fail.append(
                    f"缺陷分離度風險：自動 CNR {m.auto_defect_cnr_est:.2f} < {t.cnr_fail}，"
                    "量產時缺陷與背景雜訊可能重疊"
                )
                self._add_score(score_items, "CNR", "fail")
            elif m.auto_defect_cnr_est < t.cnr_warn:
                warn.append(
                    f"缺陷分離度觀察：自動 CNR {m.auto_defect_cnr_est:.2f} < {t.cnr_warn}，"
                    "建議用人工 ROI 與實際 OK/NG 樣本確認 recipe 窗口"
                )
                self._add_score(score_items, "CNR", "warn")
            else:
                self._add_score(score_items, "CNR", "pass")
        else:
            warn.append(
                "缺陷候選覆蓋率觀察：未找到明顯自動候選區；若此圖為量產 NG 樣本，"
                "建議用人工 ROI 確認缺陷訊號是否足以建立穩定 recipe"
            )
            self._add_score(score_items, "CNR", "warn")

        if m.signal_to_noise_ratio < t.snr_fail:
            fail.append(
                f"訊雜比風險：整體 SNR {m.signal_to_noise_ratio:.2f} < {t.snr_fail}，"
                "量產時製程微小差異可能被雜訊淹沒"
            )
            self._add_score(score_items, "SNR", "fail")
        elif m.signal_to_noise_ratio < t.snr_warn:
            warn.append(
                f"訊雜比觀察：整體 SNR {m.signal_to_noise_ratio:.2f} < {t.snr_warn}，"
                "建議確認 gain、光源穩定度與環境遮光"
            )
            self._add_score(score_items, "SNR", "warn")
        else:
            self._add_score(score_items, "SNR", "pass")

        if m.bg_std_est > t.bg_std_fail:
            fail.append(
                f"背景雜訊風險：背景 std {m.bg_std_est:.2f} > {t.bg_std_fail}，"
                "量產時背景紋理可能提高誤判率"
            )
            self._add_score(score_items, "背景 std", "fail")
        elif m.bg_std_est > t.bg_std_warn:
            warn.append(
                f"背景雜訊觀察：背景 std {m.bg_std_est:.2f} > {t.bg_std_warn}，"
                "建議確認材料反光、光源頻閃與治具震動"
            )
            self._add_score(score_items, "背景 std", "warn")
        else:
            self._add_score(score_items, "背景 std", "pass")

        if m.sharpness_laplacian_var < t.sharpness_fail:
            fail.append(
                f"成像清晰度風險：Laplacian Var={m.sharpness_laplacian_var:.1f} < "
                f"{t.sharpness_fail}，量產時細小缺陷邊緣可能不穩定"
            )
            self._add_score(score_items, "清晰度", "fail")
        elif m.sharpness_laplacian_var < t.sharpness_warn:
            warn.append(
                f"成像清晰度觀察：Laplacian Var={m.sharpness_laplacian_var:.1f} < "
                f"{t.sharpness_warn}，建議確認對焦、景深與線上震動"
            )
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
        m.risk_level = self._risk_level(m.overall_status)

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

    def _risk_level(self, status: str) -> str:
        labels = {
            "PASS": "量產風險低",
            "WARNING": "量產觀察項",
            "FAIL": "量產導入風險高",
        }
        return labels.get(status, status)
