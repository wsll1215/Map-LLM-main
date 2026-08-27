"""Shared classification rules for server and browser map rendering."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd


DEFAULT_COLORS = [
    "#0B4F6C",
    "#1D7874",
    "#679289",
    "#F4C95D",
    "#EE964B",
    "#C44536",
    "#7B2CBF",
]
NO_DATA_COLOR = "#CBD5E1"


def build_render_spec(
    gdf: Any,
    attribute: str,
    method: str = "quantile",
    classes: int = 5,
    colors: Sequence[str] | None = None,
    no_data_color: str = NO_DATA_COLOR,
) -> Dict[str, Any]:
    """Build a JSON-safe render specification from a GeoDataFrame column."""
    base = {
        "enabled": False,
        "attribute": attribute,
        "method": method,
        "classes": max(2, min(int(classes or 5), 9)),
        "breaks": [],
        "labels": [],
        "colors": list(colors or DEFAULT_COLORS),
        "no_data_color": no_data_color,
    }
    if not attribute or not hasattr(gdf, "columns") or attribute not in gdf.columns:
        return {**base, "warning_code": "attribute_not_found", "warning": f"字段不存在: {attribute}"}

    values = gdf[attribute]
    numeric = pd.to_numeric(values, errors="coerce")
    numeric_values = numeric.dropna().to_numpy(dtype=float)
    if len(numeric_values) == 0:
        categories = sorted({str(value) for value in values.dropna().tolist()})
        if categories:
            return _categorical_spec(base, categories)
        return {**base, "warning_code": "no_numeric_values", "warning": f"字段没有可用值: {attribute}"}

    clean_method = method if method in {"quantile", "equal_interval", "natural_breaks"} else "quantile"
    breaks = _class_breaks(numeric_values, clean_method, base["classes"])
    if len(breaks) < 2:
        return {**base, "warning_code": "insufficient_unique_values", "warning": f"字段可分级值不足: {attribute}"}

    class_count = len(breaks) - 1
    palette = _palette(base["colors"], class_count)
    labels = _labels(breaks)
    return {
        **base,
        "enabled": True,
        "kind": "numeric",
        "method": clean_method,
        "classes": class_count,
        "breaks": breaks,
        "labels": labels,
        "colors": palette,
    }


def _categorical_spec(base: Dict[str, Any], categories: Iterable[str]) -> Dict[str, Any]:
    values = list(categories)
    palette = _palette(base["colors"], len(values))
    return {
        **base,
        "enabled": True,
        "kind": "categorical",
        "method": "categorical",
        "classes": len(values),
        "values": values,
        "colors": palette,
        "value_colors": dict(zip(values, palette)),
    }


def _class_breaks(values: np.ndarray, method: str, classes: int) -> List[float]:
    unique = np.unique(values)
    if len(unique) <= 1:
        return [float(unique[0]), float(unique[0])] if len(unique) else []
    classes = min(classes, len(unique))
    if method == "equal_interval":
        raw = np.linspace(float(unique.min()), float(unique.max()), classes + 1)
    elif method == "natural_breaks":
        raw = _jenks_breaks(values, classes)
    else:
        raw = np.quantile(values, np.linspace(0, 1, classes + 1))
    breaks = sorted({round(float(value), 12) for value in raw})
    if breaks[0] > float(unique.min()):
        breaks.insert(0, float(unique.min()))
    if breaks[-1] < float(unique.max()):
        breaks.append(float(unique.max()))
    return breaks


def _jenks_breaks(values: np.ndarray, classes: int) -> List[float]:
    data = np.sort(np.asarray(values, dtype=float))
    n = len(data)
    lower = np.zeros((n + 1, classes + 1), dtype=int)
    variance = np.full((n + 1, classes + 1), np.inf, dtype=float)
    variance[0, :] = 0
    for row in range(1, n + 1):
        lower[row, 1] = 1
        variance[row, 1] = 0
    for count in range(2, classes + 1):
        for row in range(1, n + 1):
            if row < count:
                continue
            sum_value = 0.0
            sum_square = 0.0
            width = 0
            for start in range(row, 0, -1):
                value = data[start - 1]
                width += 1
                sum_value += value
                sum_square += value * value
                variance_segment = sum_square - (sum_value * sum_value) / width
                previous = variance[start - 1, count - 1]
                if previous + variance_segment < variance[row, count]:
                    lower[row, count] = start
                    variance[row, count] = previous + variance_segment
    breaks = [float(data[0])]
    row = n
    for count in range(classes, 1, -1):
        start = lower[row, count]
        breaks.append(float(data[start - 1]))
        row = start - 1
    breaks.append(float(data[-1]))
    return sorted(set(breaks))


def _palette(colors: Sequence[str], count: int) -> List[str]:
    palette = list(colors) or list(DEFAULT_COLORS)
    return [palette[index % len(palette)] for index in range(count)]


def _labels(breaks: Sequence[float]) -> List[str]:
    return [
        f"{breaks[index]:g} - {breaks[index + 1]:g}"
        for index in range(len(breaks) - 1)
    ]
