# -*- coding: utf-8 -*-
"""Formal v4 Session workflow widget."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core import (
    AcceptanceDatasetManifest,
    MetricGroup,
    OpticalMode,
    PreconditionLock,
    SessionWorkflow,
    Severity,
    WorkflowError,
    WorkflowStep,
)
from ..reporting import (
    build_formal_report,
    export_formal_report,
    load_report_config,
)

_STEP_INDEX = {
    WorkflowStep.EMPTY: 0,
    WorkflowStep.MANIFEST_LOADED: 1,
    WorkflowStep.EVIDENCE_CHECKED: 2,
    WorkflowStep.MEASURED: 3,
    WorkflowStep.JUDGED: 4,
    WorkflowStep.REPORT_READY: 5,
}

_STEP_TEXT = {
    WorkflowStep.EMPTY: "請建立或載入 dataset manifest",
    WorkflowStep.MANIFEST_LOADED: "Manifest 已載入；請確認取像模式並檢查證據",
    WorkflowStep.EVIDENCE_CHECKED: "證據檢查完成；通過後可執行正式量測",
    WorkflowStep.MEASURED: "量測完成；請檢閱未評估項後執行判定",
    WorkflowStep.JUDGED: "正式判定完成；可產生三方會簽報告",
    WorkflowStep.REPORT_READY: "正式報告已產生",
}


class SessionWorkflowWidget(QWidget):
    """Guided manifest → evidence → measurement → judgment → report UI."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.workflow = SessionWorkflow()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        banner = QLabel(
            "<b>正式 v4 驗收 Session</b>　"
            "所有分級均保留證據來源；證據不足不會被判為通過。"
        )
        banner.setStyleSheet(
            "background:#173b57;color:white;padding:10px;border-radius:4px;"
        )
        root.addWidget(banner)

        setup = QGroupBox("1. Manifest 與取像模式")
        grid = QGridLayout(setup)
        self.manifest_path = QLineEdit()
        self.manifest_path.setReadOnly(True)
        self.btn_create_manifest = QPushButton("建立 Manifest 範本")
        self.btn_load_manifest = QPushButton("載入 Manifest")
        self.mode_combo = QComboBox()
        for mode, label in (
            (OpticalMode.DIFFUSE_BRIGHT_FIELD, "漫反射明場"),
            (OpticalMode.SPECULAR_BRIGHT_FIELD, "鏡面明場"),
            (OpticalMode.SCATTERING_DARK_FIELD, "散射暗場"),
        ):
            self.mode_combo.addItem(label, mode)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.btn_create_manifest.clicked.connect(self.on_create_manifest)
        self.btn_load_manifest.clicked.connect(self.on_load_manifest)
        grid.addWidget(QLabel("Manifest"), 0, 0)
        grid.addWidget(self.manifest_path, 0, 1, 1, 3)
        grid.addWidget(self.btn_create_manifest, 0, 4)
        grid.addWidget(self.btn_load_manifest, 0, 5)
        grid.addWidget(QLabel("取像模式"), 1, 0)
        grid.addWidget(self.mode_combo, 1, 1)
        root.addWidget(setup)

        action_row = QHBoxLayout()
        self.btn_check = QPushButton("2. 檢查證據")
        self.btn_measure = QPushButton("3. 執行／匯入量測")
        self.btn_judge = QPushButton("4. 正式判定")
        self.btn_report = QPushButton("5. 產生報告")
        self.btn_check.clicked.connect(self.on_check_evidence)
        self.btn_measure.clicked.connect(self.on_measure)
        self.btn_judge.clicked.connect(self.on_judge)
        self.btn_report.clicked.connect(self.on_report)
        for button in (
            self.btn_check,
            self.btn_measure,
            self.btn_judge,
            self.btn_report,
        ):
            action_row.addWidget(button)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 5)
        self.step_label = QLabel()
        status_row = QHBoxLayout()
        status_row.addWidget(self.progress, 1)
        status_row.addWidget(self.step_label, 3)
        root.addLayout(status_row)

        self.pages = QTabWidget()
        self.group_table = self._table(("群組", "目前狀態", "說明"))
        self.priority_table = self._table(("優先事件", "說明", "證據"))
        self.decision_view = QTextEdit()
        self.decision_view.setReadOnly(True)
        self.gap_table = self._table(("範圍", "項目", "缺口原因", "來源"))
        self.trace_table = self._table(
            ("Metric / Evidence", "群組", "等級", "層級", "ROI", "公式版本", "來源")
        )
        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        self.pages.addTab(self.group_table, "群組總覽")
        self.pages.addTab(self.priority_table, "S0 優先事件")
        self.pages.addTab(self.decision_view, "判定順位")
        self.pages.addTab(self.gap_table, "證據缺口")
        self.pages.addTab(self.trace_table, "來源追蹤")
        self.pages.addTab(self.report_view, "報告")
        root.addWidget(self.pages, 1)

    def _table(self, headers) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def on_load_manifest(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "載入 v4 dataset manifest", "", "JSON (*.json)"
        )
        if path:
            self._guard(lambda: self.load_manifest(path))

    def load_manifest(self, path: str) -> None:
        dataset = self.workflow.load_manifest(path)
        self.manifest_path.setText(str(Path(path).resolve()))
        index = self.mode_combo.findData(dataset.optical_mode)
        if index >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(index)
            self.mode_combo.blockSignals(False)
        self.refresh()

    def on_create_manifest(self) -> None:
        machine_id, accepted = QInputDialog.getText(
            self, "建立 Manifest", "機台 ID："
        )
        if not accepted or not machine_id.strip():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "儲存 Manifest 範本", "dataset_manifest.json", "JSON (*.json)"
        )
        if not path:
            return
        self._guard(lambda: self.create_manifest_template(path, machine_id.strip()))

    def create_manifest_template(self, path: str, machine_id: str) -> None:
        lock = PreconditionLock(
            camera={
                "model": "待填",
                "serial": "待填",
                "bit_depth": 8,
                "gain": "待填",
                "exposure_us": "待填",
                "line_rate_hz": "待填",
                "binning": "待填",
                "sensor_roi": "待填",
                "internal_calibration": "待填",
                "auto_features": "待填",
            },
            optics={
                "lens_model": "待填",
                "aperture": "待填",
                "working_distance_mm": "待填",
                "filter": "待填",
                "polarizer": "待填",
                "magnification": "待填",
                "micrometers_per_pixel": "待填",
                "focus_position": "待填",
            },
            lighting={
                "model": "待填",
                "drive_mode": "待填",
                "drive_value": "待填",
                "measured_illuminance": "待填",
                "angle_deg": "待填",
                "distance_mm": "待填",
                "polarization": "待填",
                "aging_hours": "待填",
            },
            mechanics={
                "scan_speed": "待填",
                "encoder_resolution": "待填",
                "trigger_mode": "待填",
                "vibration_state": "待填",
                "fixture_state": "待填",
            },
            environment={
                "ambient_light_shielded": "待填",
                "temperature_c": "待填",
                "relative_humidity_pct": "待填",
                "warmup_minutes": 30,
            },
            sample={
                "sample_id": "待填",
                "batch_id": "待填",
                "orientation": "待填",
                "surface_cleanliness": "待填",
                "golden_approved": "待填",
            },
            computation={
                "roi_version": "待填",
                "formula_version": "v4-formula-1",
                "script_version": "待填",
            },
            data={
                "raw_format": "待填",
                "timestamp_source": "待填",
                "parameter_record_source": "待填",
            },
        )
        manifest = AcceptanceDatasetManifest(
            machine_id=machine_id,
            optical_mode=self.mode_combo.currentData(),
            precondition_lock=lock,
            spec_version="v4-discussion-2026-07-23",
        )
        manifest.save_json(path)
        self.load_manifest(path)
        self.step_label.setText("Manifest 範本已建立；請補齊資料與影像證據後檢查")

    def _on_mode_changed(self) -> None:
        if self.workflow.session is None:
            return
        self._guard(lambda: self.workflow.select_mode(self.mode_combo.currentData()))
        self.refresh()

    def on_check_evidence(self) -> None:
        self._guard(self.check_evidence)

    def check_evidence(self) -> None:
        result = self.workflow.check_evidence()
        self.refresh()
        if not result.valid:
            self.pages.setCurrentWidget(self.gap_table)

    def on_measure(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇 G1-G6 量測套件", "", "JSON (*.json)"
        )
        if path:
            self._guard(lambda: self.execute_measurements(path))

    def execute_measurements(self, path: str) -> None:
        self.workflow.execute_measurement_package(path)
        self.refresh()
        self.pages.setCurrentWidget(self.gap_table)

    def on_judge(self) -> None:
        self._guard(self.judge_session)

    def judge_session(self) -> None:
        self.workflow.judge()
        self.refresh()
        self.pages.setCurrentWidget(self.decision_view)

    def on_report(self) -> None:
        config_path, _ = QFileDialog.getOpenFileName(
            self, "選擇正式報告設定", "", "JSON (*.json)"
        )
        if not config_path:
            return
        output_dir = QFileDialog.getExistingDirectory(self, "選擇正式報告輸出資料夾")
        if output_dir:
            self._guard(lambda: self.generate_report(config_path, output_dir))

    def generate_report(self, config_path: str, output_dir: str) -> None:
        if self.workflow.session is None or self.workflow.decision is None:
            raise WorkflowError("請先完成正式判定")
        report = build_formal_report(
            self.workflow.session,
            self.workflow.decision,
            load_report_config(config_path),
        )
        paths = export_formal_report(report, output_dir)
        self.workflow.mark_report_ready(paths)
        self.refresh()
        self.pages.setCurrentWidget(self.report_view)

    def refresh(self) -> None:
        step = self.workflow.step
        self.progress.setValue(_STEP_INDEX[step])
        self.step_label.setText(_STEP_TEXT[step])
        has_manifest = self.workflow.session is not None
        evidence_ok = bool(
            self.workflow.evidence_check and self.workflow.evidence_check.valid
        )
        has_measurements = bool(
            self.workflow.session and self.workflow.session.measurements
        )
        self.btn_check.setEnabled(has_manifest)
        self.btn_measure.setEnabled(evidence_ok)
        self.btn_judge.setEnabled(has_measurements)
        self.btn_report.setEnabled(self.workflow.decision is not None)
        self.mode_combo.setEnabled(step in {
            WorkflowStep.EMPTY,
            WorkflowStep.MANIFEST_LOADED,
            WorkflowStep.EVIDENCE_CHECKED,
        })
        self._refresh_groups()
        self._refresh_priority()
        self._refresh_decision()
        self._refresh_gaps()
        self._refresh_trace()
        self.report_view.setPlainText(
            "\n".join(self.workflow.report_paths)
            if self.workflow.report_paths
            else "尚未產生正式報告。報告需要三方會簽設定與完整 artifact manifest。"
        )

    def _refresh_groups(self) -> None:
        session = self.workflow.session
        self.group_table.setRowCount(0)
        for group in MetricGroup:
            severity = session.group_status(group) if session else Severity.NOT_EVALUATED
            note = (
                "尚無量測"
                if not session or not any(item.group == group for item in session.measurements)
                else "組內取最嚴重等級；S0/S1 優先於未評估"
            )
            self._append_row(self.group_table, (group.value, severity.value, note))

    def _refresh_priority(self) -> None:
        self.priority_table.setRowCount(0)
        for event in self.workflow.priority_events:
            self._append_row(
                self.priority_table,
                (
                    event.event_type.value,
                    event.description,
                    "\n".join(event.evidence_sources),
                ),
            )
        if not self.workflow.priority_events:
            self._append_row(self.priority_table, ("—", "目前沒有 S0 優先事件", "—"))

    def _refresh_decision(self) -> None:
        decision = self.workflow.decision
        rules = (
            "任一 S0 優先事件",
            "G5／G6 任一 S0",
            "任兩組以上 S0",
            "單一 G1～G4 S0",
            "任一 S1",
            "全部為 S2 以上，且至少四組 S3",
            "全部為 S2 以上，未達順位 6",
        )
        items = []
        for index, rule in enumerate(rules, start=1):
            style = " style='background:#fff0d6;font-weight:bold'" if (
                decision and decision.rule_number == index
            ) else ""
            items.append(f"<li{style}>{html.escape(rule)}</li>")
        summary = (
            "<p>尚未執行正式判定。</p>"
            if decision is None
            else (
                f"<p><b>結果：</b>{html.escape(decision.result.value)}　"
                f"<b>命中順位：</b>{decision.rule_number or '證據不足'}<br>"
                f"<b>原因：</b>{html.escape(decision.reason)}<br>"
                f"<b>觸發群組：</b>{html.escape(', '.join(decision.trigger_groups) or '—')}<br>"
                f"<b>證據不足：</b>{html.escape(', '.join(decision.missing_metric_ids) or '—')}</p>"
            )
        )
        self.decision_view.setHtml(summary + "<ol>" + "".join(items) + "</ol>")

    def _refresh_gaps(self) -> None:
        self.gap_table.setRowCount(0)
        check = self.workflow.evidence_check
        if check:
            for issue in check.issues:
                self._append_row(
                    self.gap_table,
                    ("Manifest／檔案", issue.item_id, issue.reason, issue.source),
                )
        session = self.workflow.session
        if session:
            for item in session.measurements:
                if item.severity == Severity.NOT_EVALUATED:
                    self._append_row(
                        self.gap_table,
                        (
                            "量測",
                            item.metric_id,
                            item.missing_reason,
                            "\n".join(item.evidence_sources),
                        ),
                    )
        if self.gap_table.rowCount() == 0:
            self._append_row(self.gap_table, ("—", "—", "目前沒有已知證據缺口", "—"))

    def _refresh_trace(self) -> None:
        self.trace_table.setRowCount(0)
        dataset = self.workflow.dataset_manifest
        if dataset:
            for image in dataset.images:
                self._append_row(
                    self.trace_table,
                    (
                        image.relative_path,
                        "Manifest",
                        "evidence",
                        image.image_level.value,
                        "—",
                        image.calibration_version or "—",
                        f"{image.sha256}\n{image.sidecar_relative_path}",
                    ),
                )
        session = self.workflow.session
        if session:
            for item in session.measurements:
                self._append_row(
                    self.trace_table,
                    (
                        item.metric_id,
                        item.group.value,
                        item.severity.value,
                        item.image_level.value,
                        item.roi_id or "—",
                        item.formula_version,
                        "\n".join(item.evidence_sources) or item.missing_reason,
                    ),
                )

    def _append_row(self, table: QTableWidget, values) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, column, item)

    def _guard(self, action: Callable[[], None]) -> None:
        try:
            action()
        except (OSError, ValueError, KeyError, WorkflowError) as exc:
            QMessageBox.critical(self, "v4 Session 工作流", str(exc))
