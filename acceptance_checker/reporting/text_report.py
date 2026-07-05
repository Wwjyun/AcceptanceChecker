# -*- coding: utf-8 -*-
"""人類可讀的文字驗收報告。"""

from __future__ import annotations

from typing import List, Optional

from ..core.config import Thresholds
from ..core.metrics import Metrics
from .recommendations import RecommendationBuilder


class ReportBuilder:
    """把 Metrics 組成人類可讀的文字報告。"""

    STATUS_NOTE = {
        "PASS": "通過：目前量測值未觸發主要風險門檻，可進入後續 AOI recipe 驗證。",
        "WARNING": "警告：未達 FAIL，但已有指標接近風險區，量產前建議確認穩定性。",
        "FAIL": "不合格：至少一項關鍵指標越過 FAIL 門檻，建議先修正成像條件再調整軟體。",
    }

    def __init__(self, recommendation_builder: RecommendationBuilder | None = None):
        self.recommendation_builder = recommendation_builder or RecommendationBuilder()

    def build(self, m: Metrics, thresholds: Optional[Thresholds] = None) -> str:
        t = thresholds or Thresholds()
        note = self.STATUS_NOTE.get(m.overall_status, "")
        judgement = self._judgement_explanation(m, t)
        metric_notes = self._metric_notes(m, t)
        recommendations = self.recommendation_builder.build(m, t)
        report = f"""
【總判定】
狀態：{m.overall_status}
說明：{note}

【檔案資訊】
檔名：{m.file_name}
路徑：{m.file_path}
尺寸：{m.width_px} x {m.height_px} px
原始 dtype：{m.dtype}
正規化方式：{m.norm_method}
分析取樣 step：{m.analysis_step}

【整體灰階】
平均灰階：{m.mean_gray:.2f}
標準差：{m.std_gray:.2f}
最小/最大：{m.min_gray:.1f} / {m.max_gray:.1f}
P01 / P99：{m.p01_gray:.1f} / {m.p99_gray:.1f}
P99-P01 灰階展開：{m.hist_spread_p99_p01:.1f}
低灰階 clipping：{m.low_clip_pct:.4f} %
高灰階 clipping：{m.high_clip_pct:.4f} %

【700 mm 寬度分區均勻性】
左側 20% mean：{m.zone_1_left_mean:.2f}
左中 20% mean：{m.zone_2_left_mid_mean:.2f}
中間 20% mean：{m.zone_3_center_mean:.2f}
右中 20% mean：{m.zone_4_right_mid_mean:.2f}
右側 20% mean：{m.zone_5_right_mean:.2f}
均勻性 min/max：{m.uniformity_ratio:.3f}

【缺陷可分離性，自動估算】
自動候選缺陷數：{m.auto_defect_count}
最佳候選 CNR：{m.auto_defect_cnr_est:.3f}
最佳候選 contrast：{m.auto_defect_contrast_est:.3f}
最佳候選 sampled area：{m.auto_defect_area_px_sampled}
robust noise sigma：{m.robust_noise_sigma:.3f}
整體 SNR：{m.signal_to_noise_ratio:.3f}

【背景與條紋風險】
背景 std proxy：{m.bg_std_est:.3f}
vertical stripe score：{m.vertical_stripe_score:.3f}
horizontal stripe score：{m.horizontal_stripe_score:.3f}

【清晰度 / 對焦 proxy】
Laplacian variance：{m.sharpness_laplacian_var:.3f}

【FAIL 原因】
{m.fail_reasons if m.fail_reasons else "無"}

【WARNING 原因】
{m.warn_reasons if m.warn_reasons else "無"}

【判讀說明】
{judgement}

【逐項指標解讀】
{metric_notes}

【建議處置】
{recommendations}
"""
        return report.strip()

    def thresholds_hint(self, t: Thresholds) -> str:
        """回傳門檻摘要，供 UI 初始顯示。"""
        return (
            "預設判斷門檻：\n"
            f"- 平均灰階 < {t.mean_gray_fail}：FAIL；< {t.mean_gray_warn}：WARNING\n"
            f"- 均勻性 min/max < {t.uniformity_fail}：FAIL；< {t.uniformity_warn}：WARNING\n"
            f"- clipping > {t.clipping_fail_pct}%：FAIL；> {t.clipping_warn_pct}%：WARNING\n"
            f"- CNR < {t.cnr_fail}：FAIL；< {t.cnr_warn}：WARNING\n"
            f"- SNR < {t.snr_fail}：FAIL；< {t.snr_warn}：WARNING\n"
            f"- 背景 std > {t.bg_std_fail}：FAIL；> {t.bg_std_warn}：WARNING\n"
            f"- 清晰度 Laplacian Var < {t.sharpness_fail}：FAIL；"
            f"< {t.sharpness_warn}：WARNING\n"
            f"- 灰階展開 P99-P01 < {t.hist_spread_fail}：FAIL；"
            f"< {t.hist_spread_warn}：WARNING\n"
            "\n判定邏輯：任一 FAIL 項目會讓總判定成為 FAIL；沒有 FAIL 但有 WARNING "
            "項目則為 WARNING；全部指標都未觸發才是 PASS。\n"
            "注意：CNR 是自動估算。NG 圖建議後續用人工 ROI 量測確認缺陷與背景分離度。"
        )

    def _judgement_explanation(self, m: Metrics, t: Thresholds) -> str:
        fail_items = self._split_reasons(m.fail_reasons)
        warn_items = self._split_reasons(m.warn_reasons)
        lines: List[str] = [
            "判定邏輯：任一 FAIL 門檻觸發即列為 FAIL；沒有 FAIL 但有 WARNING "
            "項目時列為 WARNING；全部未觸發才列為 PASS。",
        ]

        if m.overall_status == "FAIL":
            lines.append(
                "本次結果為 FAIL，代表目前影像品質已有項目低於可接受下限，"
                "不建議只靠後段 AOI recipe 補償。"
            )
        elif m.overall_status == "WARNING":
            lines.append(
                "本次結果為 WARNING，代表影像仍可能可用，但穩定度或安全裕度不足，"
                "建議用更多 OK/NG 樣本確認誤判與漏判風險。"
            )
        elif m.overall_status == "PASS":
            lines.append(
                "本次結果為 PASS，代表目前量測值都在設定門檻內；仍建議搭配實際 OK/NG "
                "樣本確認 recipe 視窗。"
            )

        lines.append(f"FAIL 項目：{self._format_reason_items(fail_items)}")
        lines.append(f"WARNING 項目：{self._format_reason_items(warn_items)}")
        lines.append(
            "目前使用門檻："
            f"平均灰階 FAIL<{t.mean_gray_fail}/WARNING<{t.mean_gray_warn}；"
            f"均勻性 FAIL<{t.uniformity_fail}/WARNING<{t.uniformity_warn}；"
            f"clipping FAIL>{t.clipping_fail_pct}%/WARNING>{t.clipping_warn_pct}%；"
            f"CNR FAIL<{t.cnr_fail}/WARNING<{t.cnr_warn}；"
            f"SNR FAIL<{t.snr_fail}/WARNING<{t.snr_warn}；"
            f"背景 std FAIL>{t.bg_std_fail}/WARNING>{t.bg_std_warn}；"
            f"清晰度 FAIL<{t.sharpness_fail}/WARNING<{t.sharpness_warn}；"
            f"灰階展開 FAIL<{t.hist_spread_fail}/WARNING<{t.hist_spread_warn}。"
        )
        return "\n".join(lines)

    def _metric_notes(self, m: Metrics, t: Thresholds) -> str:
        low_clip_state = self._upper_limit_state(
            m.low_clip_pct, t.clipping_warn_pct, t.clipping_fail_pct
        )
        high_clip_state = self._upper_limit_state(
            m.high_clip_pct, t.clipping_warn_pct, t.clipping_fail_pct
        )
        cnr_note = (
            "未找到候選缺陷，因此 CNR 不能證明 NG 缺陷可被穩定分離；"
            "若此圖應為 OK，這通常不是問題。"
            if m.auto_defect_count == 0
            else f"最佳候選 CNR 為 {m.auto_defect_cnr_est:.2f}，"
            "代表候選缺陷相對背景雜訊的可分離程度。"
        )
        lines = [
            self._lower_limit_note(
                "平均灰階",
                m.mean_gray,
                t.mean_gray_warn,
                t.mean_gray_fail,
                "過低時代表進光量不足，後續拉亮會同步放大雜訊。",
            ),
            self._lower_limit_note(
                "均勻性 min/max",
                m.uniformity_ratio,
                t.uniformity_warn,
                t.uniformity_fail,
                "越接近 1 代表左右分區越一致；太低會讓固定門檻在不同位置表現不一致。",
            ),
            (
                f"低灰階 clipping：{m.low_clip_pct:.4f}%（{low_clip_state}）。"
                "數值偏高代表暗部資訊被壓到 0 附近，暗缺陷或背景差異可能消失。"
            ),
            (
                f"高灰階 clipping：{m.high_clip_pct:.4f}%（{high_clip_state}）。"
                "數值偏高代表亮部過曝，亮缺陷或材質差異可能被截斷。"
            ),
            self._lower_limit_note(
                "P99-P01 灰階展開",
                m.hist_spread_p99_p01,
                t.hist_spread_warn,
                t.hist_spread_fail,
                "太窄代表有效灰階動態範圍不足，OK/NG 差異會更難切開。",
            ),
            f"CNR：{cnr_note}",
            self._lower_limit_note(
                "整體 SNR",
                m.signal_to_noise_ratio,
                t.snr_warn,
                t.snr_fail,
                "代表平均灰階相對 robust noise sigma 的安全裕度；太低時整體訊號會被雜訊吃掉。",
            ),
            self._upper_limit_note(
                "背景 std proxy",
                m.bg_std_est,
                t.bg_std_warn,
                t.bg_std_fail,
                "越高代表背景紋理或雜訊越強，容易增加誤判。",
            ),
            self._lower_limit_note(
                "清晰度 Laplacian Var",
                m.sharpness_laplacian_var,
                t.sharpness_warn,
                t.sharpness_fail,
                "偏低時可能是對焦、震動或運動模糊，細小缺陷會被抹平。",
            ),
        ]
        return "\n".join(f"- {line}" for line in lines)

    def _split_reasons(self, text: str) -> List[str]:
        return [item.strip() for item in text.split("；") if item.strip()]

    def _format_reason_items(self, items: List[str]) -> str:
        if not items:
            return "無"
        return "；".join(items)

    def _lower_limit_note(
        self, label: str, value: float, warn_limit: float, fail_limit: float, detail: str
    ) -> str:
        state = self._lower_limit_state(value, warn_limit, fail_limit)
        return (
            f"{label}：{value:.3f}（{state}；FAIL<{fail_limit}，WARNING<{warn_limit}）。"
            f"{detail}"
        )

    def _upper_limit_note(
        self, label: str, value: float, warn_limit: float, fail_limit: float, detail: str
    ) -> str:
        state = self._upper_limit_state(value, warn_limit, fail_limit)
        return (
            f"{label}：{value:.3f}（{state}；FAIL>{fail_limit}，WARNING>{warn_limit}）。"
            f"{detail}"
        )

    def _lower_limit_state(self, value: float, warn_limit: float, fail_limit: float) -> str:
        if value < fail_limit:
            return "FAIL 區"
        if value < warn_limit:
            return "WARNING 區"
        return "通過區"

    def _upper_limit_state(self, value: float, warn_limit: float, fail_limit: float) -> str:
        if value > fail_limit:
            return "FAIL 區"
        if value > warn_limit:
            return "WARNING 區"
        return "通過區"
