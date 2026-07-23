# -*- coding: utf-8 -*-
"""可框選 ROI 的預覽 QLabel。

顯示 sample 解析度的 QPixmap（等比例置中縮放），並讓使用者用滑鼠拖曳出一個
矩形。放開時把顯示座標換算回原始影像（sample）座標，透過 signal 送出，
供上層計算人工 ROI 的 CNR。
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel


class RoiSelectLabel(QLabel):
    """顯示影像並支援滑鼠拖曳框選 ROI 的標籤。"""

    # 送出 ROI 於原始影像座標的 (x, y, w, h)
    roi_selected = Signal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._src: Optional[QPixmap] = None      # sample 解析度的原圖
        self._drag_start: Optional[QPoint] = None
        self._drag_now: Optional[QPoint] = None
        self._roi_disp: Optional[QRect] = None   # 已確定的框（顯示座標）

    # ---------- 對外 ----------

    def set_image(self, pixmap: Optional[QPixmap]) -> None:
        """設定要顯示的原圖；換圖時清掉舊框。"""
        self._src = pixmap
        self._roi_disp = None
        self._drag_start = self._drag_now = None
        self.update()

    def clear_roi(self) -> None:
        self._roi_disp = None
        self.update()

    # ---------- 幾何換算 ----------

    def _draw_geometry(self) -> Optional[Tuple[float, float, float]]:
        """回傳 (scale, off_x, off_y)：影像→顯示的縮放與置中偏移。"""
        if self._src is None:
            return None
        iw, ih = self._src.width(), self._src.height()
        if iw == 0 or ih == 0:
            return None
        scale = min(self.width() / iw, self.height() / ih)
        disp_w, disp_h = iw * scale, ih * scale
        off_x = (self.width() - disp_w) / 2.0
        off_y = (self.height() - disp_h) / 2.0
        return scale, off_x, off_y

    def _to_image_rect(self, disp: QRect) -> Optional[Tuple[int, int, int, int]]:
        geo = self._draw_geometry()
        source = self._src
        if geo is None or source is None:
            return None
        scale, off_x, off_y = geo
        iw, ih = source.width(), source.height()

        x1 = (min(disp.left(), disp.right()) - off_x) / scale
        y1 = (min(disp.top(), disp.bottom()) - off_y) / scale
        x2 = (max(disp.left(), disp.right()) - off_x) / scale
        y2 = (max(disp.top(), disp.bottom()) - off_y) / scale

        x1 = int(max(0, min(iw, x1)))
        y1 = int(max(0, min(ih, y1)))
        x2 = int(max(0, min(iw, x2)))
        y2 = int(max(0, min(ih, y2)))
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2 - x1, y2 - y1

    # ---------- 滑鼠事件 ----------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._src is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag_start = event.position().toPoint()
        self._drag_now = self._drag_start
        self._roi_disp = None
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is None:
            return
        self._drag_now = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is None or self._drag_now is None:
            return
        disp = QRect(self._drag_start, self._drag_now).normalized()
        self._drag_start = self._drag_now = None

        rect = self._to_image_rect(disp)
        if rect is None:
            self._roi_disp = None
            self.update()
            return
        self._roi_disp = disp
        self.update()
        self.roi_selected.emit(*rect)

    # ---------- 繪製 ----------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)

        geo = self._draw_geometry()
        if self._src is not None and geo is not None:
            scale, off_x, off_y = geo
            target = QRect(
                int(off_x), int(off_y),
                int(self._src.width() * scale), int(self._src.height() * scale),
            )
            painter.drawPixmap(target, self._src)

        # 拖曳中的橡皮筋 / 已確定的框
        band = None
        if self._drag_start is not None and self._drag_now is not None:
            band = QRect(self._drag_start, self._drag_now).normalized()
        elif self._roi_disp is not None:
            band = self._roi_disp
        if band is not None:
            pen = QPen(Qt.GlobalColor.cyan)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(band)

        painter.end()
