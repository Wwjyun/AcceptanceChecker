# 優化 TODO

依「先修正正確性 → 再改體驗/效能 → 最後工程化」排序。每項標註影響範圍與大致工作量。

## P0 — 正確性 / 立即痛點

- [x] **中文（非 ASCII）路徑讀寫**：已於 `core/image.py` 新增 `imread_unicode` / `imwrite_unicode`
      （Python 開檔 + `cv2.imdecode` / `cv2.imencode`）。`RawImage.load`、GUI 存 overlay 皆改用之，
      smoketest 加 `unicode_io` 檢查。
- [x] **匯出前確認覆寫 / 目錄可寫**：新增 `core/io_utils.validate_save_path`，
      GUI 匯出 CSV / 存 overlay 前先驗證目錄存在、可寫、非唯讀，錯誤訊息更清楚。
- [x] **空結果的 CLI 行為**：`cli/batch.py` 先驗證 `--csv` 路徑；全部失敗時明確 `[WARN]`
      不產生空檔，並在結尾印出 PASS/WARNING/FAIL/讀取失敗 的彙整。

## P1 — 使用體驗

- [x] **分析改用背景執行緒（QThread / worker）**：新增 `gui/worker.py` 的 `AnalysisWorker`，
      `on_open_image` → `_start_analysis` 於 QThread 跑分析，期間停用按鈕並顯示「分析中」，
      完成/失敗以 signal 回主執行緒更新。smoketest 加 `gui_worker` 檢查。
- [x] **視窗縮放時重繪預覽**：`_update_preview` 保留原始 pixmap，覆寫 `resizeEvent` 依當前
      畫布大小重新等比例 scale。
- [x] **門檻可在 UI 調整並即時重判**：新增 `gui/threshold_dialog.py`（依 dataclass 欄位動態產生
      表單）與「門檻設定」按鈕；`pipeline.set_thresholds` 同步判定器，套用後只重跑
      `AcceptanceJudge` 不重算指標。smoketest 加 `threshold_rejudge`。
- [x] **批次拖放多張 + 結果表格**：新增 `gui/batch_window.py`（`QTableWidget` + 拖放），
      可一次分析多張、逐列顯示狀態與關鍵指標、雙擊看報告、一鍵彙整 CSV；主視窗加「批次分析」入口。

## P2 — 效能

- [x] **CLI 批次平行化**：`cli/batch.py` 新增 `--jobs N`，`N>1` 時以
      `ProcessPoolExecutor` 平行分析（回傳純 `Metrics` 避免 pickle 大陣列）；
      `N<=1` 維持序列並印完整報告。
- [x] **取樣參數可調**：`max_pixels` 已由 `ImageAnalyzer` / `AcceptancePipeline` 一路貫穿，
      CLI 新增 `--max-pixels`（平行路徑以 `functools.partial` 傳遞）；預設仍 8M。
- [x] **重運算快取**：`AcceptancePipeline` 以 (絕對路徑, mtime_ns, 大小) 為鍵的 bounded LRU
      快取分析結果；同圖重開命中快取，檔案變動或改門檻即失效。smoketest 加 `cache`。

## P3 — 功能延伸

- [x] **手動畫 ROI 的 CNR**：新增 `core/detector.roi_cnr`（缺陷框 vs 外圈 ring 背景）與
      `gui/roi_label.RoiSelectLabel`（拖曳框選、座標換算回 sample）；主視窗預覽可框選、
      即時顯示人工 CNR。smoketest 加 `roi_cnr`。
- [x] **多影像灰階漂移**：新增 `reporting/drift_report.py`（`DriftReporter` 統計平均灰階、均勻性、
      背景 std、CNR、灰階展開的跨圖分佈；以 `hist_spread_*` 判平均灰階漂移）；批次視窗加「跨圖漂移報告」
      按鈕、CLI ≥2 張時附印。smoketest 加 `drift`。
- [x] **門檻設定檔（JSON）**：`Thresholds` 新增 `to_dict/from_dict/save_json/load_json`
      （未知欄位忽略、缺欄位用預設、非數值報錯）；CLI 加 `--thresholds`、門檻對話框加「載入/另存設定檔」，
      附預設檔 `thresholds.default.json`。smoketest 加 `thresholds_json`。

## P4 — 工程化 / 品質

- [x] **加入 `pyproject.toml`**：setuptools 打包、宣告相依與進入點
      （`acceptance-checker` GUI、`acceptance-checker-cli` CLI）、`dev` optional 相依（pytest/ruff/mypy）；
      套件加 `__version__`。
- [x] **單元測試**：新增 `tests/`（pytest）涵蓋 `judge`、`analyzer`、`detector`/`roi_cnr`、
      `config` JSON（含邊界：全黑、飽和、均勻、單一缺陷、ROI 夾邊界）；`pyproject` 設 `pythonpath`/`testpaths`。共 27 項。
