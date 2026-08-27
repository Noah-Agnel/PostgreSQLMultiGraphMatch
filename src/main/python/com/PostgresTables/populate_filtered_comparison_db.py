"""
populate_filtered_comparison_db.py

Populates only what compute_compatibility()/find_solutions() actually
touch: metadata_node_labels, metadata_edge_types, node_labels,
node_label_pair, node_pair_matches, edges_matches. Deliberately skips
node_static_props/node_dynamic_props/edge_static_props/edge_dynamic_props
-- nothing in that code path reads them (only WHERE-clause property
evaluation would, which isn't part of what's being compared here), so
populating millions of raw property rows just to get a handful of metadata
rows as a side effect would be pure waste. Node labels ARE loaded
unfiltered (all nodes, not just ones touching the allowed edge types), to
match a Neo4j import that included every node type.

Usage:
    python3 populate_filtered_comparison_db.py <output_path> <db_name> <edge_type> [edge_type ...]

Example (matching the 3 edge types imported into the Neo4j sandbox):
    python3 populate_filtered_comparison_db.py \\
        ../../../networks/panama/temporal_mri_import panama_db_3types \\
        "director of" "intermediary of" "registered address"
"""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from com.PostgresTables.create_postgres_tables import create_database_if_not_exists, get_db_connection
from com.PostgresTables import create_postgres_tables as schema
from com.PostgresTables.populate_postgres_tables import discover_files
from com.PostgresTables.populate_matching_tables import populate_matching_tables, load_node_labels
from com.PostgresTables.postgres_writer import PostgresGraphWriter


def create_schema(db_name: str) -> None:
    create_database_if_not_exists(db_name)
    conn = get_db_connection(db_name)
    try:
        with conn.cursor() as cur:
            schema.create_node_label_pair_table(cur)
            schema.create_node_labels_table(cur)
            schema.create_node_pair_matches_table(cur)
            schema.create_match_edges_table(cur)
            schema.create_node_static_props_table(cur)
            schema.create_node_dynamic_props_table(cur)
            schema.create_edge_static_props_table(cur)
            schema.create_edge_dynamic_props_table(cur)
            schema.create_metadata_node_labels_table(cur)
            schema.create_metadata_edge_types_table(cur)
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    output_path = sys.argv[1]
    db_name = sys.argv[2]
    allowed_edge_types = set(sys.argv[3:])

    print(f"Creating schema in database: {db_name}")
    create_schema(db_name)

    print(f"Discovering JSON files in: {output_path}")
    node_files, edge_files = discover_files(output_path)
    print(f"Found {len(node_files)} node file(s), {len(edge_files)} edge file(s)")

    writer = PostgresGraphWriter(db_name)
    try:
        # Node labels: register every label found in the staged JSON, unfiltered
        # (all node types stay present, matching an unfiltered Neo4j node import).
        node_labels = load_node_labels(node_files)
        all_labels = {label for labels in node_labels.values() for label in labels}
        writer.register_labels(all_labels)
        for edge_type in allowed_edge_types:
            writer.register_edge_type(edge_type)

        print(f"\n=== Populating matching tables (edge types: {sorted(allowed_edge_types)}) ===")
        populate_matching_tables(writer, output_path, node_files, edge_files,
                                  allowed_edge_types=allowed_edge_types)

        print("\nWriting metadata (node labels / edge types)...")
        writer.flush_metadata()
        writer.commit()

        print("\nDone!")
    finally:
        writer.close()


if __name__ == "__main__":
    main()
