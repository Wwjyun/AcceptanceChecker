# -*- coding: utf-8 -*-
"""Thresholds JSON 設定檔的單元測試。"""

from __future__ import annotations

import os

import pytest

from acceptance_checker import Thresholds


def test_round_trip(tmp_path):
    custom = Thresholds(mean_gray_fail=25.0, cnr_warn=4.5, snr_warn=18.0, bg_std_fail=8.0)
    path = os.path.join(tmp_path, "th.json")
    custom.save_json(path)
    assert Thresholds.load_json(path) == custom


def test_unicode_path_round_trip(tmp_path):
    path = os.path.join(tmp_path, "門檻_設定.json")
    Thresholds().save_json(path)
    assert Thresholds.load_json(path) == Thresholds()


def test_from_dict_ignores_unknown_and_keeps_defaults():
    t = Thresholds.from_dict({"mean_gray_fail": 22, "unknown_field": 999})
    assert t.mean_gray_fail == 22.0
    assert t.cnr_fail == Thresholds().cnr_fail


def test_from_dict_rejects_non_numeric():
    with pytest.raises(ValueError):
        Thresholds.from_dict({"mean_gray_fail": "abc"})


def test_load_json_rejects_non_object(tmp_path):
    path = os.path.join(tmp_path, "bad.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")
    with pytest.raises(ValueError):
        Thresholds.load_json(path)


def test_string_numeric_accepted():
    t = Thresholds.from_dict({"mean_gray_fail": "22.5"})
    assert t.mean_gray_fail == 22.5
