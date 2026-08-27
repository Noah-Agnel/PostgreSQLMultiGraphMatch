"""
Reads the intermediate JSON files produced by a reader script (e.g.
panama_reader.py) and loads them into PostgreSQL.

File-naming convention it expects (see node_filename/edge_filename):
    Node static : path_<n>_<node_type>_nodes_static_props_<batch>.json
    Node dynamic: path_<n>_<node_type>_nodes_dynamic_props_<batch>.json
    Edge static : path_<n>_edges_static_props_<batch>.json
    Edge dynamic: path_<n>_edges_dynamic_props_<batch>.json

Record shapes it expects (see panama_json.py / any equivalent reader):
    Node static : {"node_id", "labels", "static_props", "is_active"}
    Node dynamic: {"node_id", "labels", "is_active", "from", "to", "dynamic_props"}
    Edge static : {"edge_id", "source_id", "target_id", "edge_type", "static_props"}
    Edge dynamic: {"edge_id", "source_id", "target_id", "edge_type", "from", "to", "dynamic_props"}

Tables populated:
    node_static_props, node_dynamic_props,
    edge_static_props, edge_dynamic_props,
    metadata_node_labels, metadata_edge_types

Tables NOT populated here (they belong to the downstream graph-matching
stage, not raw import):
    node_label_pair, node_pair_matches, edges_matches
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `com.X.Y` resolves regardless of invocation style

from com.PostgresTables.postgres_writer import PostgresGraphWriter

# ============================================================
# CONFIGURATION
# ============================================================

# Edge pattern is checked first since it's more specific (literal "edges").
EDGE_FILE_PATTERN = re.compile(
    r"^path_\d+_edges_(?P<kind>static|dynamic)_props_(?P<batch>\d+)\.json$"
)
NODE_FILE_PATTERN = re.compile(
    r"^path_\d+_(?P<node_type>.+)_nodes_(?P<kind>static|dynamic)_props_(?P<batch>\d+)\.json$"
)


# ============================================================
# FILE DISCOVERY
# ============================================================

def _batch_key(filename: str, match: re.Match) -> int:
    return int(match.group("batch"))


def discover_files(output_path: str):
    node_files = []
    edge_files = []

    for path in Path(output_path).glob("*.json"):
        name = path.name

        edge_match = EDGE_FILE_PATTERN.match(name)
        if edge_match:
            edge_files.append((path, edge_match.group("kind"), int(edge_match.group("batch"))))
            continue

        node_match = NODE_FILE_PATTERN.match(name)
        if node_match:
            node_files.append((
                path, node_match.group("node_type"),
                node_match.group("kind"), int(node_match.group("batch")),
            ))
            continue

        print(f"  Skipping unrecognized file: {name}")

    node_files.sort(key=lambda t: t[3])
    edge_files.sort(key=lambda t: t[2])
    return node_files, edge_files

def load_json(path: Path) -> list:
    with open(path) as f:
        return json.load(f)


def load_node_files(writer: PostgresGraphWriter, node_files: list) -> None:
    for path, node_type, kind, batch_num in node_files:
        records = load_json(path)
        if not records:
            continue

        if kind == "static":
            writer.write_node_static_props(node_type, records)
            for record in records:
                writer.register_labels(record["labels"])
            print(f"  Loaded {len(records):>6} {node_type} static nodes  <- {path.name}")
        else:
            writer.write_node_dynamic_props(node_type, records)
            print(f"  Loaded {len(records):>6} {node_type} dynamic nodes <- {path.name}")

        writer.commit()


def load_edge_files(writer: PostgresGraphWriter, edge_files: list) -> None:
    for path, kind, batch_num in edge_files:
        records = load_json(path)
        if not records:
            continue

        if kind == "static":
            writer.write_edge_static_props(records)
            for record in records:
                writer.register_edge_type(record["edge_type"])
            print(f"  Loaded {len(records):>6} static edges  <- {path.name}")
        else:
            writer.write_edge_dynamic_props(records)
            print(f"  Loaded {len(records):>6} dynamic edges <- {path.name}")

        writer.commit()


def populate_raw_tables(writer: PostgresGraphWriter, output_path: str,
                         node_files: list = None, edge_files: list = None):
    """
    Loads staged JSON node/edge files into the raw EAV + metadata tables
    using an already-open writer. If node_files/edge_files aren't passed
    in (e.g. by a caller that already ran discover_files itself), this
    discovers them from output_path.

    Returns (node_files, edge_files) so a caller can reuse the same
    discovery results for a subsequent step (e.g. populate_matching_tables).
    """
    if node_files is None or edge_files is None:
        print(f"Discovering JSON files in: {output_path}")
        node_files, edge_files = discover_files(output_path)
        print(f"Found {len(node_files)} node file(s), {len(edge_files)} edge file(s)")

    print("\nLoading node files...")
    load_node_files(writer, node_files)

    print("\nLoading edge files...")
    load_edge_files(writer, edge_files)

    print("\nWriting metadata (node labels / edge types)...")
    writer.flush_metadata()
    writer.commit()

    return node_files, edge_files