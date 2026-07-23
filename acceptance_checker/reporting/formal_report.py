# -*- coding: utf-8 -*-
"""Structured v4 acceptance report with JSON, HTML, and PDF exports."""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from acceptance_checker.core.dataset_manifest import PreconditionLock
from acceptance_checker.core.loglog_analysis import LogLogAnalysisResult
from acceptance_checker.core.release_readiness import evaluate_release_readiness
from acceptance_checker.core.responsibility import (
    ResponsibilityReport,
    ReviewParty,
)
from acceptance_checker.core.specification import (
    V4Specification,
    load_default_v4_spec,
)
from acceptance_checker.core.v4_domain import AcceptanceSession
from acceptance_checker.core.v4_judge import V4Decision
from acceptance_checker.versions import FORMAL_REPORT_SCHEMA_VERSION


class FormalReportError(ValueError):
    """Raised when a formal report is incomplete or cannot be rendered."""


INTERNAL_CONTROL_DISCLAIMER = (
    "本報告使用專案內部工程管制線；引用 ISO／EMVA 方法學不代表這些 "
    "S0～S3 數值為 ISO 強制門檻。"
)


@dataclass(frozen=True)
class TestObject:
    machine_id: str
    production_line: str
    inspection_object: str
    full_inspection_width: str

    def __post_init__(self) -> None:
        if not all(asdict(self).values()):
            raise FormalReportError("test-object fields cannot be empty")


@dataclass(frozen=True)
class OpticalDeclaration:
    mode: str
    light_path_diagrams: Sequence[str]
    angles: Dict[str, Any]

    def __post_init__(self) -> None:
        if not self.mode or not self.light_path_diagrams or not self.angles:
            raise FormalReportError(
                "optical mode, light-path diagram, and angles are required"
            )


@dataclass(frozen=True)
class ReportArtifact:
    kind: str
    path: str
    sha256: str
    version: str = ""

    def __post_init__(self) -> None:
        if not self.kind or not self.path:
            raise FormalReportError("artifact kind and path are required")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise FormalReportError("artifact SHA-256 must be 64 lowercase hex digits")

    @classmethod
    def from_file(cls, kind: str, path: str, *, version: str = "") -> "ReportArtifact":
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return cls(kind, path, digest.hexdigest(), version)


