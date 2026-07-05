# -*- coding: utf-8 -*-
"""把 OpenCV / numpy 影像轉成 Qt 可顯示的 QPixmap。"""

from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtGui import QImage, QPixmap


class ImagePreview:
    """負責 numpy(BGR/gray) -> QPixmap 的轉換與等比例縮放。"""

    def to_pixmap(self, img: Optional[np.ndarray]) -> Optional[QPixmap]:
        if img is None:
            return None

        img = np.ascontiguousarray(img)
        if img.ndim == 2:
            h, w = img.shape
            qimg = QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            # OpenCV 為 BGR，Qt 用 RGB
            rgb = np.ascontiguousarray(img[:, :, ::-1])
            h, w, _ = rgb.shape
            qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)

        # copy() 讓 QImage 擁有自己的緩衝，避免 numpy buffer 被回收
        return QPixmap.fromImage(qimg.copy())
