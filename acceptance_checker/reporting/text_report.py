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
        "PASS": "量產風險低：加權總分達標，可進入後續 AOI recipe 驗證。",
        "WARNING": "量產觀察項：加權總分落在觀察區，建議補強穩定性確認。",
        "FAIL": "量產導入風險高：加權總分低於建議區間，建議先收斂成像條件。",
    }

    def __init__(self, recommendation_builder: RecommendationBuilder | None = None):
        self.recommendation_builder = recommendation_builder or RecommendationBuilder()

    def build(self, m: Metrics, thresholds: Optional[Thresholds] = None) -> str:
        t = thresholds or Thresholds()
        note = self.STATUS_NOTE.get(m.overall_status, "")
        risk_label = m.risk_level or self._risk_status_label(m.overall_status)
        judgement = self._judgement_explanation(m, t)
        metric_notes = self._metric_notes(m, t)
        recommendations = self.recommendation_builder.build(m, t)
        report = f"""
【量產風險總覽】
風險等級：{risk_label}
加權總分：{m.quality_score:.1f} / 100
加權明細：{m.score_breakdown if m.score_breakdown else "無"}
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
單張空間 SNR proxy：{m.signal_to_noise_ratio:.3f}（非正式時域 SNR）

【背景與條紋風險】
背景 std proxy：{m.bg_std_est:.3f}
vertical stripe score：{m.vertical_stripe_score:.3f}
horizontal stripe score：{m.horizontal_stripe_score:.3f}

【清晰度 / 對焦 proxy】
Laplacian variance：{m.sharpness_laplacian_var:.3f}

【高風險項目】
{m.fail_reasons if m.fail_reasons else "無"}

【觀察項目】
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
            f"- 平均灰階 < {t.mean_gray_fail}：高風險；< {t.mean_gray_warn}：觀察\n"
            f"- 均勻性 min/max < {t.uniformity_fail}：高風險；< {t.uniformity_warn}：觀察\n"
            f"- clipping > {t.clipping_fail_pct}%：高風險；> {t.clipping_warn_pct}%：觀察\n"
            f"- CNR < {t.cnr_fail}：高風險；< {t.cnr_warn}：觀察\n"
            f"- 單張空間 SNR proxy < {t.snr_fail}：高風險；"
            f"< {t.snr_warn}：觀察（正式時域 SNR 需 N≥30）\n"
            f"- 背景 std > {t.bg_std_fail}：高風險；> {t.bg_std_warn}：觀察\n"
            f"- 清晰度 Laplacian Var < {t.sharpness_fail}：高風險；"
            f"< {t.sharpness_warn}：觀察\n"
            f"- 灰階展開 P99-P01 < {t.hist_spread_fail}：高風險；"
            f"< {t.hist_spread_warn}：觀察\n"
            "\n加權邏輯：各項權重合計 100 分；低風險區拿滿分、觀察區拿半分、"
            "高風險區拿 0 分。總分 >= 80 為量產風險低，60-79.9 為量產觀察項，"
            "< 60 為量產導入風險高。\n"
            "注意：CNR 是自動估算。量產 NG 樣本建議後續用人工 ROI 量測確認缺陷與背景分離度。"
        )

    def _judgement_explanation(self, m: Metrics, t: Thresholds) -> str:
        fail_items = self._split_reasons(m.fail_reasons)
        warn_items = self._split_reasons(m.warn_reasons)
        lines: List[str] = [
            "判定邏輯：各項指標依權重加總為 100 分；低風險區拿滿分、觀察區拿半分、"
            "高風險區拿 0 分。總分 >= 80 為量產風險低，60-79.9 為量產觀察項，"
            "< 60 為量產導入風險高。",
        ]
        lines.append(f"加權總分：{m.quality_score:.1f} / 100")
        lines.append(f"加權明細：{m.score_breakdown if m.score_breakdown else '無'}")

        if m.overall_status == "FAIL" and m.risk_level == "量產導入風險極高":
            lines.append(
                "本次結果屬量產導入風險「極高」，加權總分遠低於建議區間，代表多項關鍵指標"
                "同時未達標，安全裕度非常薄。若仍需放行，建議優先處理【建議處置】中扣分最多的"
                "項目，並在放行紀錄中註明已知風險與原因。"
            )
        elif m.overall_status == "FAIL":
            lines.append(
                "本次結果屬量產導入風險高，代表目前成像條件對 recipe 視窗的安全裕度不足，"
                "建議先收斂光源、曝光、治具與對焦條件，再進一步調整 AOI recipe。"
            )
        elif m.overall_status == "WARNING":
            lines.append(
                "本次結果屬量產觀察項，代表影像仍可能可用，但加權總分或安全裕度不足，"
                "建議用更多 OK/NG 樣本確認誤判與漏判風險。"
            )
        elif m.overall_status == "PASS":
            lines.append(
                "本次結果屬量產風險低，代表加權總分已達標；仍建議搭配實際 OK/NG "
                "樣本確認 recipe 視窗。"
            )

        lines.append(f"高風險項目：{self._format_reason_items(fail_items)}")
        lines.append(f"觀察項目：{self._format_reason_items(warn_items)}")
        lines.append(
            "目前使用門檻："
            f"平均灰階高風險<{t.mean_gray_fail}/觀察<{t.mean_gray_warn}；"
            f"均勻性高風險<{t.uniformity_fail}/觀察<{t.uniformity_warn}；"
            f"clipping 高風險>{t.clipping_fail_pct}%/觀察>{t.clipping_warn_pct}%；"
            f"CNR 高風險<{t.cnr_fail}/觀察<{t.cnr_warn}；"
            f"單張空間 SNR proxy 高風險<{t.snr_fail}/觀察<{t.snr_warn}；"
            f"背景 std 高風險>{t.bg_std_fail}/觀察>{t.bg_std_warn}；"
            f"清晰度高風險<{t.sharpness_fail}/觀察<{t.sharpness_warn}；"
            f"灰階展開高風險<{t.hist_spread_fail}/觀察<{t.hist_spread_warn}。"
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
            "未找到候選缺陷，因此自動 CNR 對量產 NG 缺陷分離度的佐證不足；"
            "若此圖應為 OK，可作為低缺陷背景樣本一併保存。"
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
                "偏低時代表進光量裕度不足，後續拉亮會同步放大雜訊並壓縮 recipe 視窗。",
            ),
            self._lower_limit_note(
                "均勻性 min/max",
                m.uniformity_ratio,
                t.uniformity_warn,
                t.uniformity_fail,
                "越接近 1 代表左右分區越一致；偏低會讓固定門檻在不同位置表現不一致。",
            ),
            (
                f"低灰階 clipping：{m.low_clip_pct:.4f}%（{low_clip_state}）。"
                "數值偏高代表暗部資訊被壓到 0 附近，暗缺陷或背景差異的量產裕度會下降。"
            ),
            (
                f"高灰階 clipping：{m.high_clip_pct:.4f}%（{high_clip_state}）。"
                "數值偏高代表亮部過曝，亮缺陷或材質差異的量產裕度會下降。"
            ),
            self._lower_limit_note(
                "P99-P01 灰階展開",
                m.hist_spread_p99_p01,
                t.hist_spread_warn,
                t.hist_spread_fail,
                "偏窄代表有效灰階動態範圍不足，OK/NG 差異會更難切開。",
            ),
            f"CNR：{cnr_note}",
            self._lower_limit_note(
                "單張空間 SNR proxy",
                m.signal_to_noise_ratio,
                t.snr_warn,
                t.snr_fail,
                "代表平均灰階相對 robust noise sigma 的安全裕度；偏低時整體訊號較容易被雜訊干擾。",
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
                "偏低時可能是對焦、震動或運動模糊，細小缺陷邊緣的量產一致性會下降。",
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
            f"{label}：{value:.3f}（{state}；高風險<{fail_limit}，觀察<{warn_limit}）。"
            f"{detail}"
        )

    def _upper_limit_note(
        self, label: str, value: float, warn_limit: float, fail_limit: float, detail: str
    ) -> str:
        state = self._upper_limit_state(value, warn_limit, fail_limit)
        return (
            f"{label}：{value:.3f}（{state}；高風險>{fail_limit}，觀察>{warn_limit}）。"
            f"{detail}"
        )

    def _lower_limit_state(self, value: float, warn_limit: float, fail_limit: float) -> str:
        if value < fail_limit:
            return "高風險區"
        if value < warn_limit:
            return "觀察區"
        return "低風險區"

    def _upper_limit_state(self, value: float, warn_limit: float, fail_limit: float) -> str:
        if value > fail_limit:
            return "高風險區"
        if value > warn_limit:
            return "觀察區"
        return "低風險區"

    def _risk_status_label(self, status: str) -> str:
        labels = {
            "PASS": "量產風險低",
            "WARNING": "量產觀察項",
            "FAIL": "量產導入風險高",
        }
        return labels.get(status, status)
