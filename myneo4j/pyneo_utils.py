import copy
import logging
import os
import re
import time

from py2neo import Graph, NodeMatcher

logger = logging.getLogger(__name__)

DEFAULT_GRAPH_NODE_LIMIT = 50
DEFAULT_GRAPH_QUERY_LIMIT = 200
DEFAULT_GRAPH_CACHE_TTL_SECONDS = 60

_GRAPH_RESULT_CACHE = {}

color = {
    "CLASS": "#5470c6",
    "TIME": "#e474c6",
    "LOC": "#147fc6",
    "RES": "#947dc6",
    "EVE": "#847986",
    "EVC": "#8374c6",
    "other": "#111111",
}

DISPLAY_NAME_FIELDS = (
    "Name",
    "name",
    "method_name",
    "algorithm_name",
    "scale_value",
    "integration_requirement",
)

UNIQUE_ID_FIELDS = (
    "RoID",
    "SeID",
    "MeID",
    "scheme_id",
    "selection_method_id",
    "selection_algorithm_id",
    "reference_id",
    "scale_integration_principle_id",
)

LABEL_ID_FIELD_MAP = {
    "Road": "RoID",
    "Segment": "SeID",
    "Mesh": "MeID",
    "SelectionScheme": "scheme_id",
    "SelectionMethod": "selection_method_id",
    "SelectionAlgorithm": "selection_algorithm_id",
    "Reference": "reference_id",
    "ScaleIntegrationPrinciple": "scale_integration_principle_id",
}

LABEL_DISPLAY_PREFIX_MAP = {
    "Road": "道路",
    "Segment": "路段",
    "Mesh": "网眼",
    "SelectionScheme": "方案",
    "SelectionMethod": "方法",
    "SelectionAlgorithm": "算法",
    "Reference": "参考文献",
    "ScaleIntegrationPrinciple": "尺度原则",
}


def get_node_by_name(g, node_type, name):
    matcher = NodeMatcher(g)
    endnode = matcher.match(node_type, name=name).first()
    if endnode is not None:
        return endnode
    return None


def get_str_by_dict(mydict):
    last = ""
    for key in mydict:
        last = str(key) + ":" + str(mydict[key]) + "<br>" + last
    return last


def get_primary_label(node):
    labels = list(node.labels)
    return labels[0] if labels else "other"


def is_placeholder_name(value):
    return str(value).strip() in {"", "未命名", "unknown", "Unknown", "null", "None"}


def get_node_display_name(label, properties):
    if label == "Road":
        road_name = properties.get("Name") or properties.get("name")
        road_id = properties.get("RoID")
        if road_name not in (None, "") and not is_placeholder_name(road_name):
            return str(road_name)
        if road_name not in (None, "") and road_id not in (None, ""):
            return f"{road_name}（RoID:{road_id}）"
        if road_id not in (None, ""):
            return f"道路 {road_id}"

    label_id_field = LABEL_ID_FIELD_MAP.get(label)
    if label_id_field:
        label_id_value = properties.get(label_id_field)
        if label_id_value not in (None, ""):
            prefix = LABEL_DISPLAY_PREFIX_MAP.get(label, label)
            return f"{prefix} {label_id_value}"

    for field in DISPLAY_NAME_FIELDS:
        value = properties.get(field)
        if value not in (None, ""):
            return str(value)

    for _, value in properties.items():
        if value not in (None, ""):
            return f"{label}:{value}"

    return None


def get_node_unique_key(node, label, properties, display_name):
    node_identity = getattr(node, "identity", None)
    if node_identity is not None:
        return f"{label}:{node_identity}"

    label_id_field = LABEL_ID_FIELD_MAP.get(label)
    if label_id_field:
        label_id_value = properties.get(label_id_field)
        if label_id_value not in (None, ""):
            return f"{label}:{label_id_value}"

    for field in UNIQUE_ID_FIELDS:
        value = properties.get(field)
        if value not in (None, ""):
            return f"{label}:{value}"

    if display_name:
        return f"{label}:{display_name}"

    return None


def _get_cache_key(start, relation, end):
    return (start or "", relation or "", end or "")


def _get_cached_graph_result(start, relation, end):
    cache_key = _get_cache_key(start, relation, end)
    cached_entry = _GRAPH_RESULT_CACHE.get(cache_key)
    if not cached_entry:
        return None

    expires_at, cached_value = cached_entry
    if expires_at <= time.time():
        _GRAPH_RESULT_CACHE.pop(cache_key, None)
        return None

    return copy.deepcopy(cached_value)


