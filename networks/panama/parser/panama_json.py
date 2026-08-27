import os

# ============================================================
# STATIC NODES JSON CREATION
# ============================================================
#
# Node record shape (static)
# --------------------------
# {
#     "node_id"     : int,
#     "labels"      : [str, ...],
#     "static_props": { ... },
#     "is_active"   : bool
# }
#
# Each node type excludes a different set of internal/derived fields
# from static_props: "id"/"labels" always (consumed separately), plus
# for Entity, the raw date strings and "status" — those feed the
# dynamic record instead and would otherwise duplicate/conflict with it.

_STATIC_EXCLUDE = {
    "entity": {
        "id", "labels", "status",
        "_incorporation_date_raw", "_inactivation_date_raw",
        "_struck_off_date_raw", "_dorm_date_raw",
    },
    "officer"     : {"id", "labels"},
    "intermediary": {"id", "labels"},
    "address"     : {"id", "labels"},
}


def _static_node_to_dict(node, node_type: str) -> dict:
    node_dict = node.__dict__.copy()
    exclude   = _STATIC_EXCLUDE[node_type]
    node_id   = node_dict["id"]
    labels    = node_dict["labels"]
    static_props = {k: v for k, v in node_dict.items() if k not in exclude}
    return {
        "node_id"     : node_id,
        "labels"      : labels,
        "static_props": static_props,
        "is_active"   : True,
    }


def static_nodes_json_creation(nodes: dict) -> dict:
    """
    Converts node objects into static-props JSON records.

    Args:
        nodes (dict): {"entity": [...], "officer": [...], "intermediary": [...], "address": [...]}

    Returns:
        dict: {node_type: [record, ...]}
    """
    return {
        node_type: [_static_node_to_dict(node, node_type) for node in node_list]
        for node_type, node_list in nodes.items()
    }


# ============================================================
# DYNAMIC NODES JSON CREATION
# ============================================================
#
# Node record shape (dynamic)
# ----------------------------
# {
#     "node_id"     : int,
#     "labels"      : [str, ...],
#     "is_active"   : bool,
#     "from"        : str | null,   # ISO-8601, or null if unknown
#     "to"          : str | null,
#     "dynamic_props": { ... }      # one validity window applies to ALL
#                                   # fields in this record
# }
#
# Only Entity produces dynamic records currently. A record is only
# emitted if status is non-empty AND at least one of from/to parses —
# a record with no window and no value would be pure noise in the
# dynamic table.

def _entity_dynamic_dict(entity) -> dict | None:
    frm, to = entity.dynamic_status_period()
    if not entity.status or (frm is None and to is None):
        return None
    return {
        "node_id"      : entity.id,
        "labels"       : entity.labels,
        "is_active"    : True,
        "from"         : frm,
        "to"           : to,
        "dynamic_props": {"status": entity.status},
    }


def dynamic_nodes_json_creation(nodes: dict) -> dict:
    """
    Converts node objects into dynamic-props JSON records.

    Returns:
        dict: {node_type: [record, ...]}. Node types with no dynamic
        props (officer/intermediary/address) always map to an empty list.
    """
    result: dict = {node_type: [] for node_type in nodes.keys()}

    for entity in nodes.get("entity", []):
        record = _entity_dynamic_dict(entity)
        if record is not None:
            result["entity"].append(record)

    return result


# ============================================================
# STATIC EDGES JSON CREATION
# ============================================================
#
# Edge record shape (static)
# ---------------------------
# {
#     "edge_id"     : str,
#     "source_id"   : int,
#     "target_id"   : int,
#     "edge_type"   : str,
#     "static_props": { ... }
# }
#
# Every edge gets a static record regardless of whether it also has a
# dynamic one — edge_type/provenance is known even when the validity
# window isn't. "source_dataset" guarantees static_props is never
# empty.

def _static_edge_to_dict(edge: dict) -> dict:
    return {
        "edge_id"     : edge["edge_id"],
        "source_id"   : edge["src"],
        "target_id"   : edge["dst"],
        "edge_type"   : edge["type"],
        "static_props": {"source_dataset": "Panama Papers"},
    }


def static_edges_json_creation(edges: list) -> list:
    return [_static_edge_to_dict(edge) for edge in edges]


# ============================================================
# DYNAMIC EDGES JSON CREATION
# ============================================================
#
# Edge record shape (dynamic)
# -----------------------------
# {
#     "edge_id"     : str,
#     "source_id"   : int,
#     "target_id"   : int,
#     "edge_type"   : str,
#     "from"        : str | null,
#     "to"          : str | null,
#     "dynamic_props": {"active": true}   # placeholder value so the
#                                          # from/to window has a field
#                                          # to attach to
# }
#
# Only emitted for edges where at least one of start_date/end_date is
# actually populated — most all_edges.csv rows won't have either, so
# expect this to be much smaller than the static set.

def _dynamic_edge_to_dict(edge: dict) -> dict | None:
    frm = edge.get("start_date")
    to  = edge.get("end_date")
    if frm is None and to is None:
        return None
    return {
        "edge_id"     : edge["edge_id"],
        "source_id"   : edge["src"],
        "target_id"   : edge["dst"],
        "edge_type"   : edge["type"],
        "from"        : frm,
        "to"          : to,
        "dynamic_props": {"active": True},
    }


def dynamic_edges_json_creation(edges: list) -> list:
    records = [_dynamic_edge_to_dict(edge) for edge in edges]
    return [r for r in records if r is not None]


# ============================================================
# FILENAME HELPERS
# ============================================================

def node_filename(node_type: str, kind: str, output_path: str, batch_num: int) -> str:
    """
    Returns the output path for a node JSON file.
    kind is "static" or "dynamic".
    e.g. path_1_entity_nodes_static_props_0.json / path_1_entity_nodes_dynamic_props_0.json

    NOTE: the "nodes" segment is required, not cosmetic — the data
    insertion step (populate_postgres_tables.py) routes files into
    node vs edge handling via this exact naming convention.
    """
    return os.path.join(output_path, f"path_1_{node_type}_nodes_{kind}_props_{batch_num}.json")


def edge_filename(kind: str, output_path: str, batch_num: int) -> str:
    """
    Returns the output path for an edge JSON file.
    kind is "static" or "dynamic".
    e.g. path_1_edges_static_props_0.json / path_1_edges_dynamic_props_0.json
    """
    return os.path.join(output_path, f"path_1_edges_{kind}_props_{batch_num}.json")
