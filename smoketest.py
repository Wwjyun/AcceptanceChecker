# -*- coding: utf-8 -*-
"""煙霧測試 (smoke test)。

快速驗證各子套件能 import、核心分析流程可跑、報告與 CSV 可輸出、
PySide6 介面可在無顯示器 (offscreen) 環境建立。

執行：
    python smoketest.py

成功回傳離開碼 0，任何一步失敗回傳 1。
GUI 測試會強制使用 Qt 的 offscreen 平台，因此可在 CI / 無螢幕環境跑。
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback

import cv2
import numpy as np


def _synthetic_good() -> np.ndarray:
    """亮度足夠、均勻、含一個清楚缺陷的影像。"""
    rng = np.random.default_rng(0)
    img = rng.normal(150, 3, (600, 900)).clip(0, 255).astype("uint8")
    cv2.circle(img, (450, 300), 14, 90, -1)  # 明顯缺陷
    return img


def _synthetic_bad() -> np.ndarray:
    """全黑、無訊號的影像，應被判為 FAIL。"""
    return np.zeros((400, 600), dtype="uint8")


def check_imports() -> None:
    import acceptance_checker  # noqa: F401
    from acceptance_checker import (  # noqa: F401
        AcceptanceJudge,
        AcceptancePipeline,
        CsvExporter,
        ImageAnalyzer,
        Metrics,
        RawImage,
        ReportBuilder,
        Thresholds,
    )
    from acceptance_checker.cli import main as cli_main  # noqa: F401
    from acceptance_checker.core import pipeline  # noqa: F401
    from acceptance_checker.reporting import text_report  # noqa: F401


def check_pipeline() -> None:
    from acceptance_checker import (
        AcceptanceJudge,
        ImageAnalyzer,
        RawImage,
        ReportBuilder,
    )

    analyzer = ImageAnalyzer()
    judge = AcceptanceJudge()
    builder = ReportBuilder()

    # 好圖
    raw = RawImage(_synthetic_good(), "uint8")
    m, sample, defect = analyzer.analyze(raw, "good.png")
    judge.judge(m)
    assert m.overall_status in {"PASS", "WARNING", "FAIL"}, m.overall_status
    assert sample.shape == (600, 900), sample.shape
    assert defect.overlay is not None and defect.overlay.ndim == 3
    assert m.auto_defect_count >= 1, "應偵測到至少一個缺陷候選"
    report_text = builder.build(m)
    assert "總判定" in report_text

    # 壞圖（全黑）必為 FAIL
    raw_bad = RawImage(_synthetic_bad(), "uint8")
    mb, _, _ = analyzer.analyze(raw_bad, "bad.png")
    judge.judge(mb)
    assert mb.overall_status == "FAIL", f"全黑圖應 FAIL，實得 {mb.overall_status}"


def check_reporting() -> None:
    from acceptance_checker import (
        AcceptanceJudge,
        CsvExporter,
        ImageAnalyzer,
        RawImage,
    )

    raw = RawImage(_synthetic_good(), "uint8")
    m, _, _ = ImageAnalyzer().analyze(raw, "good.png")
    AcceptanceJudge().judge(m)

    exporter = CsvExporter()
    # 用純 ASCII 暫存目錄，避開 OpenCV/檔案系統對非 ASCII 路徑的限制
    with tempfile.TemporaryDirectory() as d:
        single = os.path.join(d, "one.csv")
        multi = os.path.join(d, "many.csv")
        exporter.export(m, single)
        exporter.export_many([m, m], multi)
        assert os.path.getsize(single) > 0
        with open(multi, encoding="utf-8-sig") as f:
            lines = [ln for ln in f.read().splitlines() if ln]
        assert len(lines) == 3, f"header + 2 rows，實得 {len(lines)}"


def check_gui() -> None:
    # 強制 offscreen，讓無螢幕環境也能建立 QWidget
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from acceptance_checker.gui import AcceptanceCheckerWindow
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window = AcceptanceCheckerWindow()
    window.show()

    # 直接把一張分析結果塞進畫面，驗證更新流程不炸
    from acceptance_checker import RawImage
    from acceptance_checker.core.pipeline import AnalysisResult

    raw = RawImage(_synthetic_good(), "uint8")
    m, sample, defect = window.pipeline.analyzer.analyze(raw, "good.png")
    window.pipeline.judge.judge(m)
    window.result = AnalysisResult(
        metrics=m, gray8=raw.gray8, sample=sample, overlay=defect.overlay
    )
    window._update_report()
    window._update_preview()
    app.processEvents()
    window.close()


def main() -> int:
    checks = [
        ("imports", check_imports),
        ("pipeline", check_pipeline),
        ("reporting", check_reporting),
        ("gui", check_gui),
    ]
    failed = 0
    for name, fn in checks:
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {name}: {e}")
            traceback.print_exc()

    print("-" * 40)
    if failed:
        print(f"smoketest FAILED（{failed} 項）")
        return 1
    print("smoketest OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
