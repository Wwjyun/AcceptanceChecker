# AcceptanceChecker

AcceptanceChecker is a Python AOI raw-image acceptance tool. It analyzes inspection images, computes image-quality and defect metrics, scores each image on a weighted 100-point scale, and reports the production risk level for engineering review.

**Design philosophy — the score is a signal, not a gate.** In practice, an AOI image or batch almost always has to be accepted regardless of its score; rejecting it usually is not practically enforceable further downstream. So `quality_score` / `risk_level` are not designed to block anything — they exist to make it easy to (1) prioritize which engineering issue to fix first, (2) tell "barely bad" apart from "badly bad" at a glance, (3) keep a durable trail of scores and human override reasons across time, and (4) spot slow trend degradation across batches. See [Risk Communication Design](#risk-communication-design-score-as-signal-not-gate) for the concrete features that follow from this.

The project provides:

- A PySide6 desktop GUI whose default tab guides a formal v4 Session from manifest and evidence checks through measurement, ordered judgment, evidence-gap review, provenance, and report export.
- A composable formal CLI (`validate-manifest`, `measure`, `judge`, `report`) plus a clearly separated legacy quick-check CLI for single-image engineering analysis.
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

Run the GUI (it opens on the formal v4 Session workflow):

```bash
python main.py
```

Run the legacy image-score batch analysis. This is a **quick engineering check, not a
complete v4 acceptance**:

```bash
python -m acceptance_checker.cli quick-check image1.bmp image2.tif
```

Passing images directly remains supported for one compatibility version:

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

Attach a review note (why this batch was accepted despite a low score) and append every result to a cross-batch history log:

```bash
python -m acceptance_checker.cli --note "known low light rig, accepted" --history-log history.csv *.bmp
```

Treat exit code as informational only, e.g. in a pipeline stage that should never fail the build on image quality alone:

```bash
python -m acceptance_checker.cli --no-gate --csv result.csv *.bmp
```

CLI exit codes:

- `0`: analysis completed with no images in the high-risk score band, **or** `--no-gate` was passed.
- `1`: at least one image scored in the high-risk score band (`overall_status == "FAIL"`), and `--no-gate` was not passed.
- `2`: command usage, file IO, threshold loading, or analysis error — always returned regardless of `--no-gate`, because this is a real failure to analyze, not a quality judgement.

`--no-gate` does not change the report text, `risk_level`, or CSV output — it only changes whether exit code `1` is ever returned. Use it when the exit code is consumed by automation that should not fail a build/pipeline purely because an image scored low; keep the default behavior when a human or script genuinely wants to know "did anything fail" via the process exit code.

### Formal v4 CLI workflow

The formal workflow is composable, so every intermediate artifact can be reviewed or
recomputed:

```bash
python -m acceptance_checker.cli validate-manifest dataset_manifest.json
python -m acceptance_checker.cli measure dataset_manifest.json measurements.json --output session.json
python -m acceptance_checker.cli judge session.json --output judged-session.json
python -m acceptance_checker.cli report judged-session.json --write-config-template report-config.json
python -m acceptance_checker.cli report judged-session.json --config report-config.json --output-dir reports
```

`measurements.json` is the machine-readable output package from the formal G1–G6 measurers; it
contains `measurements` and optional `priority_events`. The command validates the dataset files
and hashes before importing those results. It never treats legacy `quality_score` values as v4
measurements. The report command requires the test object, optical declaration, improvements,
artifact manifest, and all three imaging/software/quality signoffs in its reviewed config.

For formal `judge` and `report`, `--no-gate` only changes the process exit code. The serialized
`OverallResult`, matched rule, reasons, and report wording remain byte-for-byte the same.

## Python API

```python
from acceptance_checker import AcceptancePipeline, Thresholds

thresholds = Thresholds(mean_gray_fail=25, cnr_warn=4.0)
pipeline = AcceptancePipeline(thresholds)

result = pipeline.run("sample.bmp")

print(result.metrics.overall_status)
print(result.metrics.risk_level)
print(result.metrics.quality_score)
print(result.metrics.score_breakdown)
print(result.metrics.fail_reasons)

# Optional: record why a low-scoring result was accepted anyway; flows into CSV and history log
result.metrics.review_note = "known low light rig, accepted"

overlay = result.overlay
```

To log this result into a cross-batch history file instead of (or in addition to) a one-off CSV:

```python
from acceptance_checker.reporting import HistoryLogger

HistoryLogger().append(result.metrics, "history.csv")
```

## v4 Acceptance Domain Model and Session Workflow

The formal v4 acceptance workflow is separate from the existing single-image weighted quick
check. Its domain and ordered workflow types are independent from Qt and OpenCV:

```python
from acceptance_checker import (
    AcceptanceManifest,
    AcceptanceSession,
    ImageLevel,
    MeasurementResult,
    MetricGroup,
    OpticalMode,
    Severity,
)

session = AcceptanceSession(
    manifest=AcceptanceManifest(
        machine_id="AOI-01",
        optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        spec_version="v4-draft",
    )
)
session.add_measurement(
    MeasurementResult(
        metric_id="g1.background_uniformity",
        group=MetricGroup.G1,
        severity=Severity.S2,
        value=0.88,
        unit="ratio",
        formula_version="v4-draft",
        image_level=ImageLevel.L1,
        roi_id="background",
        sample_count=1,
        evidence_sources=["images/frame-001.tif"],
    )
)

session.save_json("acceptance-session.json")
print(session.group_status_values())
```

An absent group or required measurement remains `NOT_EVALUATED`; it is never silently treated
as S3. `LegacyMetricsAdapter` can retain current `Metrics` values as traceable engineering
evidence, but marks every adapted value `NOT_EVALUATED` because the quick-check fields lack the
mode-specific ROI, raw-bit-depth, multi-image, or Golden evidence required by v4. The current
`quality_score`, `risk_level`, and `overall_status` therefore remain legacy engineering signals,
not formal v4 acceptance results.

The draft v4 metric catalog is packaged as
`acceptance_checker/specs/v4_draft.json`. It contains all 63 rows from the discussion workbook,
including mode applicability, units, displayed S3–S0 bands, machine-readable numeric rules,
evidence requirement profiles, formula identifiers, and S0 special-event notes:

```python
from acceptance_checker import OpticalMode, load_default_v4_spec

spec = load_default_v4_spec()
diffuse_metrics = spec.metrics_for_mode(OpticalMode.DIFFUSE_BRIGHT_FIELD)
severity = spec.get_metric("g1.diffuse.background_cv").classify(0.10)

print(spec.spec_version, len(spec.metrics), len(diffuse_metrics), severity.value)
```

The packaged profile is deliberately marked `draft_unapproved`. Pure numeric rules use
deterministic, non-overlapping boundaries; record-only and compound/qualitative rules refuse a
single-number classification. The source documents leave dark-field background mean from
2% through below 3% FS unclassified, so that interval is explicitly `NOT_EVALUATED` instead of
being guessed into a passing band. Loading rejects unsupported schema versions, missing rows,
duplicate metric IDs, invalid requirement profiles, and malformed numeric thresholds.

`V4AcceptanceJudge` implements the ordered decision table from v4 section 13.2. It checks the
five section 4.2 priority-event types first, then G5/G6 S0, multiple S0 groups, a single G1–G4
S0, any S1, and finally the accepted/conditionally-accepted rules. The returned `V4Decision`
includes the matched rule number, trigger groups and metric IDs, priority event types, and
missing evidence. Any `NOT_EVALUATED` group blocks rules 6 and 7.

## Metrics

The analyzer records:

- Basic intensity: mean, standard deviation, min/max, P01/P99, histogram spread.
- Clipping: low and high clipping percentage.
- Uniformity: five-zone brightness means and min/max uniformity ratio.
- Noise: background standard deviation, robust noise sigma, and a legacy single-image
  spatial SNR proxy (formal temporal SNR requires at least 30 aligned frames).
- Defect proxy: automatic candidate count, sampled area, CNR, and contrast.
- Pattern proxy: vertical and horizontal stripe score.
- Diagnostic proxies: robust single-image noise, directional stripe scores, and
  Laplacian variance. These remain legacy quick-check signals and never directly map
  to a v4 severity.
- Provenance / audit: `review_note` — optional free-text reason a human entered for why a result was accepted (see [Risk Communication Design](#risk-communication-design-score-as-signal-not-gate)).

`RawImage` now keeps two distinct planes:

- `raw_gray`: the original grayscale dtype and values used by formal `%FS` measurements.
- `gray8`: an independent preview/legacy-analysis plane used by the current detector and GUI.

For uint16 containers, pass the actual sensor bit depth when it is known:

```python
from acceptance_checker import RawImage

raw = RawImage.load("frame12.tif", bit_depth=12, normalization="percentile")
assert raw.full_scale == 4095

mean_pct_fs = float(raw.percent_of_full_scale().mean())  # reads raw_gray, not gray8
preview = raw.gray8                                      # may be percentile-stretched
```

Supported declared integer depths are 8/10/12/14/16. Values above the declared Full Scale,
NaN/Inf inputs, and `%FS` requests on float/min-max images are rejected instead of silently
inventing a formal measurement scale. `measurement_sample()` preserves the original dtype, while
`sample_box_to_original()` maps sampled coordinates back to the full-resolution image.

Default threshold fields are defined in `acceptance_checker/core/config.py` and mirrored in `thresholds.default.json`. Every `Metrics` field (including `review_note`) is written as a CSV column by `CsvExporter` and `HistoryLogger`, since both use `dataclasses.asdict()` — no per-field export code is needed.

## Weighted Scoring

Each analyzed image receives a weighted score out of 100. Thresholds still define the per-metric bands, but they no longer act as a single-item veto:

- A metric in the low-risk band receives its full weight.
- A metric in the observation band receives half of its weight.
- A metric in the high-risk band receives 0 for that metric.
- If no automatic defect candidate is found, CNR is treated as an observation-band item because the image may be OK, but automatic CNR alone does not provide enough evidence for NG defect separation.

### Metric ↔ threshold ↔ weight ↔ recommendation cross-reference

Use this table to trace any report line back to the threshold field that controls it, and to the recommendation text that would fire if it scores low. All threshold fields live in `Thresholds` (`acceptance_checker/core/config.py`); all weights live in `AcceptanceJudge.SCORE_WEIGHTS` (`acceptance_checker/core/judge.py`); all recommendation titles live in `RecommendationBuilder` (`acceptance_checker/reporting/recommendations.py`).

| Score label (judge.py) | Weight | Fail / warn threshold fields | Metric field(s) | Recommendation title (recommendations.py) |
| --- | ---: | --- | --- | --- |
| 平均灰階 | 15 | `mean_gray_fail` / `mean_gray_warn` | `mean_gray` | 整體亮度不足 |
| 均勻性 | 15 | `uniformity_fail` / `uniformity_warn` | `uniformity_ratio`, `zone_1..5_*_mean` | 分區均勻性不足 |
| 低灰階 clipping | 10 | `clipping_fail_pct` / `clipping_warn_pct` | `low_clip_pct` | 整體亮度不足 |
| 高灰階 clipping | 10 | `clipping_fail_pct` / `clipping_warn_pct` | `high_clip_pct` | 亮部 clipping 偏高 |
| 灰階展開 | 10 | `hist_spread_fail` / `hist_spread_warn` | `hist_spread_p99_p01` | 灰階動態範圍偏窄 |
| CNR | 20 | `cnr_fail` / `cnr_warn` | `auto_defect_cnr_est`, `auto_defect_count` | 缺陷 CNR 偏低 / 未找到自動候選缺陷 |
| Single-image spatial SNR proxy | 10 | `snr_fail` / `snr_warn` | `signal_to_noise_ratio` | 單張空間 SNR proxy 偏低 |
| 背景 std | 5 | `bg_std_fail` / `bg_std_warn` | `bg_std_est` | 背景雜訊或紋理偏高 |
| 清晰度 | 5 | `sharpness_fail` / `sharpness_warn` | `sharpness_laplacian_var` | 清晰度偏低 |

`RecommendationBuilder.build()` sorts the triggered recommendations by this same per-label deficit (`weight - points_awarded`), largest first, so the top of the "建議處置" report section is always the single item that cost the most points — the one an engineer should look at first, regardless of how many other items also triggered.

### Risk level tiers (`risk_level`, human-facing) vs. `overall_status` (internal/CLI)

`overall_status` (`PASS` / `WARNING` / `FAIL`) is the stable internal three-tier value that CLI exit codes and older integrations rely on — it is derived purely from `quality_score` and never changes shape:

- `PASS`: score >= 80 (`AcceptanceJudge.PASS_SCORE`)
- `WARNING`: 60 <= score < 80 (`AcceptanceJudge.WARNING_SCORE`)
- `FAIL`: score < 60

`risk_level` is a separate, human-facing string layered on top for reports/GUI. It refines the `FAIL` band into two tiers using `Thresholds.critical_score` (default `30.0`), so a batch of low scores can be triaged by severity instead of all looking identical:

| `risk_level` | Condition |
| --- | --- |
| `量產風險低` | `overall_status == "PASS"` |
| `量產觀察項` | `overall_status == "WARNING"` |
| `量產導入風險高` | `overall_status == "FAIL"` and `quality_score >= critical_score` |
| `量產導入風險極高` | `overall_status == "FAIL"` and `quality_score < critical_score` |

Lowering or raising `critical_score` (via `Thresholds(critical_score=...)`, a JSON threshold file, or the GUI threshold dialog) only moves the boundary between the two `FAIL`-band tiers — it never changes `overall_status`, `quality_score`, or the CLI exit code.

The text report, GUI status, batch table (row color, with `量產導入風險極高` shown in dark red vs. plain red for `量產導入風險高`), quiet CLI output, and CSV export all include `risk_level`, `quality_score`, and `score_breakdown`. High-risk and observation items are phrased as engineering production risks, such as exposure margin, field uniformity, clipping, defect separation, SNR, background noise, and focus stability.

## Risk Communication Design (score as signal, not gate)

Because rejection is not practically enforceable, the following features exist specifically to make a low score *useful* rather than just a label that gets overridden:

| Need | Feature | Where |
| --- | --- | --- |
| "Which issue do I fix first?" | Recommendations ranked by points lost, highest first | `reporting/recommendations.py` → `RecommendationBuilder._rank()` |
| "Is this a little bad or very bad?" | `risk_level` splits the `FAIL` band into 量產導入風險高 / 量產導入風險極高 via `critical_score` | `core/config.Thresholds.critical_score`, `core/judge.AcceptanceJudge._risk_level()` |
| "Is this production line's quality trending down over weeks?" | Append-only cross-batch history CSV (timestamp, file, `risk_level`, `quality_score`, `score_breakdown`, `review_note`, ...) | `reporting/history_log.HistoryLogger`, CLI `--history-log PATH`, GUI batch window "附加寫入歷史紀錄…" button |
| "Who decided to accept this, and why?" | Optional free-text `review_note` field, flows into CSV and history log | `core/metrics.Metrics.review_note`, CLI `--note "..."`, GUI note field in both the main window and batch window |
| "Should a low score ever fail an automated pipeline step?" | `--no-gate` makes exit code always `0` for quality judgements (read/IO errors still return `2`) | `cli/batch.py` |

None of these features change `overall_status`, the per-metric thresholds, or the weighted score itself — they are purely additive layers for prioritization, severity triage, historical traceability, and audit trail.

## v4 ROI and 16-zone measurements

Formal v4 ROI definitions live in `acceptance_checker.core.roi`. Every ROI records its
type, original-image coordinates, creation method, operator, version, applicable image,
and optional metadata. `RoiCollection` supports UTF-8 JSON and CSV import/export,
boundary and overlap checks, and fixed-recipe application across a batch. Imported ROI
coordinates are never interpreted as preview coordinates.

`measure_raw_16_zones()` divides the effective inspection width into exactly 16 zones
and reports each mean in `%FS`, together with `U = min / max` and the max-to-min
brightness difference divided by the mean of all 16 zones. GUI drag selection is also
converted from the sampled preview back to an auditable original-image ROI.

`G1Measurer` evaluates the complete mode-specific G1 set (10 diffuse, 9 specular, or
9 dark-field metrics) directly from the preserved measurement plane. It requires
explicit typed ROI evidence and marks unavailable formulas `NOT_EVALUATED`. Stray-light
measurement requires separate reference, blocked, and dark images; hotspot detection
uses the locked 30%FS/8-connected/50px definition; dark-field edge clipping uses every
Golden defect's 5px ring and emits an S0 priority event for a continuous 3px break.
Record-only values remain visible but do not incorrectly make a group incomplete.

## v4 dataset manifest and precondition lock

`PreconditionLock` validates the camera, optics, lighting, mechanics, environment,
sample, computation, and data categories required by the v4 specification. Every
recorded value participates in a canonical SHA-256 fingerprint; `partition_sessions()`
starts a new session whenever any locked value changes. A warm-up shorter than
30 minutes explicitly invalidates the dataset.

`build_dataset_manifest()` imports only metadata supplied by an unambiguous JSON or CSV
sidecar. It records each source-relative path, file SHA-256, byte size, nanosecond
mtime, image level, L1 calibration version, and sidecar path. Image level and
calibration identity are never inferred from pixel data or filenames. The saved
manifest includes its own integrity hash and rejects modified content when reloaded.

## v4 temporal and stability measurements

`TemporalAcceptanceMeasurer` consumes aligned L1 frames with one evidence source per
frame. It computes mean per-pixel temporal sigma and temporal SNR only when `N >= 30`,
plus repeatability CV, warm-reference drift at 30 minutes and 8 hours, five-cycle cold
restart reproducibility, balanced crossed random-effects ANOVA R&R with at least ten
handling/repositioning cycles, and temperature-window drift. Temperature evidence must
cover seven continuous days with no gap over six hours; otherwise an apparently good
numeric result is capped at S1.

The legacy single-image `signal_to_noise_ratio` field remains for compatibility, but
all user-facing labels identify it as a spatial SNR proxy. `DriftReporter` now uses
relative drift from the first image with dedicated drift thresholds and no longer
borrows histogram-spread thresholds.

## v4 traceability validation

`TraceabilityValidator` checks every image for the ten §11.1 required categories:
millisecond timestamp, camera identity, scan batch/sequence, actual exposure/gain/line
rate, actual light setting, L1 calibration and image level, sample and orientation,
scan speed and encoder origin, and file SHA-256. Missing or inconsistent required data
is S1. Camera mismatch, conflicting sequence/timestamp pairing, or a sidecar declaring
another source image is S0. Optional environment/operator fields produce warnings only.

The G5 traceability result carries `session_id`, `spec_version`, and `manifest_hash`.
Those keys are also preserved by session JSON, legacy-compatible CSV export, and the
append-only history log.

## v4 G2 resolution and scan geometry

`G2Measurer` produces all seven G2 metrics from versioned target evidence. Its
slanted-edge path validates 20%FS minimum contrast and a 2–15° edge angle, constructs
a 4× oversampled ESF, differentiates to an apodized LSF, and samples the normalized
FFT at 0.25 cycles/pixel (Nyquist/2) in both scan and sensor directions. The same ESF
provides a locked 10–90% scan-edge blur extent.

Minimum-defect width is the worst connected component's distance-transform width;
contour clarity is the boundary-gradient P10 in %FS/pixel, with an unclear contour
forced to S0. Scale asymmetry and worst field error require versioned left/center/right
(and stitch when applicable) calibration evidence. Encoder synchronization uses the
P95 absolute deviation from the median and refuses fewer than 100 scans.

## v4 G3 noise and sensor measurements

`G3Measurer` produces all six G3 metrics from explicit evidence. DSNU uses the
spatial standard deviation of an averaged dark L0 stack with at least 30 frames.
PRNU subtracts the dark response and removes the per-pixel temporal variance
contribution before normalizing by the mean response. Vertical FPN uses column
means after averaging at least 100 uniform L0 frames.

The remaining checks reuse the formal temporal SNR measurement, compare current
L1 spatial standard deviation against an approved Golden value, and classify
new bad or hot pixels by count, Golden-defect overlap, effective inspection
area, and versioned fixed-mask coordinates. Missing acquisition evidence,
unapproved Golden data, insufficient frames, or unmasked pixels inside the
effective inspection area are reported as not evaluated instead of inferred.
Legacy robust-noise, stripe-score, and Laplacian-variance values remain
diagnostic proxies and do not directly determine a v4 grade.

## v4 G5 integrity and stitching measurements

`G5Measurer` produces all eight G5 metrics from versioned contracts, acquisition
evidence, seam targets, equivalent camera ROIs, and the dataset manifest. Image
dimensions and bit depth are checked per source file, while scan sequence
collisions retain both source names. Missing or duplicate lines and dropped,
duplicated, or interrupted frames are derived only from an acquisition log or
encoder/timestamp identifiers; an absent log is never interpreted as zero.

For multi-camera systems, the measurer reports symmetric seam brightness
difference, worst matched-feature position residual, maximum uncovered width,
and the worst equivalent-ROI gray difference. Any seam blind zone of at least
one pixel is S0 and also forces the seam-brightness result to S0 regardless of
its numeric value. A versioned single-camera architecture declaration supplies
an explicit not-applicable result instead of silently skipping stitch checks.
The existing `TraceabilityValidator` supplies the eighth G5 result.

## v4 approved Golden catalogs

Formal G6 evidence uses `GoldenCatalog`, an approved, versioned catalog whose NG
records include defect type, physical and pixel dimensions, effective width,
direction, polarity, position, full-width region, defect ROI, local background
ring, batch, orientation, image source, and SHA-256. PASS records cannot carry
defect labels. The append-only `GoldenCatalogRepository` stores every version at
`<catalog-id>/<version>.json` and refuses to overwrite a referenced baseline.

Production detector decisions are imported separately through
`DetectorResultSet`. Every row retains detector, detector version, decision-rule
version, threshold, score, decision, capture-attempt count, and import source,
and must exactly cover the catalog version's sample IDs. The legacy automatic
candidate detector is therefore kept outside formal G6 evidence.

`G6Measurer` consumes those two approved evidence sets and emits all eight G6
metrics. Defect CNR and native-gray contrast are measured from each stored
defect ROI and its ring; bright and dark polarities are reported separately and
the worse CNR controls the grade. NG results retain detection numerator,
denominator, Wilson interval, worst threshold margin, retry count, and stable
miss IDs. Sample counts and required-type coverage are evaluated independently.

PASS false-positive results retain the same ratio fields and require at least
200 samples before S3 or S2 is possible. The exact 95% one-sided
Clopper–Pearson upper bound is a separate metric. Full-width consistency covers
left, center, right, and stitch regions with per-region ratios and intervals.
A stable NG miss, an approved effective defect width below two pixels, or an
evidence-backed unrecognizable minimum defect produces an S0 priority event.

## v4 responsibility and appendix-B diagnostics

`ResponsibilityAnalyzer` orders remediation by failed group and section 14
ownership. Any G1–G5 S1/S0 explicitly prohibits L2 acceptance remedies and
keeps software in a measurement/analysis role until upstream capability is
repaired. Section 14.1 S2-to-G6 links are emitted only as
`presumed_pending_three_party_confirmation`; they never replace imaging,
software, and quality confirmation or diagnostic evidence. Written technical
objections, three-party positions, and hashed appendix-B attachments remain
alongside the recommendation.

`LogLogAnalyzer` implements the appendix-B single-variable brightness test. It
requires at least five unique positive brightness points and at least 30
spatial-STD and 30 temporal-noise observations per point, keeps the two signals
separate, fits `y = a × brightness^b`, reports `a`, exponent `b`, and R², and
exports an auditable SVG regression graph.

## v4 written waiver workflow

`Waiver` preserves the original rejected/fatal result, failed metric snapshots,
four required risk statements, responsible owner, hardware completion date,
target terms, explicit software best-effort acknowledgement, and signed
approval levels. A waiver lasts at most 90 days and is always displayed as
active-but-not-accepted; expiry or invalidation restores the original result.

G1–G4 S0 waivers require imaging-system and requirements managers jointly.
G5/G6 S0 starts one level higher. Each of the two permitted extensions raises
the approval level; the second extension (third submission) also requires an
alternative architecture/equipment/scope plan. Any newly observed S0
immediately invalidates the waiver. `WaiverTrackingReport` records 30-day
hardware progress, remaining work, actual misses/false calls, current metrics,
new S1/S0 items, and evidence; overdue tracking removes extension eligibility.

## v4 formal acceptance report

`FormalAcceptanceReport` implements all nine section 16.1 chapters: test object,
optical declaration, precondition lock, G1–G6 measurements, ordered decision,
appendix-B diagnosis, responsibility, prioritized improvements, and the raw-data
manifest. Every metric row retains value, grade, group, formula and formula
version, ROI, measurement date, image level, sample count, evidence paths, and
missing reason. Evidence paths must appear in the report's hashed image,
parameter, and script artifact list before export is allowed.

The report exports machine-readable JSON, styled HTML, and a paginated PDF with
Traditional-Chinese font embedding, repeated measurement-table headers,
appendix-B regression charts and exponents, page headers/footers, and all three
signoffs. Dissenting opinions are preserved beside the signatures. CSV remains
a detail export only. Every formal report carries the immutable statement that
its thresholds are internal engineering control limits, not ISO-mandated
acceptance thresholds.

### v4 verification assets

- `tests/data/excel_control_rows.json` is a read-only extraction of workbook sheet
  `01_卡控總表!A6:H68`, including the source workbook SHA-256. A traceability test compares all
  63 row names, groups, modes, and S3–S0 display bands to the packaged spec.
- `tests/data/synthetic_scenarios.json` declares deterministic coverage for all three optical
  modes, 8/10/12/14/16-bit inputs, temporal noise and drift, hotspot, shadow, stitching,
  acquisition loss, and Golden miss paths.
- `tests/data/golden_regression_manifest.json` stores only the deidentified automated-regression
  manifest and hashes; its 30 NG / 200 PASS generated catalog and detector-result payloads are
  not committed as large artifacts and are recreated deterministically in tests.
- `acceptance_checker/schemas/formal_report_v1.schema.json` is the JSON Schema contract for
  formal report schema `1.0`; snapshot and Draft 2020-12 validation tests protect compatibility.

Run the default large Line Scan / 30-frame temporal benchmark:

```bash
python benchmarks/benchmark_line_scan.py
```

The benchmark reports shapes, input bytes, elapsed time, Python-tracked peak memory,
16-zone uniformity, and temporal SNR. Dimensions are configurable from the command line.

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
    reporting/                    text, CSV, drift, recommendation, and history-log reports
      history_log.py              cross-batch/cross-time score history CSV (HistoryLogger)
      recommendations.py          engineering recommendations, ranked by points lost
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
