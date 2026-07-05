# -*- coding: utf-8 -*-
"""多影像灰階漂移 / 跨圖一致性報告。

批次分析多張同類影像時，除了各自的 PASS/WARNING/FAIL，還關心「整批之間」
的一致性：平均灰階是否漂移、各區均勻性是否穩定、背景雜訊是否忽高忽低。
漂移過大代表光源衰減、相機增益變動或治具擺放不一致，是量產穩定性的風險。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import List, Sequence

from ..core.config import Thresholds
from ..core.metrics import Metrics


@dataclass
class DriftStats:
    """單一指標在整批影像上的分佈統計。"""

    label: str
    count: int = 0
    mean: float = 0.0
    stdev: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0

    @property
    def spread(self) -> float:
        """全距（max - min），用來看漂移幅度。"""
        return self.max_value - self.min_value

    @classmethod
    def from_values(cls, label: str, values: Sequence[float]) -> "DriftStats":
        vals = list(values)
        if not vals:
            return cls(label=label)
        return cls(
            label=label,
            count=len(vals),
            mean=float(mean(vals)),
            stdev=float(pstdev(vals)) if len(vals) > 1 else 0.0,
            min_value=float(min(vals)),
            max_value=float(max(vals)),
        )


@dataclass
class DriftReport:
    """整批漂移報告的結構化結果。"""

    stats: List[DriftStats] = field(default_factory=list)
    mean_gray_spread: float = 0.0
    drift_status: str = "PASS"  # PASS / WARNING / FAIL（依平均灰階漂移）
    warnings: List[str] = field(default_factory=list)


class DriftReporter:
    """把多張影像的 Metrics 匯整成跨圖一致性報告。"""

    def __init__(self, thresholds: Thresholds | None = None):
        self.thresholds = thresholds or Thresholds()

    def analyze(self, metrics_list: Sequence[Metrics]) -> DriftReport:
        report = DriftReport()
        if not metrics_list:
            return report

        stats = [
            DriftStats.from_values("平均灰階", [m.mean_gray for m in metrics_list]),
            DriftStats.from_values("均勻性 min/max", [m.uniformity_ratio for m in metrics_list]),
            DriftStats.from_values("背景 std", [m.bg_std_est for m in metrics_list]),
            DriftStats.from_values("整體 SNR", [m.signal_to_noise_ratio for m in metrics_list]),
            DriftStats.from_values("自動 CNR", [m.auto_defect_cnr_est for m in metrics_list]),
            DriftStats.from_values("P99-P01 展開", [m.hist_spread_p99_p01 for m in metrics_list]),
        ]
        report.stats = stats

        mean_gray_stats = stats[0]
        report.mean_gray_spread = mean_gray_stats.spread
        # 沿用 hist_spread_* 門檻衡量跨圖平均灰階漂移（已為多圖預留）
        if report.mean_gray_spread >= self.thresholds.hist_spread_fail:
            report.drift_status = "FAIL"
            report.warnings.append(
                f"平均灰階跨圖漂移 {report.mean_gray_spread:.1f} "
                f"≥ FAIL 門檻 {self.thresholds.hist_spread_fail:.1f}"
            )
        elif report.mean_gray_spread >= self.thresholds.hist_spread_warn:
            report.drift_status = "WARNING"
            report.warnings.append(
                f"平均灰階跨圖漂移 {report.mean_gray_spread:.1f} "
                f"≥ WARNING 門檻 {self.thresholds.hist_spread_warn:.1f}"
            )
        return report

    def build(self, metrics_list: Sequence[Metrics]) -> str:
        if not metrics_list:
            return "（無資料，無法產生跨圖漂移報告）"

        report = self.analyze(metrics_list)
        lines = [
            f"【跨圖一致性 / 灰階漂移】共 {len(metrics_list)} 張",
            f"漂移判定：{report.drift_status}",
            "",
            f"{'指標':<14}{'平均':>10}{'標準差':>10}{'最小':>10}{'最大':>10}{'全距':>10}",
        ]
        for s in report.stats:
            lines.append(
                f"{s.label:<14}{s.mean:>10.2f}{s.stdev:>10.2f}"
                f"{s.min_value:>10.2f}{s.max_value:>10.2f}{s.spread:>10.2f}"
            )
        if report.warnings:
            lines.append("")
            lines.append("提醒：")
            lines.extend(f"- {w}" for w in report.warnings)
        return "\n".join(lines)
