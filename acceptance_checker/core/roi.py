# -*- coding: utf-8 -*-
"""v4 ROI 定義、座標驗證、匯入匯出與 16 區量測。"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from .image import RawImage


class RoiError(ValueError):
    """ROI 定義、座標或檔案內容不合法。"""


class RoiType(str, Enum):
    """v4 驗收會使用的 ROI 類型。"""

    DEFECT_FREE_BACKGROUND = "defect_free_background"
    EFFECTIVE_INSPECTION_AREA = "effective_inspection_area"
    GOLDEN_DEFECT = "golden_defect"
    LOCAL_BACKGROUND_RING = "local_background_ring"
    SHADOW = "shadow"
    BLOCKED = "blocked"
    STITCH_SEAM = "stitch_seam"
    EQUIVALENT_CAMERA_POSITION = "equivalent_camera_position"


class RoiCreationMethod(str, Enum):
    """ROI 的建立來源。"""

    GUI_MANUAL = "gui_manual"
    JSON_IMPORT = "json_import"
    CSV_IMPORT = "csv_import"
    FIXED_RECIPE = "fixed_recipe"
    GENERATED = "generated"


@dataclass(frozen=True)
class RoiValidationIssue:
    """可顯示於 GUI/報表的 ROI 檢查結果。"""

    code: str
    message: str
    roi_ids: Tuple[str, ...]
    fatal: bool = True


@dataclass
class RoiDefinition:
    """一個使用原始影像座標的矩形 ROI。"""

    roi_id: str
    roi_type: RoiType
    x: int
    y: int
    width: int
    height: int
    creation_method: RoiCreationMethod
    operator: str
    version: str
    image_id: str
    coordinate_space: str = "original_image"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.roi_id.strip():
            raise RoiError("roi_id 不得為空")
        if self.coordinate_space != "original_image":
            raise RoiError("ROI 只能保存 original_image 座標")
        if self.width <= 0 or self.height <= 0:
            raise RoiError(f"ROI {self.roi_id} 不得為空或負尺寸")
        if self.x < 0 or self.y < 0:
            raise RoiError(f"ROI {self.roi_id} 座標不得為負")
        if not self.version.strip():
            raise RoiError("ROI version 不得為空")
        if not self.image_id.strip():
            raise RoiError("ROI image_id 不得為空")

    @property
    def box(self) -> Tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    def validate_for_shape(self, image_width: int, image_height: int) -> None:
        if image_width <= 0 or image_height <= 0:
            raise RoiError("影像尺寸必須為正數")
        if self.x2 > image_width or self.y2 > image_height:
            raise RoiError(
                f"ROI {self.roi_id} 超出影像範圍："
                f"box={self.box}, image={image_width}x{image_height}"
            )

    def overlaps(self, other: "RoiDefinition") -> bool:
        return (
            self.x < other.x2
            and other.x < self.x2
            and self.y < other.y2
            and other.y < self.y2
        )

    def to_sample_box(self, step: int) -> Tuple[int, int, int, int]:
        """把原圖 ROI 轉成等距取樣影像座標，完整覆蓋原 ROI。"""
        if step < 1:
            raise RoiError("step 必須 ≥ 1")
        x1 = self.x // step
        y1 = self.y // step
        x2 = int(math.ceil(self.x2 / step))
        y2 = int(math.ceil(self.y2 / step))
        return x1, y1, x2 - x1, y2 - y1

    @classmethod
    def from_sample_box(
        cls,
        *,
        roi_id: str,
        roi_type: RoiType,
        sample_box: Tuple[int, int, int, int],
        step: int,
        image_width: int,
        image_height: int,
        creation_method: RoiCreationMethod,
        operator: str,
        version: str,
        image_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "RoiDefinition":
        if step < 1:
            raise RoiError("step 必須 ≥ 1")
        x, y, width, height = sample_box
        if width <= 0 or height <= 0:
            raise RoiError("sample ROI 不得為空")
        x1 = max(0, min(image_width, x * step))
        y1 = max(0, min(image_height, y * step))
        x2 = max(x1, min(image_width, (x + width) * step))
        y2 = max(y1, min(image_height, (y + height) * step))
        roi = cls(
            roi_id=roi_id,
            roi_type=roi_type,
            x=x1,
            y=y1,
            width=x2 - x1,
            height=y2 - y1,
            creation_method=creation_method,
            operator=operator,
            version=version,
            image_id=image_id,
            metadata=dict(metadata or {}),
        )
        roi.validate_for_shape(image_width, image_height)
        return roi

    def to_dict(self) -> Dict[str, Any]:
        return {
            "roi_id": self.roi_id,
            "roi_type": self.roi_type.value,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "coordinate_space": self.coordinate_space,
            "creation_method": self.creation_method.value,
            "operator": self.operator,
            "version": self.version,
            "image_id": self.image_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        *,
        imported_as: Optional[RoiCreationMethod] = None,
    ) -> "RoiDefinition":
        try:
            method = imported_as or RoiCreationMethod(str(data["creation_method"]))
            return cls(
                roi_id=str(data["roi_id"]),
                roi_type=RoiType(str(data["roi_type"])),
                x=int(data["x"]),
                y=int(data["y"]),
                width=int(data["width"]),
                height=int(data["height"]),
                coordinate_space=str(data.get("coordinate_space", "original_image")),
                creation_method=method,
                operator=str(data.get("operator", "")),
                version=str(data["version"]),
                image_id=str(data["image_id"]),
                metadata=dict(data.get("metadata", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RoiError(f"ROI 欄位無效：{exc}") from exc


_CSV_FIELDS = [
    "roi_id",
    "roi_type",
    "x",
    "y",
    "width",
    "height",
    "coordinate_space",
    "creation_method",
    "operator",
    "version",
    "image_id",
    "metadata_json",
]


@dataclass
class RoiCollection:
    """同一 recipe/session 的 ROI 集合。"""

    rois: List[RoiDefinition] = field(default_factory=list)
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.schema_version.strip():
            raise RoiError("ROI schema_version 不得為空")
        ids = [roi.roi_id for roi in self.rois]
        duplicates = sorted({roi_id for roi_id in ids if ids.count(roi_id) > 1})
        if duplicates:
            raise RoiError(f"ROI ID 重複：{', '.join(duplicates)}")

    def validate(
        self,
        image_width: int,
        image_height: int,
        *,
        overlap_is_fatal: bool = False,
    ) -> List[RoiValidationIssue]:
        issues: List[RoiValidationIssue] = []
        for roi in self.rois:
            try:
                roi.validate_for_shape(image_width, image_height)
            except RoiError as exc:
                issues.append(
                    RoiValidationIssue("out_of_bounds", str(exc), (roi.roi_id,), True)
                )
        for left_index, left in enumerate(self.rois):
            for right in self.rois[left_index + 1 :]:
                if left.overlaps(right):
                    issues.append(
                        RoiValidationIssue(
                            "overlap",
                            f"ROI {left.roi_id} 與 {right.roi_id} 重疊",
                            (left.roi_id, right.roi_id),
                            overlap_is_fatal,
                        )
                    )
        return issues

    def assert_valid(
        self,
        image_width: int,
        image_height: int,
        *,
        overlap_is_fatal: bool = False,
    ) -> None:
        fatal = [
            issue
            for issue in self.validate(
                image_width, image_height, overlap_is_fatal=overlap_is_fatal
            )
            if issue.fatal
        ]
        if fatal:
            raise RoiError("; ".join(issue.message for issue in fatal))

    def by_type(self, roi_type: RoiType) -> List[RoiDefinition]:
        return [roi for roi in self.rois if roi.roi_type == roi_type]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "coordinate_space": "original_image",
            "rois": [roi.to_dict() for roi in self.rois],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(self.to_json())
            stream.write("\n")

    @classmethod
    def from_json(cls, text: str) -> "RoiCollection":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RoiError(f"ROI JSON 格式錯誤：{exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("rois"), list):
            raise RoiError("ROI JSON 必須包含 rois 陣列")
        if data.get("coordinate_space", "original_image") != "original_image":
            raise RoiError("ROI JSON 只能使用 original_image 座標")
        return cls(
            rois=[
                RoiDefinition.from_dict(dict(item), imported_as=RoiCreationMethod.JSON_IMPORT)
                for item in data["rois"]
            ],
            schema_version=str(data.get("schema_version", "1.0")),
        )

    @classmethod
    def load_json(cls, path: str) -> "RoiCollection":
        with open(path, "r", encoding="utf-8") as stream:
            return cls.from_json(stream.read())

    def save_csv(self, path: str) -> None:
        with open(path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for roi in self.rois:
                row = roi.to_dict()
                row["metadata_json"] = json.dumps(
                    row.pop("metadata"), ensure_ascii=False, sort_keys=True
                )
                writer.writerow(row)

    @classmethod
    def load_csv(cls, path: str) -> "RoiCollection":
        rois: List[RoiDefinition] = []
        with open(path, "r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            missing = [field for field in _CSV_FIELDS if field not in (reader.fieldnames or [])]
            if missing:
                raise RoiError(f"ROI CSV 缺少欄位：{', '.join(missing)}")
            for row_number, row in enumerate(reader, start=2):
                try:
                    metadata_text = row.pop("metadata_json", "") or "{}"
                    row["metadata"] = json.loads(metadata_text)
                    rois.append(
                        RoiDefinition.from_dict(
                            row, imported_as=RoiCreationMethod.CSV_IMPORT
                        )
                    )
                except (RoiError, json.JSONDecodeError) as exc:
                    raise RoiError(f"ROI CSV 第 {row_number} 列無效：{exc}") from exc
        return cls(rois=rois)


@dataclass(frozen=True)
class ZoneMeasurement:
    """有效檢查寬度固定切成 16 區後的原始尺度量測。"""

    zone_means: Tuple[float, ...]
    zone_boxes: Tuple[Tuple[int, int, int, int], ...]
    uniformity_ratio: float
    brightness_difference_pct: float
    minimum_mean: float
    maximum_mean: float
    unit: str


def extract_rois(
    image: np.ndarray,
    collection: RoiCollection,
    *,
    copy: bool = True,
) -> Dict[str, np.ndarray]:
    """用固定原圖座標把同一組 ROI 套到一張影像。"""
    if image.ndim != 2:
        raise RoiError("ROI 擷取只支援二維灰階量測平面")
    height, width = image.shape
    collection.assert_valid(width, height)
    result: Dict[str, np.ndarray] = {}
    for roi in collection.rois:
        view = image[roi.y : roi.y2, roi.x : roi.x2]
        if view.size == 0:
            raise RoiError(f"ROI {roi.roi_id} 擷取結果為空")
        result[roi.roi_id] = view.copy() if copy else view
    return result


def apply_fixed_rois(
    images: Iterable[Tuple[str, np.ndarray]],
    collection: RoiCollection,
) -> Dict[str, Dict[str, np.ndarray]]:
    """批次套用固定 ROI；image_id 必須與每個 ROI 的適用影像相符或為 ``*``。"""
    result: Dict[str, Dict[str, np.ndarray]] = {}
    for image_id, image in images:
        applicable = RoiCollection(
            [
                roi
                for roi in collection.rois
                if roi.image_id in ("*", image_id)
            ],
            schema_version=collection.schema_version,
        )
        result[image_id] = extract_rois(image, applicable)
    return result


def measure_16_zones(
    image: np.ndarray,
    effective_roi: RoiDefinition,
    *,
    full_scale: Optional[int] = None,
) -> ZoneMeasurement:
    """沿有效檢查區寬度固定切成 16 區並計算均值與 ``U=min/max``。"""
    if image.ndim != 2:
        raise RoiError("16 區量測只支援二維灰階量測平面")
    height, width = image.shape
    effective_roi.validate_for_shape(width, height)
    if effective_roi.roi_type != RoiType.EFFECTIVE_INSPECTION_AREA:
        raise RoiError("16 區量測必須使用 effective_inspection_area ROI")
    if effective_roi.width < 16:
        raise RoiError("有效檢查區寬度至少需要 16 px")
    if full_scale is not None and full_scale <= 0:
        raise RoiError("full_scale 必須為正數")

    means: List[float] = []
    boxes: List[Tuple[int, int, int, int]] = []
    for index in range(16):
        local_x1 = int(round(index * effective_roi.width / 16))
        local_x2 = int(round((index + 1) * effective_roi.width / 16))
        x1 = effective_roi.x + local_x1
        x2 = effective_roi.x + local_x2
        zone = image[effective_roi.y : effective_roi.y2, x1:x2]
        if zone.size == 0:
            raise RoiError(f"第 {index + 1} 區取樣結果為空")
        mean = float(np.mean(zone, dtype=np.float64))
        if full_scale is not None:
            mean = mean / full_scale * 100.0
        means.append(mean)
        boxes.append((x1, effective_roi.y, x2 - x1, effective_roi.height))

    minimum = min(means)
    maximum = max(means)
    uniformity = minimum / maximum if maximum > 0 else 0.0
    mean_of_zones = float(np.mean(means, dtype=np.float64))
    difference = (
        (maximum - minimum) / mean_of_zones * 100.0
        if mean_of_zones > 0
        else 0.0
    )
    return ZoneMeasurement(
        zone_means=tuple(means),
        zone_boxes=tuple(boxes),
        uniformity_ratio=uniformity,
        brightness_difference_pct=difference,
        minimum_mean=minimum,
        maximum_mean=maximum,
        unit="%FS" if full_scale is not None else "raw",
    )


def measure_raw_16_zones(raw: RawImage, effective_roi: RoiDefinition) -> ZoneMeasurement:
    """在 ``RawImage.raw_gray`` 上執行正式 16 區 %FS 量測。"""
    return measure_16_zones(
        raw.raw_gray,
        effective_roi,
        full_scale=raw.require_full_scale(),
    )
