# -*- coding: utf-8 -*-
"""把現行單張 quick-check Metrics 明確轉成「未完成 v4 驗證」的量測資料。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .metrics import Metrics
from .v4_domain import ImageLevel, MeasurementResult, MetricGroup, Severity


@dataclass(frozen=True)
class _LegacyField:
    field_name: str
    metric_id: str
    group: MetricGroup
    unit: str


_LEGACY_FIELDS = (
    _LegacyField("mean_gray", "legacy.mean_gray_8bit", MetricGroup.G1, "gray8"),
    _LegacyField("uniformity_ratio", "legacy.uniformity_5_zone", MetricGroup.G1, "ratio"),
    _LegacyField("low_clip_pct", "legacy.low_clip_at_zero", MetricGroup.G1, "percent"),
    _LegacyField("high_clip_pct", "legacy.high_clip_at_255", MetricGroup.G1, "percent"),
    _LegacyField("hist_spread_p99_p01", "legacy.hist_spread_8bit", MetricGroup.G1, "gray8"),
    _LegacyField("bg_std_est", "legacy.full_image_spatial_std", MetricGroup.G1, "gray8"),
    _LegacyField(
        "signal_to_noise_ratio",
        "legacy.single_image_spatial_snr_proxy",
        MetricGroup.G3,
        "ratio",
    ),
    _LegacyField(
        "sharpness_laplacian_var",
        "legacy.laplacian_variance_proxy",
        MetricGroup.G2,
        "variance",
    ),
    _LegacyField(
        "auto_defect_cnr_est",
        "legacy.auto_candidate_cnr_proxy",
        MetricGroup.G6,
        "ratio",
    ),
)

_MISSING_REASON = (
    "legacy quick-check 指標缺少正式 v4 所需的模式化 ROI、原始 bit depth、"
    "樣本或 Golden 證據，不得直接視為已完成驗收"
)


class LegacyMetricsAdapter:
    """將 legacy 數值留作證據，但一律標示 NOT_EVALUATED。"""

    FORMULA_VERSION = "legacy-proxy-v1"

    def adapt(self, metrics: Metrics) -> List[MeasurementResult]:
        source = metrics.file_path or metrics.file_name
        evidence = [source] if source else []
        return [
            MeasurementResult(
                metric_id=item.metric_id,
                group=item.group,
                severity=Severity.NOT_EVALUATED,
                unit=item.unit,
                formula_version=self.FORMULA_VERSION,
                image_level=ImageLevel.L2,
                value=getattr(metrics, item.field_name),
                sample_count=1,
                evidence_sources=evidence,
                missing_reason=_MISSING_REASON,
                metadata={
                    "legacy_field": item.field_name,
                    "legacy_norm_method": metrics.norm_method,
                    "legacy_analysis_step": metrics.analysis_step,
                },
            )
            for item in _LEGACY_FIELDS
        ]


def legacy_metrics_to_measurements(metrics: Metrics) -> List[MeasurementResult]:
    """函式型便捷 API。"""
    return LegacyMetricsAdapter().adapt(metrics)
