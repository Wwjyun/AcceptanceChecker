# -*- coding: utf-8 -*-
"""人類可讀的文字驗收報告。"""

from __future__ import annotations

from ..core.config import Thresholds
from ..core.metrics import Metrics


class ReportBuilder:
    """把 Metrics 組成人類可讀的文字報告。"""

    STATUS_NOTE = {
        "PASS": "通過：raw image 指標目前未觸發主要風險。",
        "WARNING": "警告：影像可嘗試，但有量產穩定風險。",
        "FAIL": "不合格：建議回到光學/相機/光源條件修正，不應直接丟給軟體背鍋。",
    }

    def build(self, m: Metrics) -> str:
        note = self.STATUS_NOTE.get(m.overall_status, "")
        report = f"""
【總判定】
狀態：{m.overall_status}
說明：{note}

【檔案資訊】
檔名：{m.file_name}
路徑：{m.file_path}
尺寸：{m.width_px} x {m.height_px} px
原始 dtype：{m.dtype}
分析取樣 step：{m.analysis_step}

【整體灰階】
平均灰階：{m.mean_gray:.2f}
標準差：{m.std_gray:.2f}
最小/最大：{m.min_gray:.1f} / {m.max_gray:.1f}
P01 / P99：{m.p01_gray:.1f} / {m.p99_gray:.1f}
P99-P01 灰階展開：{m.hist_spread_p99_p01:.1f}
低灰階 clipping：{m.low_clip_pct:.4f} %
高灰階 clipping：{m.high_clip_pct:.4f} %

【700 mm 寬度分區均勻性】
左側 20% mean：{m.zone_1_left_mean:.2f}
左中 20% mean：{m.zone_2_left_mid_mean:.2f}
中間 20% mean：{m.zone_3_center_mean:.2f}
右中 20% mean：{m.zone_4_right_mid_mean:.2f}
右側 20% mean：{m.zone_5_right_mean:.2f}
均勻性 min/max：{m.uniformity_ratio:.3f}

【缺陷可分離性，自動估算】
自動候選缺陷數：{m.auto_defect_count}
最佳候選 CNR：{m.auto_defect_cnr_est:.3f}
最佳候選 contrast：{m.auto_defect_contrast_est:.3f}
最佳候選 sampled area：{m.auto_defect_area_px_sampled}
robust noise sigma：{m.robust_noise_sigma:.3f}

【背景與條紋風險】
背景 std proxy：{m.bg_std_est:.3f}
vertical stripe score：{m.vertical_stripe_score:.3f}
horizontal stripe score：{m.horizontal_stripe_score:.3f}

【清晰度 / 對焦 proxy】
Laplacian variance：{m.sharpness_laplacian_var:.3f}

【FAIL 原因】
{m.fail_reasons if m.fail_reasons else "無"}

【WARNING 原因】
{m.warn_reasons if m.warn_reasons else "無"}

【工程解讀】
1. 平均灰階太低，代表進光量或相機感度不足，軟體只能硬拉。
2. 均勻性太差，代表 700 mm 寬度下左中右亮度不一致，後續 threshold / recipe 會不穩。
3. CNR 太低，代表缺陷和背景不可分，這比單純 SNR 更接近 AOI 可檢性。
4. 背景 std 太高，代表正常紋理或雜訊會增加誤判。
5. clipping 太高代表資訊已經被壓死或過曝，後處理無法真正救回。
6. 清晰度 proxy 太低時，200 µm 缺陷可能被對焦或運動模糊吃掉。
"""
        return report.strip()

    def thresholds_hint(self, t: Thresholds) -> str:
        """回傳門檻摘要，供 UI 初始顯示。"""
        return (
            "預設判斷門檻：\n"
            f"- 平均灰階 < {t.mean_gray_fail}：FAIL；< {t.mean_gray_warn}：WARNING\n"
            f"- 均勻性 min/max < {t.uniformity_fail}：FAIL；< {t.uniformity_warn}：WARNING\n"
            f"- clipping > {t.clipping_fail_pct}%：FAIL；> {t.clipping_warn_pct}%：WARNING\n"
            f"- CNR < {t.cnr_fail}：FAIL；< {t.cnr_warn}：WARNING\n"
            f"- 背景 std > {t.bg_std_fail}：FAIL；> {t.bg_std_warn}：WARNING\n"
            "\n注意：CNR 是自動估算。NG 圖建議後續加手動畫 ROI 版本做更準。"
        )
