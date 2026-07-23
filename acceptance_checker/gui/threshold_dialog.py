# -*- coding: utf-8 -*-
"""門檻設定對話框：讓使用者在 UI 調整 Thresholds。"""

from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..core.config import Thresholds
from ..core.io_utils import validate_save_path

# 欄位的中文標籤（找不到時退回英文欄位名）
FIELD_LABELS = {
    "mean_gray_fail": "平均灰階高風險門檻",
    "mean_gray_warn": "平均灰階觀察門檻",
    "uniformity_fail": "均勻性高風險（min/max）",
    "uniformity_warn": "均勻性觀察（min/max）",
    "uniformity_good": "均勻性 良好參考值",
    "clipping_fail_pct": "clipping 高風險（%）",
    "clipping_warn_pct": "clipping 觀察（%）",
    "cnr_fail": "缺陷 CNR 高風險",
    "cnr_warn": "缺陷 CNR 觀察",
    "snr_fail": "單張空間 SNR proxy 高風險",
    "snr_warn": "單張空間 SNR proxy 觀察",
    "bg_std_warn": "背景 std 觀察",
    "bg_std_fail": "背景 std 高風險",
    "sharpness_fail": "清晰度高風險（Laplacian Var）",
    "sharpness_warn": "清晰度觀察（Laplacian Var）",
    "hist_spread_fail": "灰階展開高風險（P99-P01）",
    "hist_spread_warn": "灰階展開觀察（P99-P01）",
    "critical_score": "極高風險分數門檻（< 此分數則風險再升級）",
}


class ThresholdDialog(QDialog):
    """依 Thresholds 的 dataclass 欄位動態產生一組數值輸入。"""

    def __init__(self, thresholds: Thresholds, parent=None):
        super().__init__(parent)
        self.setWindowTitle("風險門檻設定")
        self._spins: dict[str, QDoubleSpinBox] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        for field in dataclasses.fields(Thresholds):
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setRange(0.0, 1_000_000.0)
            spin.setSingleStep(0.1)
            spin.setValue(float(getattr(thresholds, field.name)))
            self._spins[field.name] = spin
            form.addRow(FIELD_LABELS.get(field.name, field.name), spin)
        layout.addLayout(form)

        # 載入 / 儲存 JSON 設定檔
        file_row = QHBoxLayout()
        btn_load = QPushButton("載入設定檔…")
        btn_load.clicked.connect(self.on_load_json)
        btn_save = QPushButton("另存設定檔…")
        btn_save.clicked.connect(self.on_save_json)
        file_row.addWidget(btn_load)
        file_row.addWidget(btn_save)
        file_row.addStretch(1)
        layout.addLayout(file_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_thresholds(self) -> Thresholds:
        """回傳依目前輸入值組成的新 Thresholds。"""
        values = {name: spin.value() for name, spin in self._spins.items()}
        return Thresholds(**values)

    def _apply_to_spins(self, thresholds: Thresholds) -> None:
        for name, spin in self._spins.items():
            spin.setValue(float(getattr(thresholds, name)))

    def on_load_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入門檻設定檔", "", "JSON (*.json)")
        if not path:
            return
        try:
            self._apply_to_spins(Thresholds.load_json(path))
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "載入失敗", f"無法讀取門檻設定檔：\n{e}")

    def on_save_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "另存門檻設定檔", "thresholds.json", "JSON (*.json)"
        )
        if not path:
            return
        err = validate_save_path(path)
        if err:
            QMessageBox.critical(self, "無法儲存", err)
            return
        try:
            self.result_thresholds().save_json(path)
            QMessageBox.information(self, "完成", f"已儲存門檻設定：\n{path}")
        except OSError as e:
            QMessageBox.critical(self, "錯誤", f"儲存失敗：\n{e}")
