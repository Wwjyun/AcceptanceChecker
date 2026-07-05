# AOI Raw Image 光學驗收檢查工具

這是一套給**線掃 / AOI（自動光學檢測）raw image 初步驗收**用的桌面小工具。

在把影像丟進正式的 AOI 檢測演算法之前，先用它快速判斷「這張原始影像的光學條件到底夠不夠好」。
它不是缺陷檢測器，而是**影像品質守門員**：協助工程師判斷問題出在光學／相機／光源，
還是真的該由後端軟體處理，避免「影像本身就爛，卻叫軟體背鍋」。

## 這個程式主要在做什麼

給一張影像，它會自動計算一組光學品質指標，並依門檻給出 **PASS / WARNING / FAIL**：

| 面向 | 指標 | 用途 |
| --- | --- | --- |
| 亮度 | 平均灰階、min/max、P01/P99、灰階展開 | 判斷進光量、相機感度是否足夠 |
| 動態範圍 | 低/高灰階 clipping % | 判斷是否過曝或壓死，資訊是否已流失 |
| 均勻性 | 沿寬度切 5 區的區塊平均、min/max 比值 | 判斷 700 mm 寬幅下左中右照明是否一致 |
| 缺陷可分離性 | 自動估算疑似缺陷的 CNR、contrast、候選數 | 判斷缺陷訊號能否從背景中分離（比單純 SNR 更貼近可檢性） |
| 雜訊 / 紋理 | 背景 std、robust noise sigma | 判斷材料紋理或雜訊是否會造成誤判 |
| 條紋 / FPN | 垂直 / 水平 stripe score | 抓固定方向的亮度變化（照明不均、固定圖案雜訊） |
| 清晰度 | Laplacian variance | 對焦 / 運動模糊的粗略 proxy |

另外會輸出：

- **文字驗收報告**（含每項數值、FAIL/WARNING 原因、工程解讀）
- **CSV 報告**（單列，欄位齊全，方便彙整多張）
- **異常候選圖**（原圖上用紅框標出自動估算的疑似缺陷區與其 CNR）

> 註：CNR 為自動估算，用來當作「raw image 是否含有可分離訊號」的 proxy，
> 不是最終檢測結果。NG 圖若要更準，建議後續加上手動畫 ROI 的版本。

## 安裝

需要 Python 3.9+（`Image.Resampling.LANCZOS` 需 Pillow 9+）。

```bash
pip install -r requirements.txt
```

`tkinter` 為 Python 標準庫，Windows / macOS 官方安裝檔已內建；
若在部分 Linux 發行版缺少，請自行安裝（例如 Debian/Ubuntu：`sudo apt install python3-tk`）。

## 使用方式

### 1. 圖形介面（GUI）

```bash
python aoi_raw_image_acceptance_checker.py
# 或
python -m acceptance_checker
```

操作：
1. 按「選擇圖片並分析」挑一張 raw image（支援 bmp / png / jpg / tif…）
2. 左側預覽會顯示紅框異常候選區，右側顯示完整驗收報告
3. 需要時按「匯出 CSV 報告」或「儲存異常候選圖」

### 2. 命令列批次（無 GUI）

```bash
# 分析多張並印出完整報告
python -m acceptance_checker.cli img1.bmp img2.tif

# 只看每張的判定狀態，並彙整成一份 CSV
python -m acceptance_checker.cli --quiet --csv result.csv *.bmp
```

CLI 的離開碼：`0` 全部通過、`1` 至少一張 FAIL、`2` 有檔案讀取失敗，方便接進自動化流程。

### 3. 當成函式庫使用

```python
from acceptance_checker import AcceptancePipeline, Thresholds

# 門檻可依現場標準覆寫
pipeline = AcceptancePipeline(Thresholds(mean_gray_fail=25, cnr_warn=4.0))
result = pipeline.run("sample.bmp")

print(result.metrics.overall_status)   # PASS / WARNING / FAIL
print(result.metrics.fail_reasons)
overlay = result.overlay               # 帶紅框的 BGR 影像 (numpy)
```

## 專案結構（OOP）

程式已從單一腳本重構為職責分明的套件：

```
acceptance_checker/
├── __init__.py     匯出公開類別
├── config.py       Thresholds        —— 判斷門檻設定（可覆寫）
├── metrics.py      Metrics           —— 所有指標與判定結果的資料結構
├── image.py        RawImage          —— 影像載入、8-bit 正規化、大圖取樣
├── detector.py     DefectDetector    —— 疑似缺陷偵測與 CNR 估算 / 產生紅框 overlay
├── analyzer.py     ImageAnalyzer     —— 把 RawImage 計算成 Metrics（不做判定）
├── judge.py        AcceptanceJudge   —— 依 Thresholds 判 PASS/WARNING/FAIL
├── report.py       ReportBuilder / CsvExporter —— 文字與 CSV 輸出
├── pipeline.py     AcceptancePipeline —— 串接 載入→分析→判定
├── gui.py          AcceptanceCheckerApp —— Tkinter 介面
├── cli.py          命令列批次進入點
└── __main__.py     python -m acceptance_checker 進入點
```

設計重點：
- **分析與判定分離**：`ImageAnalyzer` 只算數值，`AcceptanceJudge` 只做判定，門檻改變不影響計算。
- **UI 與邏輯分離**：核心流程 (`AcceptancePipeline`) 不依賴 tkinter，可在 CLI 或其他程式重用。
- **門檻可注入**：所有判斷門檻集中在 `Thresholds`，可依產線標準調整。

## 判斷門檻（預設值，可於 `config.py` 或建構時調整）

| 指標 | FAIL | WARNING |
| --- | --- | --- |
| 平均灰階 | < 30 | < 50 |
| 均勻性 min/max | < 0.50 | < 0.70 |
| clipping | > 1.0 % | > 0.1 % |
| 缺陷 CNR | < 3.0 | < 5.0 |
| 背景 std | > 10.0 | > 6.0 |
| 灰階展開 P99-P01 | < 15 | < 30 |
| 清晰度 Laplacian Var | < 20 | < 50 |

## 已知限制

- **Windows + 非 ASCII 路徑**：OpenCV 的 `imread` / `imwrite` 在含中文等非 ASCII 字元的路徑下可能失敗（此為 OpenCV 本身限制）。若遇到讀寫失敗，請改用純英數路徑。
- 清晰度、背景 std 等指標具**場景相依性**，主要用於同類影像間的比較，而非絕對閾值。
- 自動 CNR 為 proxy，僅代表訊號可分離性，不等同正式缺陷判定。
