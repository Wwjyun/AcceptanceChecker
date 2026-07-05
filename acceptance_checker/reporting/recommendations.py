# -*- coding: utf-8 -*-
"""依影像指標產生工程調整建議。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..core.config import Thresholds
from ..core.metrics import Metrics


@dataclass(frozen=True)
class Recommendation:
    """單一工程建議項目。"""

    title: str
    action: str

    def format(self) -> str:
        return f"{self.title}：{self.action}"


class RecommendationBuilder:
    """把 Metrics 與 Thresholds 轉成硬體/製程調整方向。"""

    def build(self, m: Metrics, thresholds: Thresholds) -> str:
        recommendations = self.recommend(m, thresholds)
        return "\n".join(f"{idx}. {item.format()}" for idx, item in enumerate(recommendations, 1))

    def recommend(self, m: Metrics, t: Thresholds) -> List[Recommendation]:
        items: List[Recommendation] = []

        self._add_exposure_recommendations(items, m, t)
        self._add_uniformity_recommendations(items, m, t)
        self._add_noise_recommendations(items, m, t)
        self._add_defect_separation_recommendations(items, m, t)
        self._add_focus_recommendations(items, m, t)

        if not items:
            items.append(
                Recommendation(
                    "目前建議",
                    "主要指標未觸發門檻；維持現有光源、曝光、鏡頭與治具設定，"
                    "再用實際 OK/NG 樣本確認 AOI recipe 視窗。",
                )
            )
        return items

    def _add_exposure_recommendations(
        self, items: List[Recommendation], m: Metrics, t: Thresholds
    ) -> None:
        if m.high_clip_pct > t.clipping_warn_pct:
            items.append(
                Recommendation(
                    "亮部 clipping 偏高",
                    "先降低曝光時間或光源亮度；若仍過曝，再降低相機 gain。"
                    "目標是讓高灰階 clipping 低於 warning 門檻，避免亮部資訊被截斷。",
                )
            )
            return

        if m.mean_gray < t.mean_gray_warn or m.low_clip_pct > t.clipping_warn_pct:
            items.append(
                Recommendation(
                    "整體亮度不足",
                    "優先提高光源亮度，其次延長曝光時間；只有在曝光與光源受限時才提高 gain。"
                    "調整後確認平均灰階高於 warning 門檻，且高灰階 clipping 不超標。",
                )
            )

        if m.hist_spread_p99_p01 < t.hist_spread_warn:
            items.append(
                Recommendation(
                    "灰階動態範圍偏窄",
                    "調整光源角度、曝光或 16-bit 轉 8-bit 正規化方式，讓 P01 到 P99 的展開變大；"
                    "避免只靠後處理硬拉對比。",
                )
            )

    def _add_uniformity_recommendations(
        self, items: List[Recommendation], m: Metrics, t: Thresholds
    ) -> None:
        if m.uniformity_ratio >= t.uniformity_warn:
            return

        zone_means = [
            ("左側", m.zone_1_left_mean),
            ("左中", m.zone_2_left_mid_mean),
            ("中間", m.zone_3_center_mean),
            ("右中", m.zone_4_right_mid_mean),
            ("右側", m.zone_5_right_mean),
        ]
        darkest = min(zone_means, key=lambda item: item[1])[0]
        brightest = max(zone_means, key=lambda item: item[1])[0]
        items.append(
            Recommendation(
                "分區均勻性不足",
                f"{darkest}偏暗、{brightest}偏亮；調整線光源左右功率平衡、光源/相機平行度、"
                "擴散板位置或工件高度，目標是把 min/max 均勻性拉高到 warning 門檻以上。",
            )
        )

    def _add_noise_recommendations(
        self, items: List[Recommendation], m: Metrics, t: Thresholds
    ) -> None:
        if m.signal_to_noise_ratio < t.snr_warn:
            items.append(
                Recommendation(
                    "整體 SNR 偏低",
                    "先提高有效信號，例如增加光源亮度或曝光；若背景 std 同時偏高，"
                    "先降低 gain、檢查光源閃爍與環境遮光，再重新評估 SNR。",
                )
            )

        if m.bg_std_est > t.bg_std_warn:
            items.append(
                Recommendation(
                    "背景雜訊或紋理偏高",
                    "降低相機 gain、檢查光源電源穩定度與頻閃，並固定相機/治具/輸送震動；"
                    "若是反光材質，加入偏光片或調整打光角度。",
                )
            )

    def _add_defect_separation_recommendations(
        self, items: List[Recommendation], m: Metrics, t: Thresholds
    ) -> None:
        if m.auto_defect_count == 0:
            items.append(
                Recommendation(
                    "未找到自動候選缺陷",
                    "若此圖是 NG 樣本，改用人工 ROI 量測缺陷 CNR；"
                    "再調整光源角度、波長、偏光或曝光，讓缺陷與背景灰階差變大。",
                )
            )
            return

        if m.auto_defect_cnr_est < t.cnr_warn:
            items.append(
                Recommendation(
                    "缺陷 CNR 偏低",
                    "優先改變打光角度、光源波長或偏光方向，讓缺陷 contrast 增加；"
                    "同時降低背景雜訊，目標是把候選 CNR 拉高到 warning 門檻以上。",
                )
            )

    def _add_focus_recommendations(
        self, items: List[Recommendation], m: Metrics, t: Thresholds
    ) -> None:
        if m.sharpness_laplacian_var >= t.sharpness_warn:
            return

        items.append(
            Recommendation(
                "清晰度偏低",
                "重新對焦並鎖緊鏡頭，檢查工作距離與景深；若線上影像仍模糊，"
                "縮短曝光時間、提高光源亮度補償，並降低輸送或治具震動。",
            )
        )
