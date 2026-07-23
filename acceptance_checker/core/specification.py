# -*- coding: utf-8 -*-
"""版本化 v4 卡控規格的載入、驗證與純數值分級。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any, Dict, List, Optional

from .v4_domain import MetricGroup, OpticalMode, Severity


class SpecificationError(ValueError):
    """規格檔缺漏、矛盾或版本不符。"""


@dataclass(frozen=True)
class MetricSpecification:
    metric_id: str
    group: MetricGroup
    modes: List[str]
    name: str
    unit: str
    display_bands: Dict[str, str]
    classification: Dict[str, Any]
    requirement_profile: str
    formula: str
    s0_special_events: List[str]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetricSpecification":
        return cls(
            metric_id=str(data["id"]),
            group=MetricGroup(data["group"]),
            modes=[str(item) for item in data["modes"]],
            name=str(data["name"]),
            unit=str(data["unit"]),
            display_bands={str(key): str(value) for key, value in data["display_bands"].items()},
            classification=dict(data["classification"]),
            requirement_profile=str(data["requirement_profile"]),
            formula=str(data["formula"]),
            s0_special_events=[str(item) for item in data.get("s0_special_events", [])],
        )

    def applies_to(self, mode: OpticalMode) -> bool:
        return "all" in self.modes or mode.value in self.modes

    def classify(self, value: float) -> Severity:
        """依已驗證的純數值規則分級；質性/複合規則拒絕猜測。"""
        kind = self.classification["kind"]
        if kind == "lower_is_good":
            if value <= float(self.classification["s3_max"]):
                return Severity.S3
            if value <= float(self.classification["s2_max"]):
                return Severity.S2
            if value <= float(self.classification["s1_max"]):
                return Severity.S1
            return Severity.S0
        if kind == "higher_is_good":
            if value >= float(self.classification["s3_min"]):
                return Severity.S3
            if value >= float(self.classification["s2_min"]):
                return Severity.S2
            if value >= float(self.classification["s1_min"]):
                return Severity.S1
            return Severity.S0
        if kind == "target_range":
            s3_low, s3_high = self.classification["s3"]
            s2_low, s2_high = self.classification["s2"]
            s1_low, s1_high = self.classification["s1"]
            if float(s3_low) <= value <= float(s3_high):
                return Severity.S3
            if float(s2_low) <= value <= float(s2_high):
                return Severity.S2
            if float(s1_low) <= value <= float(s1_high):
                return Severity.S1
            return Severity.S0
        if kind == "zero_fatal":
            return Severity.S3 if value == 0 else Severity.S0
        if kind == "intervals":
            for interval in self.classification["intervals"]:
                if _contains(interval, value):
                    return Severity(interval["severity"])
            raise SpecificationError(f"{self.metric_id} 的 intervals 未涵蓋數值 {value}")
        raise SpecificationError(f"{self.metric_id} 是 {kind} 規則，不能只用單一數值分級")


@dataclass(frozen=True)
class V4Specification:
    schema_version: str
    spec_version: str
    profile_type: str
    status: str
    effective_date: Optional[str]
    formula_version: str
    source_documents: List[str]
    requirement_profiles: Dict[str, Dict[str, Any]]
    metrics: List[MetricSpecification]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V4Specification":
        specification = cls(
            schema_version=str(data["schema_version"]),
            spec_version=str(data["spec_version"]),
            profile_type=str(data["profile_type"]),
            status=str(data["status"]),
            effective_date=(
                str(data["effective_date"]) if data.get("effective_date") is not None else None
            ),
            formula_version=str(data["formula_version"]),
            source_documents=[str(item) for item in data["source_documents"]],
            requirement_profiles={
                str(key): dict(value) for key, value in data["requirement_profiles"].items()
            },
            metrics=[MetricSpecification.from_dict(dict(item)) for item in data["metrics"]],
        )
        specification.validate()
        return specification

    def validate(self) -> None:
        if self.profile_type != "v4_acceptance_spec":
            raise SpecificationError("profile_type 必須是 v4_acceptance_spec")
        if self.schema_version != "1.0":
            raise SpecificationError(f"不支援的 schema_version：{self.schema_version}")
        if not self.spec_version or not self.formula_version:
            raise SpecificationError("spec_version 與 formula_version 不得為空")
        if self.status == "approved" and not self.effective_date:
            raise SpecificationError("已核准規格必須提供 effective_date")
        if len(self.metrics) != 63:
            raise SpecificationError(f"v4 卡控規格必須有 63 項，實得 {len(self.metrics)}")

        ids = [item.metric_id for item in self.metrics]
        if len(ids) != len(set(ids)):
            raise SpecificationError("metric id 不得重複")

        valid_modes = {"all", *(mode.value for mode in OpticalMode)}
        expected_bands = {
            item.value for item in (Severity.S3, Severity.S2, Severity.S1, Severity.S0)
        }
        for metric in self.metrics:
            if not metric.metric_id or not metric.name or not metric.unit or not metric.formula:
                raise SpecificationError(f"{metric.metric_id or '<empty>'} 缺少必要欄位")
            if not metric.modes or not set(metric.modes) <= valid_modes:
                raise SpecificationError(f"{metric.metric_id} 的適用模式無效")
            if set(metric.display_bands) != expected_bands:
                raise SpecificationError(f"{metric.metric_id} 必須定義 S3～S0 顯示門檻")
            if metric.requirement_profile not in self.requirement_profiles:
                raise SpecificationError(f"{metric.metric_id} 引用不存在的 requirement profile")
            self._validate_classification(metric)

    def _validate_classification(self, metric: MetricSpecification) -> None:
        rule = metric.classification
        kind = rule.get("kind")
        if kind == "lower_is_good":
            values = [float(rule[key]) for key in ("s3_max", "s2_max", "s1_max")]
            if not values[0] < values[1] < values[2]:
                raise SpecificationError(f"{metric.metric_id} 的 lower_is_good 門檻順序錯誤")
        elif kind == "higher_is_good":
            values = [float(rule[key]) for key in ("s1_min", "s2_min", "s3_min")]
            if not values[0] < values[1] < values[2]:
                raise SpecificationError(f"{metric.metric_id} 的 higher_is_good 門檻順序錯誤")
        elif kind == "target_range":
            s1_low, s1_high = (float(item) for item in rule["s1"])
            s2_low, s2_high = (float(item) for item in rule["s2"])
            s3_low, s3_high = (float(item) for item in rule["s3"])
            if not (s1_low < s2_low < s3_low <= s3_high < s2_high < s1_high):
                raise SpecificationError(f"{metric.metric_id} 的 target_range 未正確巢狀")
        elif kind == "intervals":
            _validate_intervals(metric.metric_id, list(rule["intervals"]))
        elif kind not in {"zero_fatal", "record_only", "categorical"}:
            raise SpecificationError(f"{metric.metric_id} 使用未知 classification kind：{kind}")

    def get_metric(self, metric_id: str) -> MetricSpecification:
        for metric in self.metrics:
            if metric.metric_id == metric_id:
                return metric
        raise KeyError(metric_id)

    def metrics_for_mode(self, mode: OpticalMode) -> List[MetricSpecification]:
        return [item for item in self.metrics if item.applies_to(mode)]


def _contains(interval: Dict[str, Any], value: float) -> bool:
    minimum: Optional[float] = interval.get("min")
    maximum: Optional[float] = interval.get("max")
    if minimum is not None:
        if value < float(minimum) or (
            value == float(minimum) and not interval.get("min_inclusive", True)
        ):
            return False
    if maximum is not None:
        if value > float(maximum) or (
            value == float(maximum) and not interval.get("max_inclusive", True)
        ):
            return False
    return True


def _validate_intervals(metric_id: str, intervals: List[Dict[str, Any]]) -> None:
    if not intervals:
        raise SpecificationError(f"{metric_id} 的 intervals 不得為空")
    if intervals[0].get("min") is not None or intervals[-1].get("max") is not None:
        raise SpecificationError(f"{metric_id} 的 intervals 必須涵蓋負無限至正無限")
    for interval in intervals:
        Severity(interval["severity"])
    for left, right in zip(intervals, intervals[1:]):
        if left.get("max") != right.get("min"):
            raise SpecificationError(f"{metric_id} 的 intervals 有缺口或重疊")
        if bool(left.get("max_inclusive", True)) == bool(right.get("min_inclusive", True)):
            raise SpecificationError(f"{metric_id} 的 intervals 邊界必須只由一側包含")


def load_v4_spec(path: str) -> V4Specification:
    with open(path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise SpecificationError("規格 JSON 必須是物件")
    return V4Specification.from_dict(data)


def load_default_v4_spec() -> V4Specification:
    package = resources.files("acceptance_checker.specs")
    with package.joinpath("v4_draft.json").open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise SpecificationError("內建 v4 規格 JSON 必須是物件")
    return V4Specification.from_dict(data)
