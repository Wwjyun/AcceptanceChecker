# -*- coding: utf-8 -*-
"""AOI Raw Image 光學驗收檢查工具 —— 啟動項。

啟動 PySide6 桌面介面：
    python main.py

若只想做命令列批次分析，請用：
    python -m acceptance_checker.cli.batch <images...>
"""

import sys

from acceptance_checker.gui import run_app


def main() -> int:
    return run_app()


if __name__ == "__main__":
    sys.exit(main())
