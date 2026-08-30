"""High-precision, side-effect-free rules for map intent recognition."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional

from ..specs.intent import FieldEvidence, Intent, LayerSlot, LocationSlot


RuleDecision = Literal["complete", "partial", "conflict", "unknown"]


ROLE_SYNONYMS = {
    "boundary": ("边界", "行政区", "行政区划", "boundary"),
    "road": ("主要道路", "道路", "公路", "路网", "高速", "highway", "road"),
    "railway": ("铁路", "高铁", "railway"),
    "river": ("河流", "河道", "水系", "river"),
    "primary_school": ("小学", "primary school"),
    "university": ("高校", "大学", "university"),
    "school": ("学校", "school"),
    "hospital": ("医院", "hospital"),
    "park": ("公园", "park"),
    "poi": ("兴趣点", "poi"),
}

_CONTROL_RULES = (
    ("cancel", ("取消", "停止", "终止", "放弃")),
    ("retry", ("重试", "再试一次", "重新执行")),
)
_QUERY_TERMS = ("查看", "查询", "显示当前", "列出", "有哪些")
_CREATE_TERMS = ("创建", "制作", "生成", "绘制", "画", "出图", "地图")
_CREATE_ACTION_TERMS = ("创建", "制作", "生成", "绘制", "画", "出图")
_MODIFY_TERMS = (
    "添加图层",
    "增加图层",
    "删除图层",
    "移除图层",
    "隐藏图层",
    "显示图层",
    "修改图层",
    "调整图层",
    "设置颜色",
    "改成",
)
_MODIFY_VERBS = ("添加", "增加", "删除", "移除", "隐藏", "修改", "调整", "设置")
_LOCATION_PREFIXES = (
    "请",
    "请你",
    "帮我",
    "给我",
    "给",
    "把",
    "将",
    "为",
    "在",
    "制作",
    "绘制",
    "生成",
    "创建",
    "显示",
    "展示",
    "查看",
    "查询",
    "标注",
    "做一张",
    "做",
)
_GENERIC_LOCATION_WORDS = {
    "地图",
    "道路",
    "主要道路",
    "公路",
    "路网",
    "河流",
    "河道",
    "水系",
    "小学",
    "学校",
    "高校",
    "大学",
    "医院",
    "公园",
    "主要",
    "所有",
    "各个",
    "各",
}
_LOCATION_ANCHORS = "地图|位置|分布|范围|区域|道路|路网|河流|水系|小学|学校|高校|大学|医院|公园"


@dataclass(frozen=True)
class RuleParseResult:
    """The partial semantic result produced before any LLM call."""

    intent: Intent
    field_evidence: Dict[str, FieldEvidence]
    missing_fields: List[str]
    conflicts: List[str]
    decision: RuleDecision
    llm_required: bool


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term.lower() in text.lower() for term in terms)


def _strip_location_prefix(value: str) -> str:
    candidate = value.strip("的，,。；;:： \t\r\n")
    changed = True
    while changed and candidate:
        changed = False
        for prefix in sorted(_LOCATION_PREFIXES, key=len, reverse=True):
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix) :].lstrip("的，,。；;:： ")
                changed = True
                break
    return candidate.strip("的，,。；;:： ")


def _valid_location_candidate(value: str) -> bool:
    candidate = _strip_location_prefix(value)
    if len(candidate) < 2 or candidate in _GENERIC_LOCATION_WORDS:
        return False
    if any(term.lower() in candidate.lower() for terms in ROLE_SYNONYMS.values() for term in terms):
        return False
    if any(token in candidate for token in ("跟", "和", "以及", "还有")):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", candidate))


def _extract_location_candidates(text: str) -> List[str]:
    candidates: List[str] = []

    # Administrative names are found independently of the action verb. This is
    # what makes "给我天津市的地图" equivalent to "绘制天津市地图".
    administrative_pattern = r"[\u4e00-\u9fffA-Za-z]{2,}?(?:省|市|区|县|州|盟|旗|镇|新区)"
    administrative_matches = list(re.finditer(administrative_pattern, text))
    # A second pass starts after a generic conjunction so that the first broad
    # match cannot swallow the next independent place name.
    administrative_matches.extend(
        re.finditer(rf"(?<=[，,、及和与跟])(?P<name>{administrative_pattern})", text)
    )
    for match in administrative_matches:
        candidate = _strip_location_prefix(match.groupdict().get("name") or match.group(0))
        if _valid_location_candidate(candidate) and candidate not in candidates:
            candidates.append(candidate)

    # Bare place names are only considered when followed by a semantic anchor;
    # this avoids treating arbitrary nouns in a sentence as locations.
    action_pattern = "|".join(re.escape(action) for action in _LOCATION_PREFIXES)
    for match in re.finditer(
        rf"(?:{action_pattern})(?P<candidate>[\u4e00-\u9fffA-Za-z]{{2,}}?)(?:的)?(?=(?:{_LOCATION_ANCHORS}))",
        text,
    ):
        candidate = _strip_location_prefix(match.group("candidate"))
        if _valid_location_candidate(candidate) and candidate not in candidates:
            candidates.append(candidate)

    return candidates


def _extract_explicit_sources(raw_text: str) -> List[str]:
    pattern = r"(?:[A-Za-z]:[\\/])?[^\s，,。；;]+\.(?:shp|geojson|json|gpkg)(?=[\s，,。；;]|$)"
    return list(dict.fromkeys(re.findall(pattern, raw_text, flags=re.IGNORECASE)))


def _precision(location: Optional[str]) -> Optional[str]:
    if not location:
        return None
    if location.endswith(("省", "州", "盟")):
        return "province"
    if location.endswith(("市", "区", "县", "旗", "镇", "新区")):
        return "city"
    return "place"


def _task_for(text: str, current_state: Optional[Any]) -> str:
    for task, terms in _CONTROL_RULES:
        if _contains_any(text, terms):
            return task
    if _contains_any(text, _QUERY_TERMS) and not _contains_any(text, _CREATE_ACTION_TERMS):
        return "query_map"
    if _contains_any(text, _MODIFY_TERMS) or (
        _contains_any(text, _MODIFY_VERBS) and "图层" in text
    ):
        return "modify_map"
    if _contains_any(text, _CREATE_TERMS) or _contains_any(
        text, tuple(term for terms in ROLE_SYNONYMS.values() for term in terms)
    ):
        return "create_map"
    return "clarification"


class RuleParser:
    """Extract only high-confidence semantic fields without side effects."""

    def parse(self, text: str, current_state: Optional[Any] = None) -> RuleParseResult:
        raw_text = str(text or "")
        normalized = _normalize(raw_text)
        task = _task_for(normalized, current_state)
        evidence: Dict[str, FieldEvidence] = {}
        missing_fields: List[str] = []
        conflicts: List[str] = []

        evidence["task"] = FieldEvidence(
            field="task",
            source="rule",
            confidence=1.0 if task != "clarification" else 0.0,
            evidence=raw_text,
            value=task,
            locked=task != "clarification",
        )

        locations = _extract_location_candidates(normalized)
        location = locations[0] if len(locations) == 1 else None
        if len(locations) > 1:
            conflicts.append("multiple_locations")
            missing_fields.append("location")
        elif location:
            evidence["location"] = FieldEvidence(
                field="location",
                source="rule",
                confidence=0.98,
                evidence=location,
                value=location,
                locked=True,
            )

        layers = [
            LayerSlot(role=role, required=True)
            for role, terms in ROLE_SYNONYMS.items()
            if _contains_any(normalized, terms)
        ]
        if not layers and task == "create_map" and "地图" in normalized:
            layers = [LayerSlot(role="boundary", required=False)]
        if layers:
            evidence["layers"] = FieldEvidence(
                field="layers",
                source="rule",
                confidence=0.96,
                evidence=", ".join(layer.role for layer in layers),
                value=[layer.model_dump(mode="json") for layer in layers],
                locked=True,
            )

        explicit_sources = _extract_explicit_sources(raw_text)
        if explicit_sources:
            evidence["explicit_sources"] = FieldEvidence(
                field="explicit_sources",
                source="user",
                confidence=1.0,
                evidence=", ".join(explicit_sources),
                value=explicit_sources,
                locked=True,
            )

        if task == "clarification":
            missing_fields.append("task")
        elif task == "modify_map" and current_state is None:
            missing_fields.append("current_map_state")
        elif task == "create_map" and not location and not explicit_sources:
            missing_fields.append("location")

        if task == "clarification" and not layers and not explicit_sources:
            missing_fields.append("layers")

        missing_fields = list(dict.fromkeys(missing_fields))
        intent = Intent(
            task=task if task != "clarification" else "clarification",
            location=LocationSlot(text=location, precision=_precision(location)),
            layers=layers,
            explicit_sources=explicit_sources,
        )

        if conflicts:
            decision: RuleDecision = "conflict"
            llm_required = False
        elif missing_fields:
            decision = "partial"
            llm_required = True
        elif task == "clarification":
            decision = "unknown"
            llm_required = True
        else:
            decision = "complete"
            llm_required = False

        return RuleParseResult(
            intent=intent,
            field_evidence=evidence,
            missing_fields=missing_fields,
            conflicts=conflicts,
            decision=decision,
            llm_required=llm_required,
        )
