# -*- coding: utf-8 -*-
"""HistoryLogger（跨批次/跨時間分數歷史紀錄）的單元測試。"""

from __future__ import annotations

import csv
import os

from acceptance_checker import Metrics
from acceptance_checker.reporting import HistoryLogger


def _metrics(file_name: str, score: float) -> Metrics:
    m = Metrics()
    m.file_name = file_name
    m.quality_score = score
    m.risk_level = "量產風險低"
    m.overall_status = "PASS"
    return m


def test_append_creates_file_with_header_and_row(tmp_path):
    path = str(tmp_path / "history.csv")
    HistoryLogger().append(_metrics("a.png", 95.0), path)

    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["file_name"] == "a.png"
    assert rows[0]["quality_score"] == "95.0"


def test_append_many_multiple_calls_accumulate_not_overwrite(tmp_path):
    path = str(tmp_path / "history.csv")
    HistoryLogger().append_many([_metrics("a.png", 90.0), _metrics("b.png", 40.0)], path)
    HistoryLogger().append(_metrics("c.png", 20.0), path)

    with open(path, encoding="utf-8-sig", newline="") as f:
        content = f.read()
        rows = list(csv.DictReader(content.splitlines()))
    assert len(rows) == 3
    assert [r["file_name"] for r in rows] == ["a.png", "b.png", "c.png"]
    # 只應有一份表頭（BOM 不應在附加寫入時重複出現）
    assert content.count("timestamp") == 1


def test_append_many_with_empty_rows_does_nothing(tmp_path):
    path = str(tmp_path / "history.csv")
    HistoryLogger().append_many([], path)
    assert not os.path.exists(path)


def test_review_note_is_written(tmp_path):
    path = str(tmp_path / "history.csv")
    m = _metrics("a.png", 50.0)
    m.review_note = "已知風險，暫時放行"
    HistoryLogger().append(m, path)

    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["review_note"] == "已知風險，暫時放行"
