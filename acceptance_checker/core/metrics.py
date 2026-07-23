# -*- coding: utf-8 -*-
"""影像指標資料結構。"""

from dataclasses import asdict, dataclass


@dataclass
class Metrics:
    """單張影像的所有驗收指標與判定結果。"""

    file_name: str = ""
    file_path: str = ""
    width_px: int = 0
    height_px: int = 0
    dtype: str = ""
    bit_depth: int = 0
    full_scale: int = 0
    norm_method: str = ""
    analysis_step: int = 1
    session_id: str = ""
    spec_version: str = ""
    manifest_hash: str = ""

    mean_gray: float = 0.0
    std_gray: float = 0.0
    min_gray: float = 0.0
    max_gray: float = 0.0
    p01_gray: float = 0.0
    p99_gray: float = 0.0
    hist_spread_p99_p01: float = 0.0

    low_clip_pct: float = 0.0
    high_clip_pct: float = 0.0

    zone_1_left_mean: float = 0.0
    zone_2_left_mid_mean: float = 0.0
    zone_3_center_mean: float = 0.0
    zone_4_right_mid_mean: float = 0.0
    zone_5_right_mean: float = 0.0
    uniformity_ratio: float = 0.0

    bg_std_est: float = 0.0
    robust_noise_sigma: float = 0.0
    # legacy 欄位名；實值是單張 mean / robust spatial sigma proxy，不是時域 SNR。
    signal_to_noise_ratio: float = 0.0

    auto_defect_cnr_est: float = 0.0
    auto_defect_contrast_est: float = 0.0
    auto_defect_area_px_sampled: int = 0
    auto_defect_count: int = 0

    vertical_stripe_score: float = 0.0
    horizontal_stripe_score: float = 0.0
    sharpness_laplacian_var: float = 0.0

    quality_score: float = 0.0
    score_breakdown: str = ""
    risk_level: str = ""
    overall_status: str = "UNKNOWN"
    fail_reasons: str = ""
    warn_reasons: str = ""

    # 放行簽核 / 覆蓋理由：分數不擋線時，人工填寫的放行備註，會一併寫入 CSV 與歷史紀錄，
    # 作為「為何在低分情況下仍放行」的留痕依據。
    review_note: str = ""

    def as_dict(self) -> dict:
        """轉為 dict，供 CSV 匯出使用。"""
        return asdict(self)
