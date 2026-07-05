# -*- coding: utf-8 -*-
"""依門檻對 Metrics 做 PASS / WARNING / FAIL 判定。"""

from __future__ import annotations

from typing import List

from .config import Thresholds
from .metrics import Metrics


class AcceptanceJudge:
    """把計算好的 Metrics 依 Thresholds 判定為 PASS / WARNING / FAIL。"""

    def __init__(self, thresholds: Thresholds | None = None):
        self.thresholds = thresholds or Thresholds()

    def judge(self, m: Metrics) -> Metrics:
        """就地更新 m 的 overall_status / fail_reasons / warn_reasons 並回傳。"""
        t = self.thresholds
        fail: List[str] = []
        warn: List[str] = []

        if m.mean_gray < t.mean_gray_fail:
            fail.append(f"平均灰階過低：{m.mean_gray:.1f} < {t.mean_gray_fail}")
        elif m.mean_gray < t.mean_gray_warn:
            warn.append(f"平均灰階偏低：{m.mean_gray:.1f} < {t.mean_gray_warn}")

        if m.uniformity_ratio < t.uniformity_fail:
            fail.append(f"左右/分區均勻性不合格：{m.uniformity_ratio:.2f} < {t.uniformity_fail}")
        elif m.uniformity_ratio < t.uniformity_warn:
            warn.append(f"左右/分區均勻性偏差：{m.uniformity_ratio:.2f} < {t.uniformity_warn}")

        if m.low_clip_pct > t.clipping_fail_pct:
            fail.append(f"低灰階 clipping 過高：{m.low_clip_pct:.2f}% > {t.clipping_fail_pct}%")
        elif m.low_clip_pct > t.clipping_warn_pct:
            warn.append(f"低灰階 clipping 偏高：{m.low_clip_pct:.2f}% > {t.clipping_warn_pct}%")

        if m.high_clip_pct > t.clipping_fail_pct:
            fail.append(f"高灰階 clipping 過高：{m.high_clip_pct:.2f}% > {t.clipping_fail_pct}%")
        elif m.high_clip_pct > t.clipping_warn_pct:
            warn.append(f"高灰階 clipping 偏高：{m.high_clip_pct:.2f}% > {t.clipping_warn_pct}%")

        if m.hist_spread_p99_p01 < t.hist_spread_fail:
            fail.append(f"灰階分布太窄：P99-P01={m.hist_spread_p99_p01:.1f} < {t.hist_spread_fail}")
        elif m.hist_spread_p99_p01 < t.hist_spread_warn:
            warn.append(f"灰階分布偏窄：P99-P01={m.hist_spread_p99_p01:.1f} < {t.hist_spread_warn}")

        # 自動 CNR 若沒有找到候選缺陷，不一定 fail，可能是 PASS 圖。
        # 若有找到候選但 CNR 很低，代表異常訊號也不清楚。
        if m.auto_defect_count > 0:
            if m.auto_defect_cnr_est < t.cnr_fail:
                fail.append(f"自動估算缺陷 CNR 過低：{m.auto_defect_cnr_est:.2f} < {t.cnr_fail}")
            elif m.auto_defect_cnr_est < t.cnr_warn:
                warn.append(f"自動估算缺陷 CNR 偏低：{m.auto_defect_cnr_est:.2f} < {t.cnr_warn}")
        else:
            warn.append("未找到明顯異常候選區；若這是 NG 圖，代表缺陷訊號可能不足")

        if m.bg_std_est > t.bg_std_fail:
            fail.append(f"背景 std / 紋理偏高：{m.bg_std_est:.2f} > {t.bg_std_fail}")
        elif m.bg_std_est > t.bg_std_warn:
            warn.append(f"背景 std / 紋理偏高：{m.bg_std_est:.2f} > {t.bg_std_warn}")

        if m.sharpness_laplacian_var < t.sharpness_fail:
            fail.append(f"清晰度 proxy 過低：Laplacian Var={m.sharpness_laplacian_var:.1f}")
        elif m.sharpness_laplacian_var < t.sharpness_warn:
            warn.append(f"清晰度 proxy 偏低：Laplacian Var={m.sharpness_laplacian_var:.1f}")

        if fail:
            m.overall_status = "FAIL"
        elif warn:
            m.overall_status = "WARNING"
        else:
            m.overall_status = "PASS"

        m.fail_reasons = "；".join(fail)
        m.warn_reasons = "；".join(warn)
        return m
