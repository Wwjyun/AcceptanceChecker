# -*- coding: utf-8 -*-
"""跨批次 / 跨時間的分數歷史紀錄。

實務上分數不會擋線，真正有價值的是「同一產線的分數是否持續下滑」這種趨勢；
單筆結果看不出來，需要把每次分析的關鍵欄位持續累積寫入同一份 CSV，
之後才能拿這份歷史紀錄去比對趨勢，或作為量產導入風險的佐證。

寫入方式一律用附加（append）而非覆蓋：檔案不存在或為空時才寫入表頭，
之後每次呼叫都只附加新的一列，不會動到既有內容。
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Iterable

from ..core.metrics import Metrics

FIELDNAMES = [
    "timestamp",
    "session_id",
    "spec_version",
    "manifest_hash",
    "file_name",
    "file_path",
    "risk_level",
    "overall_status",
    "quality_score",
    "mean_gray",
    "uniformity_ratio",
    "signal_to_noise_ratio",
    "auto_defect_cnr_est",
    "bg_std_est",
    "hist_spread_p99_p01",
    "score_breakdown",
    "review_note",
]


class HistoryLogger:
    """把 Metrics 的關鍵欄位附加寫入一份跨時間的歷史紀錄 CSV。"""

    def append(self, m: Metrics, path: str) -> None:
        """單筆附加寫入。"""
        self.append_many([m], path)

    def append_many(self, rows: Iterable[Metrics], path: str) -> None:
        """多筆附加寫入；檔案不存在或為空時，先寫入表頭。"""
        rows = list(rows)
        if not rows:
            return
        write_header = not os.path.exists(path) or os.path.getsize(path) == 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if write_header:
                writer.writeheader()
            for m in rows:
                writer.writerow(
                    {
                        "timestamp": now,
                        "session_id": m.session_id,
                        "spec_version": m.spec_version,
                        "manifest_hash": m.manifest_hash,
                        "file_name": m.file_name,
                        "file_path": m.file_path,
                        "risk_level": m.risk_level,
                        "overall_status": m.overall_status,
                        "quality_score": m.quality_score,
                        "mean_gray": m.mean_gray,
                        "uniformity_ratio": m.uniformity_ratio,
                        "signal_to_noise_ratio": m.signal_to_noise_ratio,
                        "auto_defect_cnr_est": m.auto_defect_cnr_est,
                        "bg_std_est": m.bg_std_est,
                        "hist_spread_p99_p01": m.hist_spread_p99_p01,
                        "score_breakdown": m.score_breakdown,
                        "review_note": m.review_note,
                    }
                )
