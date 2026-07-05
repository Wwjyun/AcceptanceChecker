# AcceptanceChecker

AcceptanceChecker is a Python AOI raw-image acceptance tool. It analyzes inspection images, computes image-quality and defect metrics, scores each image on a weighted 100-point scale, and classifies the score as `PASS`, `WARNING`, or `FAIL`.

The project provides:

- A PySide6 desktop GUI for opening images, viewing overlays, selecting ROI, tuning thresholds, and exporting results.
- A batch CLI for scripted analysis, CSV export, threshold JSON loading, parallel processing, and drift summaries.
- A reusable Python API under `acceptance_checker`.
- Pytest, Ruff, Mypy, and an offscreen GUI smoke test for validation.

## Requirements

- Python 3.9+
- Windows, Linux, or macOS
- Runtime packages listed in `requirements.txt`

Install runtime dependencies:

```bash
pip install -r requirements.txt
```

For development and validation:

```bash
pip install -e ".[dev]"
```

## Quick Start

Run the GUI:

```bash
python main.py
```

Run batch analysis from the CLI:

```bash
python -m acceptance_checker.cli image1.bmp image2.tif
```

Export CSV:

```bash
python -m acceptance_checker.cli --csv result.csv *.bmp
```

Use multiple worker processes:

```bash
python -m acceptance_checker.cli --jobs 4 --csv result.csv *.bmp
```

Use a custom threshold file:

```bash
python -m acceptance_checker.cli --thresholds thresholds.default.json image.bmp
```

Choose 16-bit normalization:

```bash
python -m acceptance_checker.cli --normalize percentile image16.tif
```

CLI exit codes:

- `0`: analysis completed with no images scoring below the `FAIL` band.
- `1`: at least one image scored in the `FAIL` band.
- `2`: command usage, file IO, threshold loading, or analysis error.

## Python API

```python
from acceptance_checker import AcceptancePipeline, Thresholds

thresholds = Thresholds(mean_gray_fail=25, cnr_warn=4.0)
pipeline = AcceptancePipeline(thresholds)

result = pipeline.run("sample.bmp")

print(result.metrics.overall_status)
print(result.metrics.quality_score)
print(result.metrics.score_breakdown)
print(result.metrics.fail_reasons)
overlay = result.overlay
```

## Metrics

The analyzer records:

- Basic intensity: mean, standard deviation, min/max, P01/P99, histogram spread.
- Clipping: low and high clipping percentage.
- Uniformity: five-zone brightness means and min/max uniformity ratio.
- Noise: background standard deviation, robust noise sigma, and whole-image SNR.
- Defect proxy: automatic candidate count, sampled area, CNR, and contrast.
- Pattern proxy: vertical and horizontal stripe score.
- Sharpness proxy: Laplacian variance.

Default threshold fields are defined in `acceptance_checker/core/config.py` and mirrored in `thresholds.default.json`.

## Weighted Scoring

Each analyzed image receives a weighted score out of 100. Thresholds still define the per-metric bands, but they no longer act as a single-item veto:

- A metric in the pass band receives its full weight.
- A metric in the warning band receives half of its weight.
- A metric in the fail band receives 0 for that metric.
- If no automatic defect candidate is found, CNR is treated as a warning-band item because the image may be OK, but the tool cannot prove NG defect separation from automatic CNR alone.

Default weights:

| Metric | Weight |
| --- | ---: |
| Mean gray | 15 |
| Uniformity min/max | 15 |
| Low gray clipping | 10 |
| High gray clipping | 10 |
| Histogram spread P99-P01 | 10 |
| Automatic defect CNR | 20 |
| Whole-image SNR | 10 |
| Background std proxy | 5 |
| Sharpness Laplacian variance | 5 |

Score bands:

- `PASS`: score >= 80
- `WARNING`: 60 <= score < 80
- `FAIL`: score < 60

The text report, GUI status, batch table, quiet CLI output, and CSV export include both `quality_score` and `score_breakdown`.

## Validation

Run the core test suite:

```bash
pytest -q
```

Run lint:

```bash
ruff check acceptance_checker tests smoketest.py
```

Run type checking:

```bash
mypy acceptance_checker
```

Run the GUI smoke test headlessly:

```bash
python smoketest.py
```

On Linux CI, `QT_QPA_PLATFORM=offscreen` is used for the smoke test.

## Project Layout

```text
AcceptanceChecker/
  main.py                         GUI entry point
  smoketest.py                    end-to-end smoke test
  requirements.txt                runtime dependencies
  pyproject.toml                  package metadata and dev dependencies
  thresholds.default.json         default threshold JSON
  acceptance_checker/
    core/                         image loading, metrics, judging, pipeline
    reporting/                    text, CSV, and drift reports
    gui/                          PySide6 windows, workers, previews, ROI UI
    cli/                          batch command line interface
  tests/                          pytest suite
  .github/workflows/ci.yml        CI validation
```

## Packaging

Install the package locally:

```bash
pip install -e .
```

Build package artifacts when the `build` package is available:

```bash
python -m pip install build
python -m build
```

The console entry points declared in `pyproject.toml` are:

- `acceptance-checker`: GUI launcher.
- `acceptance-checker-cli`: batch CLI launcher.
