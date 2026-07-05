# -*- coding: utf-8 -*-
"""輸出路徑相關的共用檢查。"""

from __future__ import annotations

import os
from typing import Optional


def validate_save_path(path: str) -> Optional[str]:
    """檢查存檔路徑是否可寫。

    可寫回傳 None；否則回傳一段人類可讀的錯誤說明（供 UI/CLI 顯示）。
    檢查項目：
    - 父目錄存在且為目錄
    - 父目錄具寫入權限
    - 若檔案已存在，該檔本身可寫（非唯讀）
    """
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        return f"目錄不存在：{directory}"
    if not os.access(directory, os.W_OK):
        return f"目錄沒有寫入權限：{directory}"
    if os.path.exists(path) and not os.access(path, os.W_OK):
        return f"檔案為唯讀，無法覆寫：{path}"
    return None
