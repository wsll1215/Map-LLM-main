"""Deterministic guardrails for underspecified map requests."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def detect_ambiguity(user_input: str, *, has_map_state: bool) -> Optional[Dict[str, Any]]:
    """Return a clarification payload when a request is unsafe to execute yet.

    This guard runs before the LLM so low-information input cannot be silently
    converted into a guessed map or modification. It intentionally stays small;
    domain-specific interpretation remains the responsibility of the agent.
    """

    text = re.sub(r"\s+", "", str(user_input or "")).strip("，。！？,.!?;；")
    if not text:
        return None

    if _is_conflicting_request(text):
        return _decision(
            "你的需求里有冲突：是只保留道路，还是同时显示建筑？请选择一个优先目标。",
            ["layer_scope", "priority"],
            ["只显示道路", "道路和建筑都显示"],
            "conflicting_layer_scope",
        )

    has_data = bool(re.search(r"\.(?:shp|geojson|json|gpkg)\b|数据源|数据集|目录", text, re.I))
    has_location = bool(
        re.search(r"北京|上海|天津|重庆|武汉|石家庄|河南|河北|广东|广州|深圳|燕山大学|大学|校区|省|市|区|县", text)
    )
    has_layer = bool(
        re.search(r"行政区划|边界|道路|公路|铁路|高铁|交通|建筑|学校|河流|水系|地铁|路网|图层", text)
    )
    has_default_map = bool(re.search(r"地图|底图|区域图", text))
    has_map_action = bool(re.search(r"画|绘制|制作|生成|创建|制图|地图|出图|draw|create|generate", text, re.I))

    if not has_map_state:
        if text in {"北京", "武汉", "上海", "石家庄", "河南", "广东"}:
            return _decision(
                "你想绘制哪里的哪类地图？请补充地图范围和图层类型。",
                ["map_scope", "layer_type"],
                ["北京行政区划图", "北京道路图", "北京建筑图"],
                "location_without_map_type",
            )
        if has_map_action and (not has_location or (not has_layer and not has_default_map)) and not has_data:
            return _decision(
                "我还缺少关键信息：请说明地图范围，以及要显示的图层或数据源。",
                [field for field, missing in (
                    ("map_scope", not has_location),
                    ("layer_type", not has_layer and not has_default_map),
                ) if missing],
                ["北京行政区划图", "北京道路和铁路图", "上传或指定 Shapefile/GeoJSON"],
                "incomplete_create_request",
            )
        if len(text) <= 8 and not has_layer and not has_default_map and not has_data:
            return _decision(
                "请再具体一点：要绘制哪个区域、哪些内容？",
                ["map_scope", "layer_type"],
                ["北京行政区划图", "武汉道路图", "上传或指定数据文件"],
                "short_create_request",
            )
    else:
        vague_revision = re.search(r"弄漂亮点|再改一下|换个颜色|不对|还是那个|^嗯$|^恩$|改一下$|优化一下", text)
        if vague_revision or ("学校" in text and not re.search(r"清华|北大|北京大学|大学城", text)):
            return _decision(
                "你想调整哪一项？请说明目标图层、修改内容和期望效果。",
                ["target", "change"],
                ["把道路改成深绿色", "标注清华大学的位置", "隐藏建筑图层"],
                "incomplete_adjustment_request",
            )
        if not has_map_action and not has_layer and not has_data and len(text) <= 8:
            return _decision(
                "我没有识别到具体操作。请说明要添加、删除、隐藏还是修改哪个图层。",
                ["operation", "target"],
                ["添加道路图层", "隐藏建筑图层", "把道路改成深绿色"],
                "short_adjustment_request",
            )

    return None


def _is_conflicting_request(text: str) -> bool:
    return "只显示道路" in text and "建筑" in text and ("所有" in text or "加上" in text or "同时" in text)


def _decision(question: str, missing_fields: list[str], suggestions: list[str], reason: str) -> Dict[str, Any]:
    return {
        "question": question,
        "missing_fields": missing_fields,
        "suggestions": suggestions,
        "reason": reason,
    }
