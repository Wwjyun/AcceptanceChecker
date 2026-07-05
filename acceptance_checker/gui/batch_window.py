# -*- coding: utf-8 -*-
"""批次分析視窗：拖放多張影像，逐列顯示判定與關鍵指標。"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.config import Thresholds
from ..core.io_utils import validate_save_path
from ..core.metrics import Metrics
from ..core.pipeline import AcceptancePipeline
from ..reporting import CsvExporter, DriftReporter, HistoryLogger, ReportBuilder
from .worker import BatchWorker

_IMAGE_EXTS = (".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff")

_STATUS_COLORS = {
    "PASS": Qt.GlobalColor.darkGreen,
    "WARNING": Qt.GlobalColor.darkYellow,
    "FAIL": Qt.GlobalColor.red,
}
# 分數低於 critical_score 時，即使 overall_status 仍是 FAIL，顏色也加深以區分優先序。
_CRITICAL_COLOR = Qt.GlobalColor.darkRed
_CRITICAL_LABEL = "量產導入風險極高"


class BatchWindow(QMainWindow):
    """接受拖放/選檔的批次驗收視窗。"""

    COLUMNS = [
        "檔名",
        "風險等級",
        "總分",
        "平均灰階",
        "均勻性",
        "SNR",
        "CNR",
        "背景std",
        "主要原因",
    ]

    def __init__(self, thresholds: Optional[Thresholds] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批次驗收")
        self.resize(1000, 600)
        self.setAcceptDrops(True)

        self._thresholds = thresholds or Thresholds()
        self.pipeline = AcceptancePipeline(self._thresholds)
        self.report_builder = ReportBuilder()
        self.csv_exporter = CsvExporter()
        self.drift_reporter = DriftReporter(self._thresholds)
        self.history_logger = HistoryLogger()

        self._queued: List[str] = []          # 待分析路徑
        self._metrics: Dict[int, Metrics] = {}  # row -> Metrics
        self._thread: Optional[QThread] = None
        self._worker: Optional[BatchWorker] = None

        self._build_ui()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        top = QHBoxLayout()
        self.btn_add = QPushButton("加入檔案")
        self.btn_add.clicked.connect(self.on_add_files)
        self.btn_run = QPushButton("分析全部")
        self.btn_run.clicked.connect(self.on_run)
        self.btn_csv = QPushButton("匯出彙整 CSV")
        self.btn_csv.clicked.connect(self.on_export_csv)
        self.btn_drift = QPushButton("跨圖漂移報告")
        self.btn_drift.clicked.connect(self.on_show_drift)
        self.btn_history = QPushButton("附加寫入歷史紀錄…")
        self.btn_history.clicked.connect(self.on_append_history)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self.on_clear)
        for b in (
            self.btn_add, self.btn_run, self.btn_csv, self.btn_drift,
            self.btn_history, self.btn_clear,
        ):
            top.addWidget(b)
        top.addStretch(1)
        root.addLayout(top)

        root.addWidget(QLabel("可將影像檔直接拖放到下方表格；雙擊列可看完整報告。"))

        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("放行備註/理由（選填，會寫入 CSV 與歷史紀錄）："))
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("例如：線壓不足暫時放行，已知風險為背景雜訊偏高")
        note_row.addWidget(self.note_edit, 1)
        root.addLayout(note_row)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            len(self.COLUMNS) - 1, QHeaderView.ResizeMode.Stretch
        )
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)
        root.addWidget(self.table, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

    # ---------- 拖放 ----------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(_IMAGE_EXTS):
                paths.append(p)
        if paths:
            self._add_paths(paths)

    # ---------- 佇列管理 ----------

    def on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "選擇影像檔",
            "",
            "Image files (*.bmp *.png *.jpg *.jpeg *.tif *.tiff);;All files (*.*)",
        )
        if paths:
            self._add_paths(paths)

    def _add_paths(self, paths: List[str]) -> None:
        import os

        for p in paths:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(p)))
            self.table.setItem(row, 1, QTableWidgetItem("待分析"))
            for c in range(2, len(self.COLUMNS)):
                self.table.setItem(row, c, QTableWidgetItem(""))
            self._queued.append(p)

    def on_clear(self) -> None:
        if self._thread is not None:
            return
        self.table.setRowCount(0)
        self._queued.clear()
        self._metrics.clear()

    # ---------- 分析 ----------

    def on_run(self) -> None:
        if self._thread is not None:
            return
        if not self._queued:
            QMessageBox.information(self, "沒有檔案", "請先加入或拖放影像檔。")
            return

        self._set_busy(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(self._queued))
        self.progress.setValue(0)
        self._row_cursor = 0

        self._thread = QThread(self)
        self._worker = BatchWorker(self.pipeline, list(self._queued))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.item_done.connect(self._on_item_done)
        self._worker.item_failed.connect(self._on_item_failed)
        self._worker.finished.connect(self._on_batch_finished)
        self._thread.start()

    def _on_item_done(self, _path: str, result) -> None:
        row = self._row_cursor
        m = result.metrics
        self._metrics[row] = m
        self._fill_row(row, m)
        self._advance()

    def _on_item_failed(self, _path: str, message: str) -> None:
        row = self._row_cursor
        self.table.setItem(row, 1, QTableWidgetItem("讀取失敗"))
        self.table.setItem(row, len(self.COLUMNS) - 1, QTableWidgetItem(message))
        self._advance()

    def _advance(self) -> None:
        self._row_cursor += 1
        self.progress.setValue(self._row_cursor)

    def _fill_row(self, row: int, m: Metrics) -> None:
        status_item = QTableWidgetItem(m.risk_level or m.overall_status)
        color = _CRITICAL_COLOR if m.risk_level == _CRITICAL_LABEL else _STATUS_COLORS.get(
            m.overall_status
        )
        if color is not None:
            status_item.setForeground(color)
        self.table.setItem(row, 1, status_item)
        self.table.setItem(row, 2, QTableWidgetItem(f"{m.quality_score:.1f}"))
        self.table.setItem(row, 3, QTableWidgetItem(f"{m.mean_gray:.1f}"))
        self.table.setItem(row, 4, QTableWidgetItem(f"{m.uniformity_ratio:.3f}"))
        self.table.setItem(row, 5, QTableWidgetItem(f"{m.signal_to_noise_ratio:.2f}"))
        self.table.setItem(row, 6, QTableWidgetItem(f"{m.auto_defect_cnr_est:.2f}"))
        self.table.setItem(row, 7, QTableWidgetItem(f"{m.bg_std_est:.2f}"))
        reason = m.fail_reasons or m.warn_reasons or ""
        self.table.setItem(row, len(self.COLUMNS) - 1, QTableWidgetItem(reason))

    def _on_batch_finished(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
        self._worker = None
        self.progress.setVisible(False)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        for b in (self.btn_add, self.btn_run, self.btn_clear):
            b.setEnabled(not busy)

    # ---------- 檢視 / 匯出 ----------

    def on_row_double_clicked(self, row: int, _col: int) -> None:
        m = self._metrics.get(row)
        if m is None:
            return
        QMessageBox.information(
            self, f"報告：{m.file_name}", self.report_builder.build(m, self._thresholds)
        )

    def on_show_drift(self) -> None:
        rows = [self._metrics[r] for r in sorted(self._metrics)]
        if len(rows) < 2:
            QMessageBox.information(self, "資料不足", "至少需 2 張成功結果才能看跨圖漂移。")
            return
        QMessageBox.information(self, "跨圖一致性 / 灰階漂移", self.drift_reporter.build(rows))

    def _apply_note(self, rows: List[Metrics]) -> None:
        note = self.note_edit.text().strip()
        if note:
            for m in rows:
                m.review_note = note

    def on_export_csv(self) -> None:
        rows = [self._metrics[r] for r in sorted(self._metrics)]
        if not rows:
            QMessageBox.information(self, "沒有結果", "尚無成功分析的結果可匯出。")
            return
        self._apply_note(rows)
        default_name = f"aoi_batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "匯出彙整 CSV", default_name, "CSV (*.csv)")
        if not path:
            return
        err = validate_save_path(path)
        if err:
            QMessageBox.critical(self, "無法匯出", err)
            return
        try:
            self.csv_exporter.export_many(rows, path)
            QMessageBox.information(self, "完成", f"已匯出 {len(rows)} 筆：\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "錯誤", f"匯出失敗：\n{e}")

    def on_append_history(self) -> None:
        """把目前批次結果附加寫入一份跨時間的歷史紀錄 CSV（不覆蓋既有內容）。

        用途：單次分數不會擋線，但同一產線的分數若持續下滑，就是能拿去反映的證據；
        這裡選的檔案若已存在則附加、不存在則建立並寫表頭。
        """
        rows = [self._metrics[r] for r in sorted(self._metrics)]
        if not rows:
            QMessageBox.information(self, "沒有結果", "尚無成功分析的結果可寫入歷史紀錄。")
            return
        self._apply_note(rows)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "選擇歷史紀錄 CSV（可選擇既有檔案以附加寫入）",
            "history.csv",
            "CSV (*.csv)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path:
            return
        err = validate_save_path(path)
        if err:
            QMessageBox.critical(self, "無法寫入", err)
            return
        try:
            self.history_logger.append_many(rows, path)
            QMessageBox.information(self, "完成", f"已附加寫入 {len(rows)} 筆：\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "錯誤", f"寫入失敗：\n{e}")
