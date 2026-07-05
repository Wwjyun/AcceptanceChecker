# -*- coding: utf-8 -*-
"""命令列批次分析：不開 GUI，直接對一或多張圖輸出判定與 CSV。

用法：
    python -m acceptance_checker.cli image1.bmp image2.tif
    python -m acceptance_checker.cli --csv out.csv *.bmp
    python -m acceptance_checker.cli --jobs 4 --quiet *.bmp
"""

from __future__ import annotations

import argparse
import functools
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import List, Optional, Tuple

from ..core.config import Thresholds
from ..core.io_utils import validate_save_path
from ..core.metrics import Metrics
from ..core.pipeline import AcceptancePipeline
from ..reporting import CsvExporter, DriftReporter, ReportBuilder

logger = logging.getLogger("acceptance_checker.cli")

# 每個工作項目的結果：(路徑, Metrics 或 None, 錯誤訊息 或 None)
ItemResult = Tuple[str, Optional[Metrics], Optional[str]]


def analyze_one(
    file_path: str,
    max_pixels: int = 8_000_000,
    thresholds: Optional[Thresholds] = None,
    normalization: str = "linear",
) -> ItemResult:
    """分析單張並只回傳 Metrics（可跨行程 pickle，不帶大型影像陣列）。

    定義在模組層級，才能被 ProcessPoolExecutor 序列化。
    """
    try:
        pipeline = AcceptancePipeline(
            thresholds, max_pixels=max_pixels, normalization=normalization
        )
        result = pipeline.run(file_path)
    except Exception as e:  # noqa: BLE001
        return file_path, None, str(e)
    return file_path, result.metrics, None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AOI raw image 批次驗收")
    parser.add_argument("images", nargs="+", help="要分析的影像檔")
    parser.add_argument("--csv", dest="csv_path", help="彙整結果輸出的 CSV 路徑")
    parser.add_argument("--quiet", action="store_true", help="只印狀態，不印完整報告")
    parser.add_argument(
        "--jobs", type=int, default=1,
        help="平行分析的行程數（>1 時使用多行程；預設 1 為序列）",
    )
    parser.add_argument(
        "--max-pixels", type=int, default=8_000_000,
        help="分析取樣的像素上限（超大線掃圖可調高/調低；預設 8M）",
    )
    parser.add_argument(
        "--thresholds", dest="thresholds_path",
        help="門檻設定檔（JSON）路徑；未指定則用內建預設門檻",
    )
    parser.add_argument(
        "--normalize", default="linear", choices=["linear", "percentile"],
        help="16-bit 影像轉 8-bit 的方式：linear（÷257）或 percentile（1-99 百分位拉伸）",
    )
    parser.add_argument(
        "--log-level", default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="診斷訊息（錯誤/警告）的記錄等級；預設 WARNING",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s: %(message)s",
    )

    thresholds: Optional[Thresholds] = None
    if args.thresholds_path:
        try:
            thresholds = Thresholds.load_json(args.thresholds_path)
        except (OSError, ValueError) as e:
            logger.error("無法讀取門檻設定檔：%s", e)
            return 2

    # 先驗證 CSV 輸出路徑，避免分析完才發現無法寫出
    if args.csv_path:
        err = validate_save_path(args.csv_path)
        if err:
            logger.error("無法寫出 CSV：%s", err)
            return 2

    items = _analyze_all(args.images, args.jobs, args.max_pixels, thresholds, args.normalize)
    return _report_and_export(items, args, thresholds)


def _analyze_all(
    images: List[str], jobs: int, max_pixels: int,
    thresholds: Optional[Thresholds], normalization: str,
) -> List[ItemResult]:
    worker = functools.partial(
        analyze_one, max_pixels=max_pixels, thresholds=thresholds, normalization=normalization
    )
    if jobs > 1 and len(images) > 1:
        with ProcessPoolExecutor(max_workers=jobs) as executor:
            return list(executor.map(worker, images))
    return [worker(p) for p in images]


def _report_and_export(
    items: List[ItemResult], args: argparse.Namespace, thresholds: Optional[Thresholds]
) -> int:
    report_builder = ReportBuilder()
    results: List[Metrics] = []
    failed_files: List[str] = []
    exit_code = 0

    for path, m, error in items:
        if m is None:
            logger.error("%s: %s", path, error)
            failed_files.append(path)
            exit_code = 2
            continue

        results.append(m)
        if args.quiet:
            print(f"{m.risk_level or m.overall_status}\t{m.quality_score:.1f}\t{m.file_name}")
        else:
            print(report_builder.build(m, thresholds))
            print("-" * 60)
        if m.overall_status == "FAIL" and exit_code == 0:
            exit_code = 1

    _write_csv(CsvExporter(), results, args.csv_path)
    _print_summary(results, failed_files)
    if len(results) >= 2:
        print("-" * 60)
        print(DriftReporter(thresholds).build(results))
    return exit_code


def _write_csv(exporter: CsvExporter, results: List[Metrics], csv_path: Optional[str]) -> None:
    if not csv_path:
        return
    if not results:
        logger.warning("沒有任何影像分析成功，未產生 CSV。")
        return
    exporter.export_many(results, csv_path)
    print(f"已寫入 CSV：{csv_path}（{len(results)} 筆）")


def _print_summary(results: List[Metrics], failed_files: List[str]) -> None:
    counts = {"PASS": 0, "WARNING": 0, "FAIL": 0}
    for m in results:
        counts[m.overall_status] = counts.get(m.overall_status, 0) + 1
    print(
        "彙整："
        f"成功 {len(results)}（量產風險低 {counts['PASS']} / "
        f"量產觀察項 {counts['WARNING']} / 量產導入風險高 {counts['FAIL']}）、"
        f"讀取失敗 {len(failed_files)}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