- [x] **logging 取代 print/traceback**：`cli/batch.py` 的診斷訊息（錯誤/警告）改走 `logging`
      並加 `--log-level`；報告/CSV/彙整仍為 stdout 輸出。`gui/app.py` 加 module logger 記錄分析失敗。
- [x] **型別檢查與 lint**：`pyproject` 加 `ruff`（E/F/W/I/B/N）與 `mypy` 設定，全碼 ruff 通過；
      新增 `.github/workflows/ci.yml` 跑 ruff + mypy + pytest + smoketest（offscreen Qt）。
- [x] **16-bit 正規化策略**：`RawImage.load` / `_normalize_to_8bit` 加 `normalization`
      （linear ÷257 或 percentile 百分位拉伸）與 `percentiles`；`Metrics.norm_method` 記錄方式並印於報告；
      pipeline/CLI（`--normalize`）貫穿。smoketest 加 `normalization`、`tests/test_image.py`。

## P5 — 風險溝通強化（分數用於留痕與提示，而非攔阻）

背景：實務上影像/批次幾乎一定要放行，`quality_score` / `risk_level` 無法真的擋線，
功能上應該優先服務「留痕、排優先序、看趨勢」這幾件事，而不是假裝自己是一道關卡。

- [x] **建議事項依扣分排序**：`recommendations.py` 新增 `_parse_score_deficits()`，解析
      `Metrics.score_breakdown`（`AcceptanceJudge.judge()` 已產生的 `"label points/weight；..."`
      字串）算出每個標籤的 `weight - points` 扣分；`Recommendation` 新增 `labels` 欄位對應
      `AcceptanceJudge.SCORE_WEIGHTS` 的標籤，`RecommendationBuilder.build()` 內的 `_rank()`
      依扣分由大到小穩定排序（未先呼叫 `judge()`／無 `score_breakdown` 時，安全退回原始呼叫順序）。
      不需改 `judge.py` 的簽章，改用解析既有字串而非新增結構化傳遞。
      測試：`tests/test_recommendations.py`（排序、無 breakdown 時的退回行為）。

- [x] **高風險區再分級**：`core/config.Thresholds` 新增 `critical_score`（預設 `30.0`）；
      `AcceptanceJudge._risk_level()` 在 `overall_status == "FAIL"` 時，依分數是否低於
      `critical_score` 再分出「量產導入風險極高」（更嚴重）與「量產導入風險高」（原本用字）；
      `overall_status` 本身（PASS/WARNING/FAIL）不受影響，CLI exit code 與既有測試斷言維持不變。
      `text_report.py` 的判讀說明依此分兩段文字；`gui/batch_window.py` 新增 `_CRITICAL_COLOR`
      （深紅）區分表格列顏色；`gui/threshold_dialog.py` 的 `FIELD_LABELS` 加上中文標籤；
      `thresholds.default.json` 補上欄位。測試：`tests/test_judge.py` 三項新增案例。

- [x] **跨批次/跨時間的分數歷史紀錄**：新增 `reporting/history_log.py` 的 `HistoryLogger`
      （`append` / `append_many`），每次呼叫皆以附加模式（`"a"` + `utf-8-sig`）寫入使用者指定的
      CSV，檔案不存在或為空才寫表頭，欄位含時間戳、檔名、`risk_level`、`quality_score`、
      各關鍵指標、`score_breakdown`、`review_note`。已驗證重複附加不會重複寫入 BOM。
      CLI 新增 `--history-log PATH`；GUI 批次視窗新增「附加寫入歷史紀錄…」按鈕。
      影響檔案：`reporting/history_log.py`（新）、`reporting/__init__.py`、`cli/batch.py`、
      `gui/batch_window.py`。測試：`tests/test_history_log.py`、smoketest `history_log`/`cli`。

- [x] **放行簽核 / 覆蓋理由欄位**：`core/metrics.Metrics` 新增 `review_note: str = ""`
      （隨 `as_dict()` / `asdict()` 自動流入 CSV 與歷史紀錄，無需額外程式碼）。
      CLI 新增 `--note "文字"`，套用到該次執行所有成功結果；GUI 主視窗與批次視窗都新增一列
      文字輸入框，匯出 CSV／附加寫入歷史紀錄前套用到當時的結果上（非必填）。
      影響檔案：`core/metrics.py`、`cli/batch.py`、`gui/app.py`、`gui/batch_window.py`。

- [x] **確認 CLI exit code 的實際用途**：結論是把它明確定位成「預設供人工/半自動流程參考，
      但呼叫端可自行選擇不當真」：新增 `--no-gate` 旗標，指定後 FAIL 判定不再把 exit code
      推到 `1`（讀取失敗仍回傳 `2`，因為那是真的錯誤而非品質判定）；未加旗標時行為與先前
      完全一致。README 的「CLI exit codes」章節已補充旗標說明與使用時機建議。
      影響檔案：`cli/batch.py`、`README.md`。
