from collections.abc import Sequence
from typing import List, Union

import numpy as np
import torch
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.collection import GeometryCollection

from sahi.annotation import BoundingBox, Category, Mask
from sahi.prediction import ObjectPrediction
from sahi.utils.shapely import ShapelyAnnotation, get_shapely_multipolygon


class ObjectPredictionList(Sequence):
    def __init__(self, list):
        self.list = list
        super().__init__()

    def __getitem__(self, i):
        if torch.is_tensor(i) or isinstance(i, np.ndarray):
            i = i.tolist()
        if isinstance(i, int):
            return ObjectPredictionList([self.list[i]])
        elif isinstance(i, (tuple, list)):
            accessed_mapping = map(self.list.__getitem__, i)
            return ObjectPredictionList(list(accessed_mapping))
        else:
            raise NotImplementedError(f"{type(i)}")

    def __setitem__(self, i, elem):
        if torch.is_tensor(i) or isinstance(i, np.ndarray):
            i = i.tolist()
        if isinstance(i, int):
            self.list[i] = elem
        elif isinstance(i, (tuple, list)):
            if len(i) != len(elem):
                raise ValueError()
            if isinstance(elem, ObjectPredictionList):
                for ind, el in enumerate(elem.list):
                    self.list[i[ind]] = el
            else:
                for ind, el in enumerate(elem):
                    self.list[i[ind]] = el
        else:
            raise NotImplementedError(f"{type(i)}")

    def __len__(self):
        return len(self.list)

    def __str__(self):
        return str(self.list)

    def extend(self, object_prediction_list):
        self.list.extend(object_prediction_list.list)

    def totensor(self):
        return object_prediction_list_to_torch(self)

    def tonumpy(self):
        return object_prediction_list_to_numpy(self)

    def tolist(self):
        if len(self.list) == 1:
            return self.list[0]
        else:
            return self.list


def repair_polygon(shapely_polygon: Polygon) -> Polygon:
    """
    Fix polygons
    :param shapely_polygon: Shapely polygon object
    :return:
    """
    if not shapely_polygon.is_valid:
        fixed_polygon = shapely_polygon.buffer(0)
        if fixed_polygon.is_valid:
            if isinstance(fixed_polygon, Polygon):
                return fixed_polygon
            elif isinstance(fixed_polygon, MultiPolygon):
                return max(fixed_polygon.geoms, key=lambda p: p.area)
            elif isinstance(fixed_polygon, GeometryCollection):
                polygons = [geom for geom in fixed_polygon.geoms if isinstance(geom, Polygon)]
                return max(polygons, key=lambda p: p.area) if polygons else shapely_polygon

    return shapely_polygon


def repair_multipolygon(shapely_multipolygon: MultiPolygon) -> MultiPolygon:
    """
    Fix invalid MultiPolygon objects
    :param shapely_multipolygon: Imported shapely MultiPolygon object
    :return:
    """
    if not shapely_multipolygon.is_valid:
        fixed_geometry = shapely_multipolygon.buffer(0)

        if fixed_geometry.is_valid:
            if isinstance(fixed_geometry, MultiPolygon):
                return fixed_geometry
            elif isinstance(fixed_geometry, Polygon):
                return MultiPolygon([fixed_geometry])
            elif isinstance(fixed_geometry, GeometryCollection):
                polygons = [geom for geom in fixed_geometry.geoms if isinstance(geom, Polygon)]
                return MultiPolygon(polygons) if polygons else shapely_multipolygon

    return shapely_multipolygon


def coco_segmentation_to_shapely(segmentation: Union[List, List[List]]):
    """
    Fix segment data in COCO format
    :param segmentation: segment data in COCO format
    :return:
    """
    if isinstance(segmentation, List) and all([not isinstance(seg, List) for seg in segmentation]):
        segmentation = [segmentation]
    elif isinstance(segmentation, List) and all([isinstance(seg, List) for seg in segmentation]):
        pass
    else:
        raise ValueError("segmentation must be List or List[List]")

    polygon_list = []

    for coco_polygon in segmentation:
        point_list = list(zip(coco_polygon[::2], coco_polygon[1::2]))
        shapely_polygon = Polygon(point_list)
        polygon_list.append(repair_polygon(shapely_polygon))

    shapely_multipolygon = repair_multipolygon(MultiPolygon(polygon_list))
    return shapely_multipolygon


def object_prediction_list_to_torch(object_prediction_list: ObjectPredictionList) -> torch.tensor:
    """
    Returns:
        torch.tensor of size N x [x1, y1, x2, y2, score, category_id]
    """
    num_predictions = len(object_prediction_list)
    torch_predictions = torch.zeros([num_predictions, 6], dtype=torch.float32)
    for ind, object_prediction in enumerate(object_prediction_list):
        torch_predictions[ind, :4] = torch.tensor(object_prediction.tolist().bbox.to_xyxy(), dtype=torch.float32)
        torch_predictions[ind, 4] = object_prediction.tolist().score.value
        torch_predictions[ind, 5] = object_prediction.tolist().category.id
    return torch_predictions


def object_prediction_list_to_numpy(object_prediction_list: ObjectPredictionList) -> np.ndarray:
    """
    Returns:
        np.ndarray of size N x [x1, y1, x2, y2, score, category_id]
    """
    num_predictions = len(object_prediction_list)
    numpy_predictions = np.zeros([num_predictions, 6], dtype=np.float32)
    for ind, object_prediction in enumerate(object_prediction_list):
        numpy_predictions[ind, :4] = np.array(object_prediction.tolist().bbox.to_xyxy(), dtype=np.float32)
        numpy_predictions[ind, 4] = object_prediction.tolist().score.value
        numpy_predictions[ind, 5] = object_prediction.tolist().category.id
    return numpy_predictions


