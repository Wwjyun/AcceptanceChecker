import numpy as np
import pytest

from acceptance_checker import BrightnessPoint, LogLogAnalysisError, LogLogAnalyzer


def points():
    return [
        BrightnessPoint(
            brightness=brightness,
            spatial_std_samples=[2 * brightness**0.5] * 30,
            temporal_noise_samples=[3 * brightness**0.25] * 30,
            evidence_source=f"{brightness}.csv",
        )
        for brightness in (10, 20, 40, 80, 160)
    ]


def test_loglog_separates_exponents_and_writes_regression_svg(tmp_path):
    result = LogLogAnalyzer().analyze(
        experiment_id="light-sweep",
        points=points(),
        fixed_conditions={"exposure_us": 100, "gain": 1, "sample": "golden"},
    )

    assert result.spatial_fit.exponent_b == pytest.approx(0.5)
    assert result.temporal_fit.exponent_b == pytest.approx(0.25)
    path = tmp_path / "regression.svg"
    result.save_svg(str(path))
    text = path.read_text(encoding="utf-8")
    assert "<svg" in text and "spatial STD" in text and "temporal noise" in text


def test_loglog_requires_five_points_and_30_samples_per_series():
    with pytest.raises(LogLogAnalysisError, match="30"):
        BrightnessPoint(10, np.ones(29), np.ones(30), "10.csv")
    with pytest.raises(LogLogAnalysisError, match="five"):
        LogLogAnalyzer().analyze(
            experiment_id="short",
            points=points()[:4],
            fixed_conditions={"gain": 1},
        )
