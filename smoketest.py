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
    assert "判讀說明" in report_text
    assert "逐項指標解讀" in report_text
    assert "建議處置" in report_text

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


def check_unicode_io() -> None:
    """含中文路徑的讀寫應正常（繞過 OpenCV 對非 ASCII 路徑的限制）。"""
    from acceptance_checker import AcceptancePipeline
    from acceptance_checker.core.image import imread_unicode, imwrite_unicode

    img = _synthetic_good()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "測試圖_中文.png")
        assert imwrite_unicode(path, img), "中文路徑寫檔失敗"
        assert os.path.getsize(path) > 0

        back = imread_unicode(path)
        assert back is not None, "中文路徑讀檔失敗"
        assert back.shape[:2] == img.shape[:2], back.shape

        # 完整 pipeline 也要能吃中文路徑
        result = AcceptancePipeline().run(path)
        assert result.metrics.overall_status in {"PASS", "WARNING", "FAIL"}


def check_cache() -> None:
    """同一張圖重開走快取（回傳同一物件）；檔案變動後失效並重算。"""
    from acceptance_checker import AcceptancePipeline
    from acceptance_checker.core.image import imwrite_unicode

    pipeline = AcceptancePipeline()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cache_測試.png")
        assert imwrite_unicode(path, _synthetic_good())

        first = pipeline.run(path)
        second = pipeline.run(path)
        assert first is second, "重複開啟同一張圖應命中快取（回傳同一物件）"

        # 覆寫成不同內容 → mtime/大小改變 → 應失效重算
        assert imwrite_unicode(path, _synthetic_bad())
        third = pipeline.run(path)
        assert third is not first, "檔案變動後應失效並重新分析"


def check_roi_cnr() -> None:
    """人工 ROI CNR：框在缺陷上 CNR 應明顯高於框在均勻背景上。"""
    from acceptance_checker.core.detector import roi_cnr

    img = _synthetic_good()  # 缺陷圓在 (450, 300) 半徑 14，值 90，背景 ~150

    on_defect = roi_cnr(img, (436, 286, 28, 28))
    on_flat = roi_cnr(img, (50, 50, 28, 28))
    assert on_defect.defect_area_px > 0
    assert on_defect.cnr > on_flat.cnr, (on_defect.cnr, on_flat.cnr)
    assert on_defect.cnr > 3.0, f"缺陷 ROI CNR 應偏高，實得 {on_defect.cnr:.2f}"

    # 超出範圍的 ROI 回傳空結果
    empty = roi_cnr(img, (10_000, 10_000, 20, 20))
    assert empty.defect_area_px == 0 and empty.cnr == 0.0


def check_drift() -> None:
    """跨圖漂移報告：灰階一致時 PASS，人為拉開平均灰階時升為 WARNING/FAIL。"""
    from acceptance_checker import AcceptanceJudge, ImageAnalyzer, RawImage
    from acceptance_checker.reporting import DriftReporter

    analyzer = ImageAnalyzer()
    judge = AcceptanceJudge()

    def metrics_for(offset: int):
        img = _synthetic_good().astype("int16")
        img = np.clip(img + offset, 0, 255).astype("uint8")
        m, _, _ = analyzer.analyze(RawImage(img, "uint8"), f"drift_{offset}.png")
        judge.judge(m)
        return m

    reporter = DriftReporter()

    # 一致的三張（幾乎無漂移）→ PASS
    stable = [metrics_for(0) for _ in range(3)]
    rep_stable = reporter.analyze(stable)
    assert rep_stable.drift_status == "PASS", rep_stable.drift_status

    # 明顯拉開平均灰階（0 / +40 / +80）→ 全距大 → 應非 PASS
    drifted = [metrics_for(0), metrics_for(40), metrics_for(80)]
    rep_drift = reporter.analyze(drifted)
    assert rep_drift.drift_status in {"WARNING", "FAIL"}, rep_drift.drift_status
    assert rep_drift.mean_gray_spread > rep_stable.mean_gray_spread

    text = reporter.build(drifted)
    assert "灰階漂移" in text


