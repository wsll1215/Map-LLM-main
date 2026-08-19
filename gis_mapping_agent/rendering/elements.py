from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models.schemas import MapState
from ..utils.config import Config


class MapQualityChecker:
    """Minimal hard checks before/after accepting a rendered map."""

    def check(self, map_state: MapState, output_path: Optional[str] = None) -> Dict[str, Any]:
        errors = []
        warnings = []

        if not map_state.layers and not map_state.is_generalization_task:
            errors.append("no_layers")

        visible_layers = [layer for layer in map_state.layers if layer.visible]
        if map_state.layers and not visible_layers:
            warnings.append("no_visible_layers")

        empty_layers = [layer.name for layer in visible_layers if self._is_empty_layer(layer)]
        if empty_layers:
            warnings.append({"empty_layers": empty_layers})

        if not self._valid_extent(map_state.config.extent):
            errors.append("invalid_extent")

        crs_values = self._layer_crs_values(visible_layers)
        map_crs = str(map_state.config.crs.value if hasattr(map_state.config.crs, "value") else map_state.config.crs)
        if len(set(crs_values)) > 1:
            warnings.append({"mixed_crs": sorted(set(crs_values))})
        if crs_values and map_crs and any(crs != map_crs for crs in crs_values):
            warnings.append({"crs_mismatch": {"map": map_crs, "layers": sorted(set(crs_values))}})

        legend_warning = self._check_legend(map_state)
        if legend_warning:
            warnings.append(legend_warning)

        overlaps = self._element_overlaps(map_state)
        if overlaps:
            warnings.append({"element_overlaps": overlaps})

        label_overlaps = self._label_overlaps(map_state)
        if label_overlaps:
            warnings.append({"label_overlaps": label_overlaps})

        if output_path:
            path = Path(output_path)
            if not path.exists():
                errors.append("output_missing")
            elif path.stat().st_size <= 0:
                errors.append("output_empty")

        if map_state.is_generalization_task and map_state.generalization_output_path:
            path = Path(map_state.generalization_output_path)
            if not path.exists():
                warnings.append("generalization_output_missing")

        return {"ok": not errors, "errors": errors, "warnings": warnings}

    @staticmethod
    def _is_empty_layer(layer: Any) -> bool:
        if layer.gdf is not None:
            return bool(getattr(layer.gdf, "empty", False))
        return not layer.data_source and not layer.data

    @staticmethod
    def _layer_crs_values(layers: List[Any]) -> List[str]:
        values = []
        for layer in layers:
            crs = getattr(layer.gdf, "crs", None) if layer.gdf is not None else None
            if crs is not None:
                values.append(str(crs))
        return values

    @staticmethod
    def _check_legend(map_state: MapState) -> Optional[Dict[str, Any]]:
        layer_names = {layer.name for layer in map_state.layers if layer.visible}
        legend_labels = {item.label for item in map_state.legend_items}
        if not legend_labels:
            return None
        missing_layers = sorted(layer_names - legend_labels)
        extra_legend = sorted(legend_labels - layer_names)
        if missing_layers or extra_legend:
            return {"legend_layer_mismatch": {"missing_layers": missing_layers, "extra_legend": extra_legend}}
        return None

    def _element_overlaps(self, map_state: MapState) -> List[Dict[str, str]]:
        boxes: List[Tuple[str, Tuple[float, float, float, float]]] = []
        if map_state.scalebar:
            width, height = Config.HYPERPARAMETERS.QUALITY_SCALEBAR_BOX
            boxes.append(("scalebar", self._box_from_position(map_state.scalebar.get("position", Config.HYPERPARAMETERS.SCALEBAR_POSITION), width, height)))
        if map_state.compass:
            width, height = Config.HYPERPARAMETERS.QUALITY_COMPASS_BOX
            boxes.append(("compass", self._box_from_position(map_state.compass.get("position", Config.HYPERPARAMETERS.COMPASS_POSITION), width, height)))
        annotation_width, annotation_height = Config.HYPERPARAMETERS.QUALITY_ANNOTATION_BOX
        for legend in map_state.legends:
            boxes.append((f"legend:{legend.title or 'legend'}", self._legend_box(legend.position)))
        for annotation in map_state.annotations:
            boxes.append((f"annotation:{annotation.annotation_id}", self._box_from_position(annotation.position, annotation_width, annotation_height)))

        overlaps = []
        for i, (left_name, left_box) in enumerate(boxes):
            for right_name, right_box in boxes[i + 1:]:
                if self._boxes_overlap(left_box, right_box):
                    overlaps.append({"a": left_name, "b": right_name})
        return overlaps

    def _label_overlaps(self, map_state: MapState) -> List[Dict[str, str]]:
        annotation_width, annotation_height = Config.HYPERPARAMETERS.QUALITY_ANNOTATION_BOX
        boxes = [
            (annotation.annotation_id, self._box_from_position(annotation.position, annotation_width, annotation_height))
            for annotation in map_state.annotations
        ]
        overlaps = []
        for i, (left_name, left_box) in enumerate(boxes):
            for right_name, right_box in boxes[i + 1:]:
                if self._boxes_overlap(left_box, right_box):
                    overlaps.append({"a": left_name, "b": right_name})
        return overlaps

    @staticmethod
    def _box_from_position(position: Any, width: float, height: float) -> Tuple[float, float, float, float]:
        try:
            x, y = float(position[0]), float(position[1])
        except (TypeError, ValueError, IndexError):
            x, y = 0.5, 0.5
        return (x, y, min(1.0, x + width), min(1.0, y + height))

    @staticmethod
    def _legend_box(position: str) -> Tuple[float, float, float, float]:
        boxes = {
            "upper right": (0.72, 0.72, 1.0, 1.0),
            "upper left": (0.0, 0.72, 0.28, 1.0),
            "lower right": (0.72, 0.0, 1.0, 0.28),
            "lower left": (0.0, 0.0, 0.28, 0.28),
            "center": (0.36, 0.36, 0.64, 0.64),
        }
        return boxes.get(position, boxes["lower right"])

    @staticmethod
    def _boxes_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
        return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]

    @staticmethod
    def _valid_extent(extent: Any) -> bool:
        if not isinstance(extent, (list, tuple)) or len(extent) != 4:
            return False
        try:
            min_x, min_y, max_x, max_y = [float(value) for value in extent]
        except (TypeError, ValueError):
            return False
        return min_x < max_x and min_y < max_y
