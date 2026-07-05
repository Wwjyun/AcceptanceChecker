# -*- coding: utf-8 -*-
"""背景執行緒分析 worker，避免大圖分析卡住 UI。"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QObject, Signal, Slot

from ..core.pipeline import AcceptancePipeline


class AnalysisWorker(QObject):
    """在背景執行緒跑一次 AcceptancePipeline.run。

    用法（在主執行緒）：
        thread = QThread()
        worker = AnalysisWorker(pipeline, path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(...)   # 參數為 AnalysisResult
        worker.failed.connect(...)     # 參數為錯誤訊息 str
        thread.start()
    """

    finished = Signal(object)  # AnalysisResult
    failed = Signal(str)

    def __init__(self, pipeline: AcceptancePipeline, file_path: str):
        super().__init__()
        self._pipeline = pipeline
        self._file_path = file_path

    @Slot()
    def run(self) -> None:
        try:
            result = self._pipeline.run(self._file_path)
        except Exception as e:  # noqa: BLE001 - 交由 UI 顯示
            self.failed.emit(str(e))
            return
        self.finished.emit(result)


class BatchWorker(QObject):
    """在背景執行緒依序分析多張影像，逐張回報結果。"""

    item_done = Signal(str, object)  # (file_path, AnalysisResult)
    item_failed = Signal(str, str)   # (file_path, error message)
    finished = Signal()

    def __init__(self, pipeline: AcceptancePipeline, file_paths: Sequence[str]):
        super().__init__()
        self._pipeline = pipeline
        self._file_paths = list(file_paths)

    @Slot()
    def run(self) -> None:
        for path in self._file_paths:
            try:
                result = self._pipeline.run(path)
            except Exception as e:  # noqa: BLE001
                self.item_failed.emit(path, str(e))
                continue
            self.item_done.emit(path, result)
        self.finished.emit()
