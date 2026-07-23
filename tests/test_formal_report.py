import json

import pytest

from acceptance_checker import (
    AcceptanceManifest,
    AcceptanceSession,
    BrightnessPoint,
    FormalAcceptanceReport,
    ImageLevel,
    ImprovementAction,
    LogLogAnalyzer,
    MeasurementResult,
    MetricGroup,
    OpticalDeclaration,
    OpticalMode,
    ReportArtifact,
    ReportSignoff,
    ResponsibilityAnalyzer,
    ReviewParty,
    Severity,
    V4AcceptanceJudge,
)
from acceptance_checker import (
    TestObject as ReportTestObject,
)
from tests.test_traceability import lock


def build_report(tmp_path):
    image = tmp_path / "image.raw"
    parameter = tmp_path / "parameters.json"
    script = tmp_path / "measure.py"
    image.write_bytes(b"raw-image")
    parameter.write_text("{}", encoding="utf-8")
    script.write_text("print('measure')\n", encoding="utf-8")
    artifacts = [
        ReportArtifact.from_file("image", str(image)),
        ReportArtifact.from_file("parameter", str(parameter), version="manifest-1"),
        ReportArtifact.from_file("script", str(script), version="git-abc"),
    ]
    manifest = AcceptanceManifest(
        machine_id="AOI-1",
        optical_mode=OpticalMode.DIFFUSE_BRIGHT_FIELD,
        session_id="session-1",
        spec_version="v4-discussion-2026-07-23",
        precondition_lock=lock(),
        manifest_hash="f" * 64,
    )
    session = AcceptanceSession(
        manifest=manifest,
        measurements=[
            MeasurementResult(
                metric_id="g1.diffuse.background_cv",
                group=MetricGroup.G1,
                severity=Severity.S2,
                unit="ratio",
                formula_version="v4-formula-1",
                image_level=ImageLevel.L1,
                value=0.1,
                roi_id="background-1",
                sample_count=100,
                evidence_sources=[str(image), str(parameter), str(script)],
                metadata={"measured_at": "2026-07-23T10:00:00+08:00"},
            )
        ],
    )
    decision = V4AcceptanceJudge().judge(session)
    responsibility = ResponsibilityAnalyzer().analyze(session)
    diagnostic = LogLogAnalyzer().analyze(
        experiment_id="brightness-sweep",
        points=[
            BrightnessPoint(
                brightness=value,
                spatial_std_samples=[2 * value**0.5] * 30,
                temporal_noise_samples=[3 * value**0.25] * 30,
                evidence_source=str(parameter),
            )
            for value in (10, 20, 40, 80, 160)
        ],
        fixed_conditions={"gain": 1, "exposure_us": 100, "sample": "golden"},
    )
    return FormalAcceptanceReport(
        report_id="RPT-001",
        report_schema_version="1.0",
        created_at="2026-07-23T12:00:00+08:00",
        measurement_date="2026-07-23T10:00:00+08:00",
        test_object=ReportTestObject("AOI-1", "Line-1", "metal surface", "1200 mm"),
        optical_declaration=OpticalDeclaration(
            "diffuse_bright_field",
            [str(image)],
            {"light_deg": 30, "camera_deg": 0},
        ),
        precondition_lock=lock(),
        session=session,
        decision=decision,
        responsibility=responsibility,
        diagnostics=[diagnostic],
        improvements=[
            ImprovementAction(1, "Optics", "improve uniformity", "2026-08-15")
        ],
        artifacts=artifacts,
        signoffs=[
            ReportSignoff(
                ReviewParty.IMAGING,
                "Imaging Owner",
                "reviewed",
                "2026-07-23T13:00:00+08:00",
            ),
            ReportSignoff(
                ReviewParty.SOFTWARE,
                "Software Owner",
                "reviewed with dissent",
                "2026-07-23T13:01:00+08:00",
                "S2 mechanism remains a hypothesis until appendix-B data is complete.",
            ),
            ReportSignoff(
                ReviewParty.QUALITY,
                "Quality Owner",
                "reviewed",
                "2026-07-23T13:02:00+08:00",
            ),
        ],
    )


def test_structured_report_has_nine_sections_measurement_provenance_and_dissent(
    tmp_path,
):
    report = build_report(tmp_path)
    data = report.to_dict()

    assert [item["number"] for item in data["sections"]] == list(range(1, 10))
    measurement = data["sections"][3]["content"][0]
    assert measurement["formula"] == "spatial_std_over_mean"
    assert measurement["roi_id"] == "background-1"
    assert measurement["severity"] == "S2"
    assert measurement["evidence_sources"]
    assert data["dissenting_opinions"][0]["party"] == "software"
    assert "內部工程管制線" in data["disclaimer"]
    assert data["sections"][5]["content"][0]["spatial_fit"][
        "exponent_b"
    ] == pytest.approx(0.5)


def test_report_exports_machine_json_html_and_pdf(tmp_path):
    report = build_report(tmp_path)
    json_path = tmp_path / "report.json"
    html_path = tmp_path / "report.html"
    pdf_path = tmp_path / "report.pdf"

    report.save_json(str(json_path))
    report.save_html(str(html_path))
    report.save_pdf(str(pdf_path))

    assert json.loads(json_path.read_text(encoding="utf-8"))["report_schema_version"] == "1.0"
    html_text = html_path.read_text(encoding="utf-8")
    assert html_text.count("<section>") == 10
    assert "ISO 強制門檻" in html_text
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert pdf_path.stat().st_size > 10_000