@dataclass(frozen=True)
class ReportSignoff:
    party: ReviewParty
    representative: str
    decision: str
    signed_at: str
    dissent: str = ""

    def __post_init__(self) -> None:
        if not self.representative or not self.decision or not self.signed_at:
            raise FormalReportError("signoff identity, decision, and time are required")
        try:
            datetime.fromisoformat(self.signed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FormalReportError("signoff time must be ISO-8601") from exc


@dataclass(frozen=True)
class ImprovementAction:
    priority: int
    owner: str
    action: str
    due_date: str

    def __post_init__(self) -> None:
        if self.priority < 1 or not self.owner or not self.action or not self.due_date:
            raise FormalReportError("improvement action fields cannot be empty")


@dataclass
class FormalAcceptanceReport:
    report_id: str
    report_schema_version: str
    created_at: str
    measurement_date: str
    test_object: TestObject
    optical_declaration: OpticalDeclaration
    precondition_lock: PreconditionLock
    session: AcceptanceSession
    decision: V4Decision
    responsibility: ResponsibilityReport
    improvements: Sequence[ImprovementAction]
    artifacts: Sequence[ReportArtifact]
    signoffs: Sequence[ReportSignoff]
    diagnostics: Sequence[LogLogAnalysisResult] = field(default_factory=list)
    specification: V4Specification = field(default_factory=load_default_v4_spec)
    disclaimer: str = INTERNAL_CONTROL_DISCLAIMER

    def __post_init__(self) -> None:
        if not self.report_id or not self.report_schema_version:
            raise FormalReportError("report id and schema version are required")
        if self.report_schema_version != FORMAL_REPORT_SCHEMA_VERSION:
            raise FormalReportError(
                "unsupported formal report schema version: "
                f"{self.report_schema_version}"
            )
        for value, label in (
            (self.created_at, "created_at"),
            (self.measurement_date, "measurement_date"),
        ):
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise FormalReportError(f"{label} must be ISO-8601") from exc
        if self.session.manifest.machine_id != self.test_object.machine_id:
            raise FormalReportError("report machine id differs from session manifest")
        if self.session.manifest.spec_version != self.specification.spec_version:
            raise FormalReportError("session and report specification versions differ")
        if self.decision.result != self.session.overall_result:
            raise FormalReportError("decision result differs from the finalized session")
        parties = {item.party for item in self.signoffs}
        if parties != set(ReviewParty):
            raise FormalReportError("imaging, software, and quality signoffs are required")
        if not self.improvements:
            raise FormalReportError("formal report requires prioritized improvements")
        artifact_kinds = {item.kind for item in self.artifacts}
        if not {"image", "parameter", "script"} <= artifact_kinds:
            raise FormalReportError(
                "raw-data chapter requires image, parameter, and script artifacts"
            )
        artifact_paths = {item.path for item in self.artifacts}
        missing_evidence = sorted(
            {
                source
                for measurement in self.session.measurements
                for source in measurement.evidence_sources
                if source not in artifact_paths
            }
            | {
                source
                for diagnostic in self.diagnostics
                for source in diagnostic.evidence_sources
                if source not in artifact_paths
            }
        )
        if missing_evidence:
            raise FormalReportError(
                "measurement evidence is absent from artifact manifest: "
                + ", ".join(missing_evidence)
            )
        if self.disclaimer != INTERNAL_CONTROL_DISCLAIMER:
            raise FormalReportError("formal internal-control disclaimer cannot be altered")

    def _measurement_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in self.session.measurements:
            try:
                spec = self.specification.get_metric(item.metric_id)
                formula = spec.formula
            except KeyError:
                formula = item.metadata.get("formula", "external/formal measurement")
            rows.append(
                {
                    "metric_id": item.metric_id,
                    "group": item.group.value,
                    "value": item.value,
                    "unit": item.unit,
                    "severity": item.severity.value,
                    "formula": formula,
                    "formula_version": item.formula_version,
                    "roi_id": item.roi_id,
                    "measurement_date": item.metadata.get(
                        "measured_at", self.measurement_date
                    ),
                    "image_level": item.image_level.value,
                    "sample_count": item.sample_count,
                    "evidence_sources": list(item.evidence_sources),
                    "missing_reason": item.missing_reason,
                }
            )
        return rows

    def to_dict(self) -> Dict[str, Any]:
        diagnostic_rows = [
            {
                "experiment_id": item.experiment_id,
                "controlled_variable": item.controlled_variable,
                "fixed_conditions": item.fixed_conditions,
                "spatial_fit": _primitive(item.spatial_fit),
                "temporal_fit": _primitive(item.temporal_fit),
                "evidence_sources": item.evidence_sources,
            }
            for item in self.diagnostics
        ]
        decision_content = _primitive(self.decision)
        readiness = evaluate_release_readiness(self.specification)
        decision_content.update(
            {
                "specification_status": self.specification.status,
                "official_v4_support": readiness.official_v4_support,
                "support_status": readiness.status,
                "release_readiness_reasons": list(readiness.reasons),
            }
        )
        sections = [
            {"number": 1, "title": "受驗標的", "content": _primitive(self.test_object)},
            {
                "number": 2,
                "title": "取像模式宣告",
                "content": _primitive(self.optical_declaration),
            },
            {
                "number": 3,
                "title": "量測前提鎖定表",
                "content": self.precondition_lock.to_dict(),
            },
            {
                "number": 4,
                "title": "各群組實測值與分級",
                "content": self._measurement_rows(),
            },
            {
                "number": 5,
                "title": "整體判定",
                "content": decision_content,
            },
            {"number": 6, "title": "成因診斷", "content": diagnostic_rows},
            {
                "number": 7,
                "title": "責任歸屬",
                "content": _primitive(self.responsibility),
            },
            {
                "number": 8,
                "title": "改善建議與優先序",
                "content": _primitive(self.improvements),
            },
            {
                "number": 9,
                "title": "原始資料",
                "content": _primitive(self.artifacts),
            },
        ]
        return {
            "report_schema_version": self.report_schema_version,
            "report_id": self.report_id,
            "created_at": self.created_at,
            "measurement_date": self.measurement_date,
            "specification_version": self.specification.spec_version,
            "formula_version": self.specification.formula_version,
            "session_id": self.session.manifest.session_id,
            "manifest_hash": self.session.manifest.manifest_hash,
            "disclaimer": self.disclaimer,
            "sections": sections,
            "signoffs": _primitive(self.signoffs),
            "dissenting_opinions": [
                {
                    "party": item.party.value,
                    "representative": item.representative,
                    "opinion": item.dissent,
                }
                for item in self.signoffs
                if item.dissent
            ],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    def save_json(self, path: str) -> None:
        Path(path).write_text(self.to_json() + "\n", encoding="utf-8")

    def to_html(self) -> str:
        data = self.to_dict()
        sections = []
        for section in data["sections"]:
            number = section["number"]
            title = html.escape(section["title"])
            if number == 4:
                content = _measurement_html(section["content"])
            elif number == 6:
                content = "".join(
                    (
                        f"<h3>{html.escape(item.experiment_id)}</h3>"
                        f"<p>Spatial b={item.spatial_fit.exponent_b:.5f}, "
                        f"R²={item.spatial_fit.r_squared:.5f}; "
                        f"Temporal b={item.temporal_fit.exponent_b:.5f}, "
                        f"R²={item.temporal_fit.r_squared:.5f}</p>"
                        + item.to_svg()
                    )
                    for item in self.diagnostics
                ) or (
                    "<p>No completed appendix-B experiment; "
                    "causal statements remain hypotheses.</p>"
                )
            else:
                content = (
                    "<pre>"
                    + html.escape(
                        json.dumps(section["content"], ensure_ascii=False, indent=2)
                    )
                    + "</pre>"
                )
            sections.append(f"<section><h2>{number}. {title}</h2>{content}</section>")
        signoff_rows = "".join(
            "<tr>"
            f"<td>{html.escape(item.party.value)}</td>"
            f"<td>{html.escape(item.representative)}</td>"
            f"<td>{html.escape(item.decision)}</td>"
            f"<td>{html.escape(item.signed_at)}</td>"
            f"<td>{html.escape(item.dissent)}</td>"
            "</tr>"
            for item in self.signoffs
        )
        return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>{html.escape(self.report_id)} - 取像品質驗收報告</title>
<style>
body{{font-family:"Microsoft JhengHei",sans-serif;margin:32px;color:#17202a}}
h1{{border-bottom:3px solid #245c84;padding-bottom:10px}} h2{{color:#245c84}}
.notice{{background:#fff3cd;border:1px solid #e0b84f;padding:12px;font-weight:bold}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th,td{{border:1px solid #aaa;padding:6px;vertical-align:top}}
th{{background:#e9f1f7}} pre{{white-space:pre-wrap;background:#f5f7f8;padding:12px}}
footer{{margin-top:32px;color:#555;font-size:12px}}
</style></head><body>
<h1>取像品質驗收報告</h1>
<p>Report ID: {html.escape(self.report_id)} | Spec: {html.escape(self.specification.spec_version)}
| Session: {html.escape(self.session.manifest.session_id)}</p>
<div class="notice">{html.escape(self.disclaimer)}</div>
{''.join(sections)}
<section><h2>三方會簽與並列意見</h2>
<table><thead><tr><th>單位</th><th>代表</th><th>決定</th><th>時間</th><th>不同意見</th></tr></thead>
<tbody>{signoff_rows}</tbody></table></section>
<footer>Schema {html.escape(self.report_schema_version)} |
Generated {html.escape(self.created_at)}</footer>
</body></html>"""

    def save_html(self, path: str) -> None:
        Path(path).write_text(self.to_html(), encoding="utf-8")

    def save_pdf(self, path: str, *, font_path: Optional[str] = None) -> None:
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import (
                PageBreak,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as exc:
            raise FormalReportError("PDF export requires reportlab") from exc

        selected_font = font_path or _find_report_font()
        font_name = "V4ReportFont"
        try:
            pdfmetrics.registerFont(TTFont(font_name, selected_font))
        except Exception as exc:
            raise FormalReportError(f"cannot load PDF font {selected_font}: {exc}") from exc

        styles = getSampleStyleSheet()
        title = ParagraphStyle(
            "V4Title",
            parent=styles["Title"],
            fontName=font_name,
            fontSize=20,
            leading=25,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#183b56"),
        )
        heading = ParagraphStyle(
            "V4Heading",
            parent=styles["Heading2"],
            fontName=font_name,
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#245c84"),
            spaceBefore=8,
            spaceAfter=6,
        )
        body = ParagraphStyle(
            "V4Body",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=8.5,
            leading=12,
        )
        small = ParagraphStyle(
            "V4Small",
            parent=body,
            fontSize=7,
            leading=9,
        )
        document = SimpleDocTemplate(
            path,
            pagesize=landscape(A4),
            leftMargin=14 * mm,
            rightMargin=14 * mm,
            topMargin=16 * mm,
            bottomMargin=15 * mm,
            title="取像品質驗收報告",
            author="AcceptanceChecker",
        )
        story = [
            Paragraph("取像品質驗收報告", title),
            Spacer(1, 5 * mm),
            Paragraph(
                f"Report ID: {_xml(self.report_id)} | "
                f"Spec: {_xml(self.specification.spec_version)} | "
                f"Session: {_xml(self.session.manifest.session_id)}",
                body,
            ),
            Spacer(1, 3 * mm),
            Table(
                [[Paragraph(_xml(self.disclaimer), body)]],
                colWidths=[260 * mm],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff3cd")),
                        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d6a600")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                ),
            ),
            Spacer(1, 4 * mm),
        ]
        report_data = self.to_dict()
        for section in report_data["sections"]:
            story.append(
                Paragraph(f"{section['number']}. {_xml(section['title'])}", heading)
            )
            if section["number"] == 4:
                story.append(_measurement_pdf_table(section["content"], small, font_name))
            elif section["number"] == 6:
                if self.diagnostics:
                    for diagnostic in self.diagnostics:
                        story.extend(
                            [
                                Paragraph(_xml(diagnostic.experiment_id), body),
                                Paragraph(
                                    (
                                        f"Spatial b={diagnostic.spatial_fit.exponent_b:.5f}, "
                                        f"R²={diagnostic.spatial_fit.r_squared:.5f}; "
                                        f"Temporal b={diagnostic.temporal_fit.exponent_b:.5f}, "
                                        f"R²={diagnostic.temporal_fit.r_squared:.5f}"
                                    ),
                                    small,
                                ),
                                _diagnostic_pdf_chart(diagnostic),
                            ]
                        )
                else:
                    story.append(
                        Paragraph(
                            "No completed appendix-B experiment; causal statements "
                            "remain hypotheses.",
                            body,
                        )
                    )
            else:
                pretty = json.dumps(section["content"], ensure_ascii=False, indent=2)
                story.append(Paragraph(_xml(pretty).replace("\n", "<br/>"), small))
            if section["number"] in {3, 5}:
                story.append(PageBreak())
            else:
                story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("三方會簽與並列意見", heading))
        signoff_data = [["單位", "代表", "決定", "時間", "不同意見"]]
        signoff_data.extend(
            [
                item.party.value,
                item.representative,
                item.decision,
                item.signed_at,
                item.dissent,
            ]
            for item in self.signoffs
        )
        story.append(
            Table(
                [
                    [Paragraph(_xml(str(cell)), small) for cell in row]
                    for row in signoff_data
                ],
                colWidths=[35 * mm, 38 * mm, 45 * mm, 52 * mm, 90 * mm],
                repeatRows=1,
                style=_pdf_table_style(font_name, colors),
            )
        )

        def page_decor(canvas, doc) -> None:
            canvas.saveState()
            canvas.setFont(font_name, 7)
            canvas.setFillColor(colors.HexColor("#666666"))
            canvas.drawString(
                14 * mm,
                landscape(A4)[1] - 9 * mm,
                f"Acceptance Report | {self.report_id}",
            )
            canvas.drawString(14 * mm, 8 * mm, self.report_id)
            canvas.drawRightString(
                landscape(A4)[0] - 14 * mm,
                8 * mm,
                f"Page {doc.page}",
            )
            canvas.restoreState()

        document.build(story, onFirstPage=page_decor, onLaterPages=page_decor)


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _primitive(asdict(value))
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_primitive(item) for item in value]
    return value


def _measurement_html(rows: Sequence[Dict[str, Any]]) -> str:
    headers = (
        "Metric",
        "Group",
        "Value",
        "Grade",
        "Formula",
        "ROI",
        "Date",
        "Evidence",
    )
    body = []
    for row in rows:
        values = (
            row["metric_id"],
            row["group"],
            f"{row['value']} {row['unit']}",
            row["severity"],
            f"{row['formula']} ({row['formula_version']})",
            row["roi_id"],
            row["measurement_date"],
            ", ".join(row["evidence_sources"]),
        )
        body.append(
            "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in values) + "</tr>"
        )
    return (
        "<table><thead><tr>"
        + "".join(f"<th>{item}</th>" for item in headers)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _measurement_pdf_table(rows, style, font_name):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import LongTable, Paragraph

    data = [["Metric", "G", "Value", "S", "Formula", "ROI / Date", "Evidence"]]
    for row in rows:
        data.append(
            [
                _xml(str(row["metric_id"])),
                _xml(str(row["group"])),
                _xml(f"{row['value']} {row['unit']}"),
                _xml(str(row["severity"])),
                _xml(f"{row['formula']} ({row['formula_version']})"),
                (
                    _xml(str(row["roi_id"]))
                    + "<br/>"
                    + _xml(str(row["measurement_date"]))
                ),
                (
                    "<br/>".join(
                        _xml(str(item)) for item in row["evidence_sources"]
                    )
                    or _xml(str(row["missing_reason"]))
                ),
            ]
        )
    return LongTable(
        [[Paragraph(str(cell), style) for cell in row] for row in data],
        colWidths=[46 * mm, 11 * mm, 32 * mm, 11 * mm, 55 * mm, 40 * mm, 65 * mm],
        repeatRows=1,
        style=_pdf_table_style(font_name, colors),
    )


def _pdf_table_style(font_name, colors):
    from reportlab.platypus import TableStyle

    return TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceaf4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#183b56")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa9b5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def _diagnostic_pdf_chart(result: LogLogAnalysisResult):
    from reportlab.graphics.shapes import Circle, Drawing, Line, String
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm

    width = 240 * mm
    height = 72 * mm
    left = 18 * mm
    bottom = 12 * mm
    right = width - 8 * mm
    top = height - 8 * mm
    log_x = [math.log10(value) for value in result.brightness]
    log_y = [
        math.log10(value)
        for value in [*result.spatial_std, *result.temporal_noise]
    ]
    x_min, x_max = min(log_x), max(log_x)
    y_min, y_max = min(log_y), max(log_y)

    def px(value: float) -> float:
        return left + (math.log10(value) - x_min) / (x_max - x_min) * (
            right - left
        )

    def py(value: float) -> float:
        return bottom + (math.log10(value) - y_min) / (y_max - y_min) * (
            top - bottom
        )

    drawing = Drawing(width, height)
    drawing.add(Line(left, bottom, right, bottom, strokeColor=HexColor("#333333")))
    drawing.add(Line(left, bottom, left, top, strokeColor=HexColor("#333333")))
    for values, fit, color in (
        (result.spatial_std, result.spatial_fit, HexColor("#1565c0")),
        (result.temporal_noise, result.temporal_fit, HexColor("#c62828")),
    ):
        previous = None
        for brightness in sorted(result.brightness):
            point = (px(brightness), py(fit.predict(brightness)))
            if previous is not None:
                drawing.add(
                    Line(
                        previous[0],
                        previous[1],
                        point[0],
                        point[1],
                        strokeColor=color,
                        strokeWidth=1.5,
                    )
                )
            previous = point
        for brightness, value in zip(result.brightness, values):
            drawing.add(
                Circle(
                    px(brightness),
                    py(value),
                    2.2,
                    fillColor=color,
                    strokeColor=color,
                )
            )
    drawing.add(String(left, 2 * mm, "brightness (log)", fontSize=7))
    drawing.add(
        String(
            right - 52 * mm,
            top,
            "blue: spatial STD | red: temporal noise",
            fontSize=7,
        )
    )
    return drawing


def _find_report_font() -> str:
    candidates = [
        os.environ.get("ACCEPTANCE_REPORT_FONT", ""),
        r"C:\Windows\Fonts\msjh.ttc",
        r"C:\Windows\Fonts\mingliu.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise FormalReportError(
        "no Traditional-Chinese PDF font found; set ACCEPTANCE_REPORT_FONT"
    )


def _xml(value: str) -> str:
    return html.escape(value, quote=False)
