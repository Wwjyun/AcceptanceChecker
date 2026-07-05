# -*- coding: utf-8 -*-
"""命令列批次分析：不開 GUI，直接對一或多張圖輸出判定與 CSV。

用法：
    python -m acceptance_checker.cli.batch image1.bmp image2.tif
    python -m acceptance_checker.cli.batch --csv out.csv *.bmp
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from ..core.metrics import Metrics
from ..core.pipeline import AcceptancePipeline
from ..reporting import CsvExporter, ReportBuilder


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AOI raw image 批次驗收")
    parser.add_argument("images", nargs="+", help="要分析的影像檔")
    parser.add_argument("--csv", dest="csv_path", help="彙整結果輸出的 CSV 路徑")
    parser.add_argument("--quiet", action="store_true", help="只印狀態，不印完整報告")
    args = parser.parse_args(argv)

    pipeline = AcceptancePipeline()
    report_builder = ReportBuilder()
    csv_exporter = CsvExporter()

    results: List[Metrics] = []
    exit_code = 0

    for path in args.images:
        try:
            result = pipeline.run(path)
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] {path}: {e}", file=sys.stderr)
            exit_code = 2
            continue

        m = result.metrics
        results.append(m)

        if args.quiet:
            print(f"{m.overall_status}\t{m.file_name}")
        else:
            print(report_builder.build(m))
            print("-" * 60)

        if m.overall_status == "FAIL" and exit_code == 0:
            exit_code = 1

    if args.csv_path:
        csv_exporter.export_many(results, args.csv_path)
        print(f"已寫入 CSV：{args.csv_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
