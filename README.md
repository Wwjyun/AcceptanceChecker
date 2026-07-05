# AcceptanceChecker

AcceptanceChecker is a Python AOI raw-image acceptance tool. It analyzes inspection images, computes image-quality and defect metrics, and classifies each image as `PASS`, `WARNING`, or `FAIL`.

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

- `0`: analysis completed with no `FAIL` results.
- `1`: at least one image was classified as `FAIL`.
- `2`: command usage, file IO, threshold loading, or analysis error.

## Python API

```python
from acceptance_checker import AcceptancePipeline, Thresholds

thresholds = Thresholds(mean_gray_fail=25, cnr_warn=4.0)
pipeline = AcceptancePipeline(thresholds)

result = pipeline.run("sample.bmp")

print(result.metrics.overall_status)
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
