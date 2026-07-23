# -*- coding: utf-8 -*-
"""PySide6 桌面介面。"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.config import Thresholds
from ..core.detector import roi_cnr
from ..core.image import imwrite_unicode
from ..core.io_utils import validate_save_path
from ..core.pipeline import AcceptancePipeline, AnalysisResult
from ..core.roi import RoiCreationMethod, RoiDefinition, RoiType
from ..reporting import CsvExporter, ReportBuilder
from .preview import ImagePreview
from .roi_label import RoiSelectLabel
from .session_workflow import SessionWorkflowWidget
from .threshold_dialog import ThresholdDialog
from .worker import AnalysisWorker

logger = logging.getLogger("acceptance_checker.gui")


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
        self.last_manual_roi: Optional[RoiDefinition] = None

        # 背景分析執行緒相關
        self._thread: Optional[QThread] = None
        self._worker: Optional[AnalysisWorker] = None

        self._ensure_cjk_font()
        self.setWindowTitle("AcceptanceChecker｜v4 候選驗收流程與快速工程檢查")
        self.resize(1280, 820)
        self._build_ui()

    def _ensure_cjk_font(self) -> None:
        """Load a bundled OS CJK font when the offscreen platform cannot discover it."""
        candidates = (
            (r"C:\Windows\Fonts\msjh.ttc", "Microsoft JhengHei UI"),
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK TC"),
            ("/System/Library/Fonts/PingFang.ttc", "PingFang TC"),
        )
        for path, family in candidates:
            if not os.path.isfile(path):
                continue
            font_id = QFontDatabase.addApplicationFont(path)
            if font_id >= 0:
                self.setFont(QFont(family, 9))
                return

    # ---------- UI 建構 ----------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        self.mode_tabs = QTabWidget()
        root.addWidget(self.mode_tabs)
        self.session_workflow = SessionWorkflowWidget()
        self.mode_tabs.addTab(self.session_workflow, "v4 Session 候選流程")

        quick_check = QWidget()
        quick_root = QVBoxLayout(quick_check)
        quick_notice = QLabel(
            "快速工程檢查：此頁使用 legacy quality_score／overall_status，"
            "不是完整 v4 驗收，也不會產生正式 S0～S3 結論。"
        )
        quick_notice.setWordWrap(True)
        quick_notice.setStyleSheet(
            "background:#fff3cd;border:1px solid #d6b656;padding:8px;"
        )
        quick_root.addWidget(quick_notice)
        self.mode_tabs.addTab(quick_check, "快速工程檢查（非完整 v4）")

        # 頂部工具列
        top = QHBoxLayout()
        self.btn_open = QPushButton("選擇圖片並分析")
        self.btn_open.clicked.connect(self.on_open_image)
        btn_csv = QPushButton("匯出 CSV 報告")
        btn_csv.clicked.connect(self.on_export_csv)
        btn_overlay = QPushButton("儲存異常候選圖")
        btn_overlay.clicked.connect(self.on_save_overlay)
        btn_thresholds = QPushButton("門檻設定")
        btn_thresholds.clicked.connect(self.on_edit_thresholds)
        btn_batch = QPushButton("批次分析")
        btn_batch.clicked.connect(self.on_open_batch)

        self.status_label = QLabel("尚未分析")
        for w in (self.btn_open, btn_csv, btn_overlay, btn_thresholds, btn_batch):
            top.addWidget(w)
        top.addWidget(self.status_label)
        top.addStretch(1)
        quick_root.addLayout(top)

        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("放行備註/理由（選填，會寫入 CSV）："))
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("例如：線壓不足暫時放行，已知風險為背景雜訊偏高")
        note_row.addWidget(self.note_edit, 1)
        quick_root.addLayout(note_row)

        # 左右分割
        splitter = QSplitter(Qt.Orientation.Horizontal)
        quick_root.addWidget(splitter, 1)

        # 左：預覽
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("預覽：紅框為自動候選區；用滑鼠拖曳框選可量測人工 ROI 的 CNR"))
        self.canvas = RoiSelectLabel()
        self.canvas.setStyleSheet("background-color: #222222;")
        self.canvas.setMinimumSize(400, 400)
        self.canvas.roi_selected.connect(self.on_roi_selected)
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
        self._start_analysis(path)

    def _start_analysis(self, path: str) -> None:
        """在背景執行緒啟動一次分析。已有分析進行中則忽略。"""
        if self._thread is not None:
            return

        self.btn_open.setEnabled(False)
        self.status_label.setText("分析中...")

        self._thread = QThread(self)
        self._worker = AnalysisWorker(self.pipeline, path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_analysis_finished)
        self._worker.failed.connect(self._on_analysis_failed)
        self._thread.start()

    def _on_analysis_finished(self, result: AnalysisResult) -> None:
        self.result = result
        self._update_report()
        self._update_preview()
        m = result.metrics
        self.status_label.setText(
            f"{m.risk_level or m.overall_status} {m.quality_score:.1f}分：{m.file_name}"
        )
        self._teardown_thread()

    def _on_analysis_failed(self, message: str) -> None:
        logger.error("分析失敗：%s", message)
        QMessageBox.critical(self, "錯誤", f"分析失敗：\n{message}")
        self.status_label.setText("分析失敗")
        self._teardown_thread()

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
        self._worker = None
        self.btn_open.setEnabled(True)

    def on_export_csv(self) -> None:
        if self.result is None:
            QMessageBox.warning(self, "尚未分析", "請先選擇圖片並分析。")
            return

        default_name = f"aoi_raw_image_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "匯出 CSV", default_name, "CSV (*.csv)")
        if not path:
            return
        err = validate_save_path(path)
        if err:
            QMessageBox.critical(self, "無法匯出", err)
            return
        note = self.note_edit.text().strip()
        if note:
            self.result.metrics.review_note = note
        try:
            self.csv_exporter.export(self.result.metrics, path)
            QMessageBox.information(self, "完成", f"已匯出：\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "錯誤", f"匯出失敗：\n{e}")

    def on_open_batch(self) -> None:
        # 以目前門檻開啟批次視窗；保留參考避免被回收
        from .batch_window import BatchWindow

        self._batch_window = BatchWindow(self.thresholds, self)
        self._batch_window.setWindowFlag(Qt.WindowType.Window, True)
        self._batch_window.show()

    def on_edit_thresholds(self) -> None:
        dialog = ThresholdDialog(self.thresholds, self)
        if dialog.exec() != ThresholdDialog.DialogCode.Accepted:
            return
        # 更新門檻並套用到 pipeline（僅重判，不重算指標）
        self.thresholds = dialog.result_thresholds()
        self.pipeline.set_thresholds(self.thresholds)

        if self.result is not None:
            self.pipeline.judge.judge(self.result.metrics)
            self._update_report()
            m = self.result.metrics
            self.status_label.setText(
                f"{m.risk_level or m.overall_status} {m.quality_score:.1f}分："
                f"{m.file_name}（已依新門檻重判）"
            )
        else:
            self.report.setPlainText(self.report_builder.thresholds_hint(self.thresholds))

    def on_save_overlay(self) -> None:
        if self.result is None:
            QMessageBox.warning(self, "尚未分析", "請先選擇圖片並分析。")
            return

        default_name = f"aoi_candidate_overlay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "儲存異常候選圖", default_name, "PNG (*.png)")
        if not path:
            return
        err = validate_save_path(path)
        if err:
            QMessageBox.critical(self, "無法儲存", err)
            return
        try:
            if not imwrite_unicode(path, self.result.overlay):
                raise RuntimeError("影像編碼或寫入失敗")
            QMessageBox.information(self, "完成", f"已儲存：\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "錯誤", f"儲存失敗：\n{e}")

    # ---------- 畫面更新 ----------

    def _update_preview(self) -> None:
        if self.result is None:
            return
        # RoiSelectLabel 自行負責等比例縮放與重繪（含視窗縮放）
        self.canvas.set_image(self.preview.to_pixmap(self.result.overlay))

    def on_roi_selected(self, x: int, y: int, w: int, h: int) -> None:
        """使用者於預覽框選 ROI：以 sample 影像量測人工 CNR 並顯示。"""
        if self.result is None:
            return
        step = max(1, int(self.result.metrics.analysis_step))
        self.last_manual_roi = RoiDefinition.from_sample_box(
            roi_id="gui-manual-roi",
            roi_type=RoiType.GOLDEN_DEFECT,
            sample_box=(x, y, w, h),
            step=step,
            image_width=int(self.result.metrics.width_px),
            image_height=int(self.result.metrics.height_px),
            creation_method=RoiCreationMethod.GUI_MANUAL,
            operator="",
            version="1",
            image_id=self.result.metrics.file_name or "current-image",
        )
        r = roi_cnr(self.result.sample, (x, y, w, h))
        if r.defect_area_px == 0:
            self.status_label.setText("ROI 太小或超出範圍，請重新框選")
            return
        self.status_label.setText(
            f"人工 ROI CNR：{r.cnr:.2f}"
            f"（缺陷均值 {r.defect_mean:.1f} / 背景均值 {r.bg_mean:.1f} / "
            f"對比 {r.contrast:.1f} / 背景std {r.bg_std:.2f} / "
            f"ROI {r.defect_area_px}px；原圖座標 {self.last_manual_roi.box}）"
        )

    def _update_report(self) -> None:
        if self.result is None:
            return
        self.report.setPlainText(self.report_builder.build(self.result.metrics, self.thresholds))


def run_app(thresholds: Optional[Thresholds] = None) -> int:
    """建立 QApplication 並啟動主視窗。回傳程式離開碼。"""
    app = QApplication.instance() or QApplication(sys.argv)
    window = AcceptanceCheckerWindow(thresholds)
    window.show()
    return app.exec()