def check_thresholds_json() -> None:
    """門檻 JSON：round-trip 相等；未知欄位忽略、缺欄位沿用預設。"""
    from acceptance_checker.core.config import Thresholds

    custom = Thresholds(mean_gray_fail=25.0, cnr_warn=4.5, snr_warn=18.0, bg_std_fail=8.0)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "門檻_設定.json")  # 含中文路徑也要能存讀
        custom.save_json(path)
        loaded = Thresholds.load_json(path)
        assert loaded == custom, (loaded, custom)

    # 未知欄位忽略、缺欄位用預設
    partial = Thresholds.from_dict({"mean_gray_fail": 22, "不存在的欄位": 999})
    assert partial.mean_gray_fail == 22.0
    assert partial.cnr_fail == Thresholds().cnr_fail

    # 非數值欄位應報錯
    try:
        Thresholds.from_dict({"mean_gray_fail": "abc"})
    except ValueError:
        pass
    else:
        raise AssertionError("非數值門檻應丟 ValueError")


def check_normalization() -> None:
    """16-bit 正規化：percentile 拉伸應比 linear(÷257) 得到更高對比。"""
    from acceptance_checker.core.image import RawImage

    # 感測器只用低位元：16-bit 值集中在 0~4000（<< 65535）
    rng = np.random.default_rng(3)
    img16 = rng.normal(2000, 300, (300, 400)).clip(0, 65535).astype("uint16")

    lin, dtype_l, method_l = RawImage._normalize_to_8bit(img16, "linear")
    pct, dtype_p, method_p = RawImage._normalize_to_8bit(img16, "percentile", (1.0, 99.0))

    assert dtype_l == "uint16" and "linear" in method_l
    assert "percentile" in method_p
    # 低動態範圍下 linear 幾乎壓成一片暗、對比極低；percentile 應把對比拉開
    assert float(pct.std()) > float(lin.std()) * 3, (pct.std(), lin.std())

    # load() 也要帶出 norm_method
    raw = RawImage(_synthetic_good(), "uint8")
    assert raw.norm_method == "uint8-copy"


def check_gui() -> None:
    # 強制 offscreen，讓無螢幕環境也能建立 QWidget
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from acceptance_checker.gui import AcceptanceCheckerWindow

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
    # 模擬使用者框選 ROI，驗證人工 CNR 更新流程不炸
    window.on_roi_selected(436, 286, 28, 28)
    assert "ROI" in window.status_label.text()
    app.processEvents()
    window.close()


def check_gui_worker() -> None:
    """驗證背景執行緒分析：透過 worker 跑完並更新畫面，不阻塞、不崩潰。"""
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from acceptance_checker.core.image import imwrite_unicode
    from acceptance_checker.gui import AcceptanceCheckerWindow

    app = QApplication.instance() or QApplication([])
    window = AcceptanceCheckerWindow()

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "工件_worker.png")
        assert imwrite_unicode(path, _synthetic_good())

        # 等同按下「選擇圖片並分析」，但省去檔案對話框
        window._start_analysis(path)

        # 輪詢直到背景執行緒 teardown（_thread 歸 None）或逾時
        deadline = time.time() + 15.0
        while window._thread is not None and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)

    assert window._thread is None, "背景分析逾時未結束"
    assert window.result is not None, "背景分析未產生結果"
    assert window.btn_open.isEnabled(), "分析結束後 open 按鈕應恢復可用"
    window.close()


