# -*- coding: utf-8 -*-
"""Reproducible large-line-scan and temporal-sequence memory/time benchmark."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from dataclasses import asdict, dataclass
from typing import Sequence

import numpy as np

from acceptance_checker import (
    RawImage,
    RoiCreationMethod,
    RoiDefinition,
    RoiType,
    TemporalAcceptanceMeasurer,
    TemporalMeasurementInputs,
    TemporalSeries,
    measure_raw_16_zones,
)


@dataclass(frozen=True)
class BenchmarkResult:
    line_scan_shape: Sequence[int]
    temporal_shape: Sequence[int]
    line_scan_input_bytes: int
    temporal_input_bytes: int
    elapsed_seconds: float
    python_peak_bytes: int
    uniformity_u: float
    temporal_snr: float


def run_benchmark(
    *,
    height: int = 2048,
    width: int = 8192,
    frames: int = 30,
    sequence_height: int = 64,
    sequence_width: int = 2048,
    seed: int = 20260723,
) -> BenchmarkResult:
    if min(height, width, frames, sequence_height, sequence_width) <= 0:
        raise ValueError("benchmark dimensions must be positive")
    if frames < 30:
        raise ValueError("formal temporal benchmark requires at least 30 frames")

    tracemalloc.start()
    started = time.perf_counter()
    line = np.linspace(1000, 3000, width, dtype=np.uint16)
    line_scan = np.broadcast_to(line, (height, width)).copy()
    raw = RawImage.from_array(line_scan, bit_depth=12)
    effective = RoiDefinition(
        roi_id="benchmark-full-width",
        roi_type=RoiType.EFFECTIVE_INSPECTION_AREA,
        x=0,
        y=0,
        width=width,
        height=height,
        creation_method=RoiCreationMethod.FIXED_RECIPE,
        operator="benchmark",
        version="1",
        image_id="benchmark-line-scan",
    )
    zones = measure_raw_16_zones(raw, effective)

    rng = np.random.default_rng(seed)
    temporal_frames = rng.normal(
        2000,
        3,
        (frames, sequence_height, sequence_width),
    ).astype(np.float32)
    temporal_roi = RoiDefinition(
        roi_id="benchmark-temporal",
        roi_type=RoiType.DEFECT_FREE_BACKGROUND,
        x=0,
        y=0,
        width=sequence_width,
        height=sequence_height,
        creation_method=RoiCreationMethod.FIXED_RECIPE,
        operator="benchmark",
        version="1",
        image_id="benchmark-temporal-series",
    )
    temporal_report = TemporalAcceptanceMeasurer().measure(
        TemporalMeasurementInputs(
            series=TemporalSeries(
                frames=temporal_frames,
                timestamps_seconds=np.linspace(0, 8 * 3600, frames).tolist(),
                evidence_sources=[
                    f"benchmark-frame-{index:03}.raw" for index in range(frames)
                ],
            ),
            roi=temporal_roi,
        )
    )
    temporal_snr = next(
        item.value
        for item in temporal_report.measurements
        if item.metric_id == "g3.temporal_snr"
    )
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return BenchmarkResult(
        line_scan_shape=line_scan.shape,
        temporal_shape=temporal_frames.shape,
        line_scan_input_bytes=line_scan.nbytes,
        temporal_input_bytes=temporal_frames.nbytes,
        elapsed_seconds=elapsed,
        python_peak_bytes=peak,
        uniformity_u=zones.uniformity_ratio,
        temporal_snr=float(temporal_snr),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--height", type=int, default=2048)
    parser.add_argument("--width", type=int, default=8192)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--sequence-height", type=int, default=64)
    parser.add_argument("--sequence-width", type=int, default=2048)
    args = parser.parse_args()
    result = run_benchmark(
        height=args.height,
        width=args.width,
        frames=args.frames,
        sequence_height=args.sequence_height,
        sequence_width=args.sequence_width,
    )
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
