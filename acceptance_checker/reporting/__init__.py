# -*- coding: utf-8 -*-
"""報告輸出：文字報告與 CSV 匯出。"""

from .csv_export import CsvExporter
from .drift_report import DriftReport, DriftReporter, DriftStats
from .formal_report import (
    FormalAcceptanceReport,
    FormalReportError,
    ImprovementAction,
    OpticalDeclaration,
    ReportArtifact,
    ReportSignoff,
    TestObject,
)
from .history_log import HistoryLogger
from .recommendations import Recommendation, RecommendationBuilder
from .report_factory import (
    build_formal_report,
    export_formal_report,
    load_report_config,
    report_config_template,
)
from .schema import load_formal_report_schema_v1
from .text_report import ReportBuilder

__all__ = [
    "CsvExporter",
    "HistoryLogger",
    "Recommendation",
    "RecommendationBuilder",
    "ReportBuilder",
    "DriftReporter",
    "DriftReport",
    "DriftStats",
    "FormalAcceptanceReport",
    "FormalReportError",
    "ImprovementAction",
    "OpticalDeclaration",
    "ReportArtifact",
    "ReportSignoff",
    "TestObject",
    "build_formal_report",
    "export_formal_report",
    "load_report_config",
    "report_config_template",
    "load_formal_report_schema_v1",
]