def check_cli() -> None:
    """CLI 批次：序列與平行（--jobs 2）都能跑並產生 CSV。"""
    from acceptance_checker.cli.batch import analyze_one, main
    from acceptance_checker.core.image import imwrite_unicode

    with tempfile.TemporaryDirectory() as d:
        paths = []
        for i in range(3):
            p = os.path.join(d, f"cli_{i}.png")
            assert imwrite_unicode(p, _synthetic_good())
            paths.append(p)

        # module-level worker 可直接呼叫
        _p, m, err = analyze_one(paths[0])
        assert err is None and m is not None

        # 序列 + CSV
        out1 = os.path.join(d, "serial.csv")
        rc1 = main(["--quiet", "--csv", out1, *paths])
        assert rc1 in (0, 1), rc1
        assert os.path.getsize(out1) > 0

        # 平行（多行程）
        out2 = os.path.join(d, "parallel.csv")
        rc2 = main(["--quiet", "--jobs", "2", "--csv", out2, *paths])
        assert rc2 in (0, 1), rc2
        with open(out2, encoding="utf-8-sig") as f:
            lines = [ln for ln in f.read().splitlines() if ln]
        assert len(lines) == 4, f"header + 3 rows，實得 {len(lines)}"


def check_batch_window() -> None:
    """批次視窗：加入多張圖、跑完 BatchWorker、表格填值、可匯出 CSV。"""
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from acceptance_checker.core.image import imwrite_unicode
    from acceptance_checker.gui.batch_window import BatchWindow

    app = QApplication.instance() or QApplication([])
    win = BatchWindow()

    with tempfile.TemporaryDirectory() as d:
        paths = []
        for i in range(3):
            p = os.path.join(d, f"批次_{i}.png")
            assert imwrite_unicode(p, _synthetic_good())
            paths.append(p)
        win._add_paths(paths)
        assert win.table.rowCount() == 3

        win.on_run()
        deadline = time.time() + 20.0
        while win._thread is not None and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)

        assert win._thread is None, "批次分析逾時未結束"
        assert len(win._metrics) == 3, f"應有 3 筆結果，實得 {len(win._metrics)}"

        out = os.path.join(d, "batch_out.csv")
        win.csv_exporter.export_many([win._metrics[r] for r in sorted(win._metrics)], out)
        with open(out, encoding="utf-8-sig") as f:
            lines = [ln for ln in f.read().splitlines() if ln]
        assert len(lines) == 4, f"header + 3 rows，實得 {len(lines)}"
    win.close()


def check_threshold_rejudge() -> None:
    """調整門檻後只重判、不重算指標，狀態應隨門檻改變。"""
    from acceptance_checker import AcceptanceJudge, ImageAnalyzer, RawImage, Thresholds

    raw = RawImage(_synthetic_good(), "uint8")
    m, _, _ = ImageAnalyzer().analyze(raw, "good.png")

    # 極寬鬆門檻 → 不應 FAIL
    loose = Thresholds(
        mean_gray_fail=0, mean_gray_warn=0, uniformity_fail=0, uniformity_warn=0,
        clipping_fail_pct=100, clipping_warn_pct=100, cnr_fail=0, cnr_warn=0,
        snr_fail=0, snr_warn=0,
        bg_std_warn=1e9, bg_std_fail=1e9, sharpness_fail=0, sharpness_warn=0,
        hist_spread_fail=0, hist_spread_warn=0,
    )
    AcceptanceJudge(loose).judge(m)
    loose_status = m.overall_status

    # 極嚴苛門檻 → 應 FAIL
    strict = Thresholds(mean_gray_fail=999, bg_std_fail=0.0)
    AcceptanceJudge(strict).judge(m)
    assert m.overall_status == "FAIL", f"嚴苛門檻應 FAIL，實得 {m.overall_status}"
    assert loose_status != "FAIL", f"寬鬆門檻不應 FAIL，實得 {loose_status}"


def main() -> int:
    checks = [
        ("imports", check_imports),
        ("pipeline", check_pipeline),
        ("reporting", check_reporting),
        ("unicode_io", check_unicode_io),
        ("cli", check_cli),
        ("cache", check_cache),
        ("roi_cnr", check_roi_cnr),
        ("drift", check_drift),
        ("thresholds_json", check_thresholds_json),
        ("normalization", check_normalization),
        ("threshold_rejudge", check_threshold_rejudge),
        ("gui", check_gui),
        ("gui_worker", check_gui_worker),
        ("batch_window", check_batch_window),
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
