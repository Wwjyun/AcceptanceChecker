from benchmarks.benchmark_line_scan import run_benchmark


def test_line_scan_and_temporal_benchmark_smoke_has_bounded_resources():
    result = run_benchmark(
        height=256,
        width=4096,
        frames=30,
        sequence_height=32,
        sequence_width=512,
    )

    assert result.line_scan_shape == (256, 4096)
    assert result.temporal_shape == (30, 32, 512)
    assert result.line_scan_input_bytes == 256 * 4096 * 2
    assert result.temporal_input_bytes == 30 * 32 * 512 * 4
    assert 0 < result.uniformity_u <= 1
    assert result.temporal_snr > 0
    assert result.elapsed_seconds < 10
    assert result.python_peak_bytes < 512 * 1024 * 1024
