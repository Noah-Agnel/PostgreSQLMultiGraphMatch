"""
populate_matching_tables.py

Python/pandas-free port of the graph-matching portion of
TablesPopulationHandler.scala + DataInsertionInTable.scala. Builds
node_label_pair, node_pair_matches, and edges_matches by analysing every
node-pair connected by an edge in the dataset.
"""

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `com.X.Y` resolves regardless of invocation style

from com.PostgresTables.populate_postgres_tables import discover_files, load_json
from com.PostgresTables.postgres_writer import PostgresGraphWriter


# ============================================================
# RAW DATA LOADING
# ============================================================

def load_node_labels(node_files: list) -> dict:
    node_labels = {}
    for path, node_type, kind, batch_num in node_files:
        for record in load_json(path):
            node_id = int(record["node_id"])
            if node_id not in node_labels:
                node_labels[node_id] = tuple(record["labels"])
    return node_labels


def load_edges(edge_files: list) -> list:
    edges_by_id = {}
    for path, kind, batch_num in edge_files:
        for record in load_json(path):
            edge_id = record["edge_id"]
            if edge_id in edges_by_id:
                continue
            source_id = int(record["source_id"])
            target_id = int(record["target_id"])
            if source_id == target_id:
                continue
            edges_by_id[edge_id] = {
                "edge_id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "edge_type": record["edge_type"],
            }
    return list(edges_by_id.values())


# ============================================================
# NODES/EDGES MATRIX CONFIGURATION
# (port of nodesAndEdgesLabelsAndIdsConfiguration)
# ============================================================

def build_node_pair_groups(edges: list, node_labels: dict) -> dict:
    """
    Groups edges by canonicalised (min_node, max_node) pair.

    Returns {(min_node, max_node): {
        "min_labels": tuple, "max_labels": tuple,
        "edge_in_list": [edge_type, ...], "edge_in_id_list": [edge_id, ...],
        "edge_out_list": [...], "edge_out_id_list": [...],
    }}
    """
    groups = {}
    skipped_missing_labels = 0

    for edge in edges:
        sid, tid = edge["source_id"], edge["target_id"]
        if sid == tid:
            continue
        if sid not in node_labels or tid not in node_labels:
            skipped_missing_labels += 1
            continue

        is_source_min = sid < tid
        if is_source_min:
            min_node, max_node = sid, tid
            min_labels, max_labels = node_labels[sid], node_labels[tid]
            edge_in, edge_in_id = edge["edge_type"], edge["edge_id"]
            edge_out, edge_out_id = None, None
        else:
            min_node, max_node = tid, sid
            min_labels, max_labels = node_labels[tid], node_labels[sid]
            edge_in, edge_in_id = None, None
            edge_out, edge_out_id = edge["edge_type"], edge["edge_id"]

        key = (min_node, max_node)
        group = groups.get(key)
        if group is None:
            group = {
                "min_labels": min_labels, "max_labels": max_labels,
                "edge_in_list": [], "edge_in_id_list": [],
                "edge_out_list": [], "edge_out_id_list": [],
            }
            groups[key] = group

        if edge_in is not None:
            group["edge_in_list"].append(edge_in)
            group["edge_in_id_list"].append(edge_in_id)
        if edge_out is not None:
            group["edge_out_list"].append(edge_out)
            group["edge_out_id_list"].append(edge_out_id)

    if skipped_missing_labels:
        print(f"  Warning: skipped {skipped_missing_labels} edge(s) referencing "
              f"a node_id with no known labels")

    return groups


def assign_pair_ids(groups: dict) -> dict:
    """
    Dense-ranks each node pair's (edge_in_types, edge_out_types) signature
    within its (min_labels, max_labels) partition. Returns
    {(min_node, max_node): pair_id}.
    """
    partitions = defaultdict(list)
    for key, group in groups.items():
        partitions[(group["min_labels"], group["max_labels"])].append(key)

    pair_id_map = {}
    for partition_key, keys in partitions.items():
        sig_to_keys = defaultdict(list)
        for key in keys:
            group = groups[key]
            sig = (tuple(group["edge_in_list"]), tuple(group["edge_out_list"]))
            sig_to_keys[sig].append(key)

        for rank, sig in enumerate(sorted(sig_to_keys.keys()), start=1):
            for key in sig_to_keys[sig]:
                pair_id_map[key] = rank

    return pair_id_map


