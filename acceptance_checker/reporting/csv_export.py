# -*- coding: utf-8 -*-
"""CSV 報告匯出。"""

from __future__ import annotations

import csv
from typing import Iterable, List

from ..core.metrics import Metrics


class CsvExporter:
    """把一或多筆 Metrics 匯出成 CSV。"""

    def export(self, m: Metrics, save_path: str) -> None:
        """單筆匯出成單列 CSV。"""
        self.export_many([m], save_path)

    def export_many(self, rows: Iterable[Metrics], save_path: str) -> None:
        """多筆匯出成多列 CSV（欄位取自第一筆）。"""
        rows = list(rows)
        if not rows:
            return
        fieldnames: List[str] = list(rows[0].as_dict().keys())
        with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for m in rows:
                writer.writerow(m.as_dict())
