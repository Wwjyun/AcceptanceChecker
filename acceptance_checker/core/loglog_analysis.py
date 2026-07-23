# -*- coding: utf-8 -*-
"""Single-variable log-log brightness diagnostics from appendix B."""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np


class LogLogAnalysisError(ValueError):
    """Raised when appendix-B experiment evidence is insufficient."""


@dataclass(frozen=True)
class BrightnessPoint:
    brightness: float
    spatial_std_samples: Sequence[float]
    temporal_noise_samples: Sequence[float]
    evidence_source: str

    def __post_init__(self) -> None:
        if self.brightness <= 0 or not self.evidence_source:
            raise LogLogAnalysisError("brightness and evidence source must be positive/non-empty")
        for label, values in (
            ("spatial STD", self.spatial_std_samples),
            ("temporal noise", self.temporal_noise_samples),
        ):
            if len(values) < 30:
                raise LogLogAnalysisError(f"{label} requires at least 30 samples per point")
            if any(not math.isfinite(value) or value <= 0 for value in values):
                raise LogLogAnalysisError(f"{label} samples must be finite and positive")


@dataclass(frozen=True)
class PowerLawFit:
    exponent_b: float
    coefficient_a: float
    r_squared: float
    sample_points: int

    def predict(self, brightness: float) -> float:
        return self.coefficient_a * brightness**self.exponent_b


@dataclass
class LogLogAnalysisResult:
    experiment_id: str
    controlled_variable: str
    fixed_conditions: Dict[str, Any]
    brightness: List[float]
    spatial_std: List[float]
    temporal_noise: List[float]
    spatial_fit: PowerLawFit
    temporal_fit: PowerLawFit
    evidence_sources: List[str]

    def to_svg(self, *, width: int = 800, height: int = 420) -> str:
        if width < 400 or height < 240:
            raise LogLogAnalysisError("regression SVG is too small")
        padding = 55
        log_x = np.log10(self.brightness)
        log_values = np.log10([*self.spatial_std, *self.temporal_noise])
        x_min, x_max = float(np.min(log_x)), float(np.max(log_x))
        y_min, y_max = float(np.min(log_values)), float(np.max(log_values))
        if x_max == x_min or y_max == y_min:
            raise LogLogAnalysisError("regression chart requires non-zero axis ranges")

        def px(value: float) -> float:
            return padding + (math.log10(value) - x_min) / (x_max - x_min) * (
                width - 2 * padding
            )

        def py(value: float) -> float:
            return height - padding - (
                math.log10(value) - y_min
            ) / (y_max - y_min) * (height - 2 * padding)

        elements = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            (
                f'<text x="{width / 2:.1f}" y="24" text-anchor="middle" '
                f'font-family="sans-serif" font-size="16">'
                f'{html.escape(self.experiment_id)} log-log regression</text>'
            ),
            (
                f'<line x1="{padding}" y1="{height-padding}" x2="{width-padding}" '
                f'y2="{height-padding}" stroke="black"/>'
            ),
            (
                f'<line x1="{padding}" y1="{padding}" x2="{padding}" '
                f'y2="{height-padding}" stroke="black"/>'
            ),
        ]
        colors = (
            ("spatial STD", self.spatial_std, self.spatial_fit, "#1565c0"),
            ("temporal noise", self.temporal_noise, self.temporal_fit, "#c62828"),
        )
        sorted_x = sorted(self.brightness)
        for label, values, fit, color in colors:
            for brightness, value in zip(self.brightness, values):
                elements.append(
                    f'<circle cx="{px(brightness):.2f}" cy="{py(value):.2f}" '
                    f'r="4" fill="{color}"/>'
                )
            path = " ".join(
                (
                    "M" if index == 0 else "L"
                )
                + f" {px(brightness):.2f} {py(fit.predict(brightness)):.2f}"
                for index, brightness in enumerate(sorted_x)
            )
            elements.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
            elements.append(
                f'<text x="{width-padding-240}" y="{45 + 20 * len(elements) % 40}" '
                f'font-family="sans-serif" font-size="12" fill="{color}">'
                f'{html.escape(label)}: b={fit.exponent_b:.4f}, R²={fit.r_squared:.4f}</text>'
            )
        elements.extend(
            [
                (
                    f'<text x="{width/2:.1f}" y="{height-12}" text-anchor="middle" '
                    'font-family="sans-serif" font-size="12">brightness (log scale)</text>'
                ),
                (
                    f'<text x="15" y="{height/2:.1f}" text-anchor="middle" '
                    'font-family="sans-serif" font-size="12" '
                    f'transform="rotate(-90 15 {height/2:.1f})">'
                    'noise / spatial STD (log scale)</text>'
                ),
                "</svg>",
            ]
        )
        return "\n".join(elements)

    def save_svg(self, path: str) -> None:
        Path(path).write_text(self.to_svg() + "\n", encoding="utf-8")


class LogLogAnalyzer:
    def analyze(
        self,
        *,
        experiment_id: str,
        points: Sequence[BrightnessPoint],
        fixed_conditions: Dict[str, Any],
        controlled_variable: str = "lighting_brightness",
    ) -> LogLogAnalysisResult:
        if not experiment_id:
            raise LogLogAnalysisError("experiment id is required")
        if controlled_variable not in {"lighting_brightness", "exposure"}:
            raise LogLogAnalysisError("only one declared brightness variable may change")
        if not fixed_conditions or any(value in ("", None) for value in fixed_conditions.values()):
            raise LogLogAnalysisError("fixed experimental conditions must be recorded")
        if len(points) < 5:
            raise LogLogAnalysisError("log-log analysis requires at least five brightness points")
        brightness = [float(point.brightness) for point in points]
        if len(set(brightness)) != len(brightness):
            raise LogLogAnalysisError("brightness points must be unique")
        spatial = [float(np.mean(point.spatial_std_samples)) for point in points]
        temporal = [float(np.mean(point.temporal_noise_samples)) for point in points]
        return LogLogAnalysisResult(
            experiment_id=experiment_id,
            controlled_variable=controlled_variable,
            fixed_conditions=dict(fixed_conditions),
            brightness=brightness,
            spatial_std=spatial,
            temporal_noise=temporal,
            spatial_fit=_fit_power_law(brightness, spatial),
            temporal_fit=_fit_power_law(brightness, temporal),
            evidence_sources=list(dict.fromkeys(point.evidence_source for point in points)),
        )


def _fit_power_law(x_values: Sequence[float], y_values: Sequence[float]) -> PowerLawFit:
    x = np.log(np.asarray(x_values, dtype=np.float64))
    y = np.log(np.asarray(y_values, dtype=np.float64))
    design = np.column_stack([x, np.ones_like(x)])
    exponent, intercept = np.linalg.lstsq(design, y, rcond=None)[0]
    predicted = design @ np.array([exponent, intercept])
    residual_sum = float(np.sum((y - predicted) ** 2))
    total_sum = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 if total_sum == 0 else 1.0 - residual_sum / total_sum
    return PowerLawFit(
        exponent_b=float(exponent),
        coefficient_a=float(math.exp(intercept)),
        r_squared=r_squared,
        sample_points=len(x_values),
    )