# ============================================================
# TABLE ROW BUILDING
# (ports of nodeLabelPairPopulation / nodePairMatchesPopulation /
#  matchEdgesPopulation)
# ============================================================

def frequency_map(items: list) -> dict:
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def build_node_label_pair_rows(groups: dict, pair_id_map: dict, created_at) -> list:
    partitions = defaultdict(dict)  # (min_labels,max_labels) -> {sig: pair_id}
    for key, group in groups.items():
        sig = (tuple(group["edge_in_list"]), tuple(group["edge_out_list"]))
        partitions[(group["min_labels"], group["max_labels"])][sig] = pair_id_map[key]

    rows = []
    for (min_labels, max_labels), sig_to_pair_id in partitions.items():
        for (edge_in_types, edge_out_types), pair_id in sig_to_pair_id.items():
            rows.append((
                pair_id,
                list(min_labels),
                list(max_labels),
                frequency_map(edge_in_types),
                frequency_map(edge_out_types),
                None,  # edge_bi_types: undirected case not handled (matches Scala TODO)
                created_at,
            ))
    return rows


def build_node_pair_matches_rows(groups: dict, pair_id_map: dict, created_at) -> list:
    rows = []
    for (min_node, max_node), group in groups.items():
        pair_id = pair_id_map[(min_node, max_node)]
        nodes_match_id = f"{min_node}_{max_node}"
        rows.append((nodes_match_id, pair_id, str(min_node), str(max_node), created_at))
    return rows


def build_edges_matches_rows(groups: dict, pair_id_map: dict, created_at) -> list:
    rows = []
    for (min_node, max_node), group in groups.items():
        pair_id = pair_id_map[(min_node, max_node)]
        nodes_match_id = f"{min_node}_{max_node}"
        for edge_type, edge_id in zip(group["edge_in_list"], group["edge_in_id_list"]):
            rows.append((edge_id, pair_id, nodes_match_id, edge_type, "min_to_max", created_at))
        for edge_type, edge_id in zip(group["edge_out_list"], group["edge_out_id_list"]):
            rows.append((edge_id, pair_id, nodes_match_id, edge_type, "max_to_min", created_at))
    return rows


def build_node_labels_rows(node_labels: dict) -> list:
    return [(str(node_id), list(labels)) for node_id, labels in node_labels.items()]


def populate_matching_tables(writer: PostgresGraphWriter, output_path: str,
                              node_files: list = None, edge_files: list = None,
                              allowed_edge_types: set = None):
    if node_files is None or edge_files is None:
        print(f"Discovering JSON files in: {output_path}")
        node_files, edge_files = discover_files(output_path)
        print(f"Found {len(node_files)} node file(s), {len(edge_files)} edge file(s)")

    print("Loading node labels...")
    node_labels = load_node_labels(node_files)
    print(f"  {len(node_labels)} distinct nodes")

    print("Loading edges...")
    edges = load_edges(edge_files)
    print(f"  {len(edges)} distinct edges (self-loops excluded)")

    if allowed_edge_types is not None:
        before = len(edges)
        edges = [e for e in edges if e["edge_type"] in allowed_edge_types]
        print(f"  Filtered to {len(edges)} edges of type {sorted(allowed_edge_types)} (dropped {before - len(edges)})")

    print("Grouping edges by node pair...")
    groups = build_node_pair_groups(edges, node_labels)
    print(f"  {len(groups)} distinct node pairs")

    print("Assigning pair ids...")
    pair_id_map = assign_pair_ids(groups)

    created_at = datetime.now(timezone.utc)

    node_label_pair_rows = build_node_label_pair_rows(groups, pair_id_map, created_at)
    node_pair_matches_rows = build_node_pair_matches_rows(groups, pair_id_map, created_at)
    edges_matches_rows = build_edges_matches_rows(groups, pair_id_map, created_at)

    print(f"  {len(node_label_pair_rows)} node_label_pair row(s)")
    print(f"  {len(node_pair_matches_rows)} node_pair_matches row(s)")
    print(f"  {len(edges_matches_rows)} edges_matches row(s)")

    print("Writing node_labels...")
    writer.write_node_labels(build_node_labels_rows(node_labels))
    writer.commit()

    print("Writing node_label_pair...")
    writer.write_node_label_pair(node_label_pair_rows)
    writer.commit()

    print("Writing node_pair_matches...")
    writer.write_node_pair_matches(node_pair_matches_rows)
    writer.commit()

    print("Writing edges_matches...")
    writer.write_edges_matches(edges_matches_rows)
    writer.commit()