def calculate_box_union(box1: Union[List[int], np.ndarray], box2: Union[List[int], np.ndarray]) -> List[int]:
    """
    Args:
        box1 (List[int]): [x1, y1, x2, y2]
        box2 (List[int]): [x1, y1, x2, y2]
    """
    box1 = np.array(box1)
    box2 = np.array(box2)
    left_top = np.minimum(box1[:2], box2[:2])
    right_bottom = np.maximum(box1[2:], box2[2:])
    return list(np.concatenate((left_top, right_bottom)))


def calculate_area(box: Union[List[int], np.ndarray]) -> float:
    """
    Args:
        box (List[int]): [x1, y1, x2, y2]
    """
    return (box[2] - box[0]) * (box[3] - box[1])


def calculate_intersection_area(box1: np.ndarray, box2: np.ndarray) -> float:
    """
    Args:
        box1 (np.ndarray): np.array([x1, y1, x2, y2])
        box2 (np.ndarray): np.array([x1, y1, x2, y2])
    """
    left_top = np.maximum(box1[:2], box2[:2])
    right_bottom = np.minimum(box1[2:], box2[2:])
    width_height = (right_bottom - left_top).clip(min=0)
    return width_height[0] * width_height[1]


def calculate_bbox_iou(pred1: ObjectPrediction, pred2: ObjectPrediction) -> float:
    """Returns the ratio of intersection area to the union"""
    box1 = np.array(pred1.bbox.to_xyxy())
    box2 = np.array(pred2.bbox.to_xyxy())
    area1 = calculate_area(box1)
    area2 = calculate_area(box2)
    intersect = calculate_intersection_area(box1, box2)
    return intersect / (area1 + area2 - intersect)


def calculate_bbox_ios(pred1: ObjectPrediction, pred2: ObjectPrediction) -> float:
    """Returns the ratio of intersection area to the smaller box's area"""
    box1 = np.array(pred1.bbox.to_xyxy())
    box2 = np.array(pred2.bbox.to_xyxy())
    area1 = calculate_area(box1)
    area2 = calculate_area(box2)
    intersect = calculate_intersection_area(box1, box2)
    smaller_area = np.minimum(area1, area2)
    return intersect / smaller_area


def has_match(
    pred1: ObjectPrediction, pred2: ObjectPrediction, match_type: str = "IOU", match_threshold: float = 0.5
) -> bool:
    if match_type == "IOU":
        threshold_condition = calculate_bbox_iou(pred1, pred2) > match_threshold
    elif match_type == "IOS":
        threshold_condition = calculate_bbox_ios(pred1, pred2) > match_threshold
    else:
        raise ValueError()
    return threshold_condition


def get_merged_mask(pred1: ObjectPrediction, pred2: ObjectPrediction) -> Mask:
    mask1 = pred1.mask
    mask2 = pred2.mask

    # buffer(0) is a quickhack to fix invalid polygons most of the time
    poly1 = get_shapely_multipolygon(mask1.segmentation).buffer(0)
    poly2 = get_shapely_multipolygon(mask2.segmentation).buffer(0)

    if poly1.is_empty:
        poly1 = coco_segmentation_to_shapely(mask1.segmentation)
    if poly2.is_empty:
        poly2 = coco_segmentation_to_shapely(mask2.segmentation)

    union_poly = poly1.union(poly2)
    if not hasattr(union_poly, "geoms"):
        union_poly = MultiPolygon([union_poly])
    else:
        union_poly = MultiPolygon([g.buffer(0) for g in union_poly.geoms if isinstance(g, Polygon)])
    union = ShapelyAnnotation(multipolygon=union_poly).to_coco_segmentation()
    return Mask(
        segmentation=union,
        full_shape=mask1.full_shape,
        shift_amount=mask1.shift_amount,
    )


def get_merged_score(
    pred1: ObjectPrediction,
    pred2: ObjectPrediction,
) -> float:
    scores: List[float] = [pred.score.value for pred in (pred1, pred2)]
    return max(scores)


def get_merged_bbox(pred1: ObjectPrediction, pred2: ObjectPrediction) -> BoundingBox:
    box1: List[int] = pred1.bbox.to_xyxy()
    box2: List[int] = pred2.bbox.to_xyxy()
    bbox = BoundingBox(box=calculate_box_union(box1, box2))
    return bbox


def get_merged_category(pred1: ObjectPrediction, pred2: ObjectPrediction) -> Category:
    if pred1.score.value > pred2.score.value:
        return pred1.category
    else:
        return pred2.category


def merge_object_prediction_pair(
    pred1: ObjectPrediction,
    pred2: ObjectPrediction,
) -> ObjectPrediction:
    shift_amount = pred1.bbox.shift_amount
    merged_bbox: BoundingBox = get_merged_bbox(pred1, pred2)
    merged_score: float = get_merged_score(pred1, pred2)
    merged_category: Category = get_merged_category(pred1, pred2)
    if pred1.mask and pred2.mask:
        merged_mask: Mask = get_merged_mask(pred1, pred2)
        segmentation = merged_mask.segmentation
        full_shape = merged_mask.full_shape
    else:
        segmentation = None
        full_shape = None
    return ObjectPrediction(
        bbox=merged_bbox.to_xyxy(),
        score=merged_score,
        category_id=merged_category.id,
        category_name=merged_category.name,
        segmentation=segmentation,
        shift_amount=shift_amount,
        full_shape=full_shape,
    )
