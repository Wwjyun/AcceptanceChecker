# -*- coding: utf-8 -*-
"""v4 ROI 模型、I/O、座標與 16 區量測測試。"""

from __future__ import annotations

import numpy as np
import pytest

from acceptance_checker import (
    RawImage,
    RoiCollection,
    RoiCreationMethod,
    RoiDefinition,
    RoiError,
    RoiType,
    apply_fixed_rois,
    extract_rois,
    measure_16_zones,
    measure_raw_16_zones,
)


def make_roi(
    roi_id: str = "effective",
    roi_type: RoiType = RoiType.EFFECTIVE_INSPECTION_AREA,
    *,
    x: int = 0,
    y: int = 0,
    width: int = 32,
    height: int = 4,
    image_id: str = "image-a",
) -> RoiDefinition:
    return RoiDefinition(
        roi_id=roi_id,
        roi_type=roi_type,
        x=x,
        y=y,
        width=width,
        height=height,
        creation_method=RoiCreationMethod.FIXED_RECIPE,
        operator="王小明",
        version="roi-v1",
        image_id=image_id,
        metadata={"用途": "驗收"},
    )


def test_roi_json_and_csv_round_trip_preserve_traceability(tmp_path):
    collection = RoiCollection(
        [
            make_roi(),
            make_roi(
                "background",
                RoiType.DEFECT_FREE_BACKGROUND,
                x=4,
                y=5,
                width=8,
                height=6,
            ),
        ]
    )
    json_path = tmp_path / "roi_中文.json"
    csv_path = tmp_path / "roi_中文.csv"

    collection.save_json(str(json_path))
    collection.save_csv(str(csv_path))
    from_json = RoiCollection.load_json(str(json_path))
    from_csv = RoiCollection.load_csv(str(csv_path))

    assert from_json.rois[0].box == (0, 0, 32, 4)
    assert from_json.rois[0].operator == "王小明"
    assert from_json.rois[0].creation_method == RoiCreationMethod.JSON_IMPORT
    assert from_csv.rois[0].metadata == {"用途": "驗收"}
    assert from_csv.rois[0].creation_method == RoiCreationMethod.CSV_IMPORT


def test_roi_rejects_empty_negative_duplicate_and_out_of_bounds():
    with pytest.raises(RoiError, match="不得為空"):
        make_roi(width=0)
    with pytest.raises(RoiError, match="不得為負"):
        make_roi(x=-1)
    with pytest.raises(RoiError, match="重複"):
        RoiCollection([make_roi(), make_roi()])

    collection = RoiCollection([make_roi(x=20, width=20)])
    with pytest.raises(RoiError, match="超出影像範圍"):
        collection.assert_valid(32, 10)


def test_overlap_is_reported_and_can_be_promoted_to_fatal():
    collection = RoiCollection(
        [
            make_roi(width=20, height=10),
            make_roi(
                "ring",
                RoiType.LOCAL_BACKGROUND_RING,
                x=10,
                width=20,
                height=10,
            ),
        ]
    )

    issues = collection.validate(40, 20)
    assert [(issue.code, issue.fatal) for issue in issues] == [("overlap", False)]
    with pytest.raises(RoiError, match="重疊"):
        collection.assert_valid(40, 20, overlap_is_fatal=True)


def test_sample_coordinate_mapping_is_clipped_and_reversible():
    roi = RoiDefinition.from_sample_box(
        roi_id="manual",
        roi_type=RoiType.GOLDEN_DEFECT,
        sample_box=(2, 3, 10, 20),
        step=4,
        image_width=45,
        image_height=80,
        creation_method=RoiCreationMethod.GUI_MANUAL,
        operator="",
        version="1",
        image_id="image-a",
    )

    assert roi.box == (8, 12, 37, 68)
    assert roi.to_sample_box(4) == (2, 3, 10, 17)


def test_extract_and_batch_apply_fixed_rois():
    image_a = np.arange(100, dtype=np.uint16).reshape(10, 10)
    image_b = image_a + 100
    collection = RoiCollection(
        [
            make_roi(
                "common",
                RoiType.DEFECT_FREE_BACKGROUND,
                x=1,
                y=2,
                width=3,
                height=4,
                image_id="*",
            ),
            make_roi(
                "only-a",
                RoiType.SHADOW,
                x=5,
                y=1,
                width=2,
                height=2,
                image_id="image-a",
            ),
        ]
    )

    one = extract_rois(image_a, RoiCollection([collection.rois[0]]))
    batch = apply_fixed_rois([("image-a", image_a), ("image-b", image_b)], collection)

    assert one["common"].shape == (4, 3)
    assert set(batch["image-a"]) == {"common", "only-a"}
    assert set(batch["image-b"]) == {"common"}
    assert int(batch["image-b"]["common"][0, 0]) == 121


def test_measure_16_zones_uses_effective_width_and_raw_scale():
    image = np.zeros((6, 40), dtype=np.uint16)
    for index in range(16):
        image[1:5, 4 + index * 2 : 4 + (index + 1) * 2] = (index + 1) * 10
    roi = make_roi(x=4, y=1, width=32, height=4)

    result = measure_16_zones(image, roi)

    assert len(result.zone_means) == 16
    assert result.zone_means == tuple(float((index + 1) * 10) for index in range(16))
    assert result.uniformity_ratio == pytest.approx(10 / 160)
    assert result.brightness_difference_pct == pytest.approx((160 - 10) / 85 * 100)
    assert result.zone_boxes[0] == (4, 1, 2, 4)
    assert result.zone_boxes[-1] == (34, 1, 2, 4)
    assert result.unit == "raw"


def test_raw_16_zone_measurement_reports_percent_full_scale():
    full_scale = 4095
    image = np.full((4, 32), full_scale // 2, dtype=np.uint16)
    raw = RawImage.from_array(image, bit_depth=12)
    roi = make_roi(width=32, height=4)

    result = measure_raw_16_zones(raw, roi)

    assert result.unit == "%FS"
    assert result.zone_means[0] == pytest.approx((full_scale // 2) / full_scale * 100)
    assert result.uniformity_ratio == pytest.approx(1.0)


def test_16_zone_measurement_rejects_wrong_type_and_narrow_roi():
    image = np.zeros((10, 20), dtype=np.uint8)
    with pytest.raises(RoiError, match="effective_inspection_area"):
        measure_16_zones(
            image,
            make_roi(
                roi_type=RoiType.DEFECT_FREE_BACKGROUND,
                width=16,
                height=4,
            ),
        )
    with pytest.raises(RoiError, match="至少需要 16"):
        measure_16_zones(image, make_roi(width=15, height=4))