def _set_cached_graph_result(start, relation, end, value, ttl_seconds=DEFAULT_GRAPH_CACHE_TTL_SECONDS):
    cache_key = _get_cache_key(start, relation, end)
    _GRAPH_RESULT_CACHE[cache_key] = (
        time.time() + ttl_seconds,
        copy.deepcopy(value),
    )


def get_all_relation(start, relation, end):
    if start == "" and relation == "" and end == "":
        cached_result = _get_cached_graph_result(start, relation, end)
        if cached_result is not None:
            return cached_result

    datas = []
    links = []
    node_cache = set()
    link_cache = set()
    categories = []
    legend_data = []
    g = Graph(
        os.getenv("NEO4J_URL", "http://localhost:7474"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", ""),
    )
    mr = ""
    where_clauses = []
    params = {}
    default_graph = start == "" and relation == "" and end == ""

    if start != "":
        where_clauses.append("n.Name = $start")
        params["start"] = start
    if relation == "":
        mr = "r"
    else:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", relation):
            mr = "r:" + relation
        else:
            logger.warning("忽略非法关系类型: %s", relation)
            mr = "r"
    if end != "":
        where_clauses.append("b.Name = $end")
        params["end"] = end

    if default_graph:
        sql = (
            f"MATCH (n:Road)-[{mr}]-(b:Road) "
            f"RETURN n,r,b LIMIT {DEFAULT_GRAPH_QUERY_LIMIT}"
        )
    else:
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        sql = f"MATCH (n)-[{mr}]-(b) {where_sql} RETURN n,r,b LIMIT 300"

    nodes_data_all = g.run(sql, **params).data()

    for nodes_relations in nodes_data_all:
        start_label = get_primary_label(nodes_relations["n"])
        end_label = get_primary_label(nodes_relations["b"])

        start_props = dict(nodes_relations["n"])
        end_props = dict(nodes_relations["b"])

        start_display_name = get_node_display_name(start_label, start_props)
        end_display_name = get_node_display_name(end_label, end_props)
        if not start_display_name or not end_display_name:
            continue

        start_key = get_node_unique_key(
            nodes_relations["n"], start_label, start_props, start_display_name
        )
        end_key = get_node_unique_key(
            nodes_relations["b"], end_label, end_props, end_display_name
        )
        if not start_key or not end_key:
            continue

        try:
            relation_name = type(nodes_relations["r"]).__name__
        except Exception as exc:
            logger.debug("解析知识图谱关系失败: %s", exc)
            continue

        existing_start = start_key in node_cache
        existing_end = end_key in node_cache
        new_nodes_needed = int(not existing_start) + int(not existing_end)
        if new_nodes_needed > 0 and len(node_cache) + new_nodes_needed > DEFAULT_GRAPH_NODE_LIMIT:
            continue

        if not existing_start:
            datas.append(
                {
                    "name": str(start_key),
                    "display_name": str(start_display_name),
                    "attr": start_props,
                    "color": color.get(start_label, color["other"]),
                    "des": get_str_by_dict(start_props),
                    "category": start_label,
                }
            )
            node_cache.add(start_key)

        if not existing_end:
            datas.append(
                {
                    "name": str(end_key),
                    "display_name": str(end_display_name),
                    "attr": end_props,
                    "color": color.get(end_label, color["other"]),
                    "des": get_str_by_dict(end_props),
                    "category": end_label,
                }
            )
            node_cache.add(end_key)

        if start_label not in legend_data:
            legend_data.append(start_label)
            categories.append({"name": start_label})
        if end_label not in legend_data:
            legend_data.append(end_label)
            categories.append({"name": end_label})

        cache_relation = str(start_key) + "-" + str(end_key) + "-" + str(relation_name)
        if cache_relation not in link_cache:
            links.append(
                {
                    "source": str(start_key),
                    "target": str(end_key),
                    "name": relation_name,
                }
            )
            link_cache.add(cache_relation)

    result = {
        "datas": datas,
        "links": links,
        "legend_data": legend_data,
        "categories": categories,
    }

    if default_graph:
        _set_cached_graph_result(start, relation, end, result)

    return result
