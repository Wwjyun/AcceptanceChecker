# -*- coding: utf-8 -*-
"""PySide6 桌面介面。"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from typing import Optional

import cv2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.config import Thresholds
from ..core.pipeline import AcceptancePipeline, AnalysisResult
from ..reporting import CsvExporter, ReportBuilder
from .preview import ImagePreview


class AcceptanceCheckerWindow(QMainWindow):
    """AOI Raw Image 光學驗收檢查工具主視窗。"""

    def __init__(self, thresholds: Optional[Thresholds] = None):
        super().__init__()
        self.thresholds = thresholds or Thresholds()

        self.pipeline = AcceptancePipeline(self.thresholds)
        self.report_builder = ReportBuilder()
        self.csv_exporter = CsvExporter()
        self.preview = ImagePreview()

        self.result: Optional[AnalysisResult] = None

        self.setWindowTitle("AOI Raw Image 光學驗收檢查工具")
        self.resize(1280, 820)
        self._build_ui()

    # ---------- UI 建構 ----------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # 頂部工具列
        top = QHBoxLayout()
        btn_open = QPushButton("選擇圖片並分析")
        btn_open.clicked.connect(self.on_open_image)
        btn_csv = QPushButton("匯出 CSV 報告")
        btn_csv.clicked.connect(self.on_export_csv)
        btn_overlay = QPushButton("儲存異常候選圖")
        btn_overlay.clicked.connect(self.on_save_overlay)

        self.status_label = QLabel("尚未分析")
        for w in (btn_open, btn_csv, btn_overlay):
            top.addWidget(w)
        top.addWidget(self.status_label)
        top.addStretch(1)
        root.addLayout(top)

        # 左右分割
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # 左：預覽
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("預覽：紅框為自動估算的異常候選區"))
        self.canvas = QLabel()
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setStyleSheet("background-color: #222222;")
        self.canvas.setMinimumSize(400, 400)
        left_layout.addWidget(self.canvas, 1)
        splitter.addWidget(left)

        # 右：報告
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Raw Image 驗收報告"))
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.report.setPlainText(self.report_builder.thresholds_hint(self.thresholds))
        right_layout.addWidget(self.report, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

    # ---------- 事件處理 ----------

    def on_open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇 AOI raw image",
            "",
            "Image files (*.bmp *.png *.jpg *.jpeg *.tif *.tiff);;All files (*.*)",
        )
        if not path:
            return

        try:
            self.status_label.setText("分析中...")
            QApplication.processEvents()

            self.result = self.pipeline.run(path)
            self._update_report()
            self._update_preview()

            m = self.result.metrics
            self.status_label.setText(f"{m.overall_status}：{m.file_name}")
        except Exception as e:  # noqa: BLE001 - 對使用者顯示錯誤即可
            traceback.print_exc()
            QMessageBox.critical(self, "錯誤", f"分析失敗：\n{e}")
            self.status_label.setText("分析失敗")

    def on_export_csv(self) -> None:
        if self.result is None:
            QMessageBox.warning(self, "尚未分析", "請先選擇圖片並分析。")
            return

        default_name = f"aoi_raw_image_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "匯出 CSV", default_name, "CSV (*.csv)")
        if not path:
            return
        try:
            self.csv_exporter.export(self.result.metrics, path)
            QMessageBox.information(self, "完成", f"已匯出：\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "錯誤", f"匯出失敗：\n{e}")

    def on_save_overlay(self) -> None:
        if self.result is None:
            QMessageBox.warning(self, "尚未分析", "請先選擇圖片並分析。")
            return

        default_name = f"aoi_candidate_overlay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "儲存異常候選圖", default_name, "PNG (*.png)")
        if not path:
            return
        try:
            cv2.imwrite(path, self.result.overlay)
            QMessageBox.information(self, "完成", f"已儲存：\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "錯誤", f"儲存失敗：\n{e}")

    # ---------- 畫面更新 ----------

    def _update_preview(self) -> None:
        if self.result is None:
            return
        pixmap = self.preview.to_pixmap(self.result.overlay)
        if pixmap is None:
            return
        scaled = pixmap.scaled(
            self.canvas.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.canvas.setPixmap(scaled)

    def _update_report(self) -> None:
        if self.result is None:
            return
        self.report.setPlainText(self.report_builder.build(self.result.metrics))


def run_app(thresholds: Optional[Thresholds] = None) -> int:
    """建立 QApplication 並啟動主視窗。回傳程式離開碼。"""
    app = QApplication.instance() or QApplication(sys.argv)
    window = AcceptanceCheckerWindow(thresholds)
    window.show()
    return app.exec()
