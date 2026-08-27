"""
Single entrypoint that populates every table for a dataset in one run:
    1. populate_postgres_tables.populate_raw_tables()
       -> node_static_props, node_dynamic_props, edge_static_props,
          edge_dynamic_props, metadata_node_labels, metadata_edge_types
    2. populate_matching_tables.populate_matching_tables()
       -> node_label_pair, node_pair_matches, edges_matches
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # so `com.X.Y` resolves regardless of invocation style

from com.PostgresTables.populate_postgres_tables import discover_files, populate_raw_tables
from com.PostgresTables.populate_matching_tables import populate_matching_tables
from com.PostgresTables.postgres_writer import PostgresGraphWriter


def parse_args():
    parser = argparse.ArgumentParser(
        description="Populate raw + matching tables from staged JSON node/edge files."
    )
    parser.add_argument(
        "output_path", nargs="?", default=None,
        help="Directory containing the staged JSON files "
             "(falls back to $GRAPH_OUTPUT_PATH if omitted)",
    )
    parser.add_argument(
        "db_name", nargs="?", default=None,
        help="Target Postgres database name "
             "(falls back to $GRAPH_DB_NAME if omitted)",
    )
    args = parser.parse_args()

    output_path = args.output_path or os.environ.get("GRAPH_OUTPUT_PATH")
    db_name = args.db_name or os.environ.get("GRAPH_DB_NAME")

    if not output_path or not db_name:
        parser.error(
            "output_path and db_name are required, either as arguments "
            "or via $GRAPH_OUTPUT_PATH / $GRAPH_DB_NAME"
        )

    return output_path, db_name


if __name__ == "__main__":
    output_path, db_name = parse_args()

    print(f"Discovering JSON files in: {output_path}")
    node_files, edge_files = discover_files(output_path)
    print(f"Found {len(node_files)} node file(s), {len(edge_files)} edge file(s)")

    writer = PostgresGraphWriter(db_name)
    try:
        print("\n=== Step 1/2: raw node/edge/metadata tables ===")
        populate_raw_tables(writer, output_path, node_files, edge_files)

        print("\n=== Step 2/2: matching tables ===")
        populate_matching_tables(writer, output_path, node_files, edge_files)

        print("\nDone!")
    finally:
        writer.close()
