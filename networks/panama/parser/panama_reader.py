import csv
import json
from pathlib      import Path
from tqdm         import tqdm
from panama_models import (
    NodesManaging, EdgesManaging,
    entity_from_row, officer_from_row, intermediary_from_row, address_from_row,
    edge_from_row,
)
from panama_json  import (
    static_nodes_json_creation, dynamic_nodes_json_creation,
    static_edges_json_creation, dynamic_edges_json_creation,
    node_filename, edge_filename,
)

# ============================================================
# CONFIGURATION
# ============================================================

config      = json.load(open("../config/config.json"))
csv_dir     = config.get("csv_dir", "../data")
output_path = config.get("output_path", "../temporal_mri_import")
batch_size  = config.get("batch_size", 50000)

ENTITIES_CSV       = f"{csv_dir}/Entities.csv"
OFFICERS_CSV       = f"{csv_dir}/Officers.csv"
INTERMEDIARIES_CSV = f"{csv_dir}/Intermediaries.csv"
ADDRESSES_CSV      = f"{csv_dir}/Addresses.csv"
EDGES_CSV          = f"{csv_dir}/all_edges.csv"


# ============================================================
# CSV ROW COUNTING
# ============================================================

def _count_rows(path: str) -> int:
    with open(path, encoding="utf-8", errors="ignore") as f:
        return sum(1 for _ in f) - 1  # minus header


# ============================================================
# BATCH SAVING
# ============================================================

def save_node_batch(node_manager: NodesManaging, output_path: str, batch_num: int):
    """
    Serialises the current batch of node objects to static + dynamic JSON files.
    """
    static_json  = static_nodes_json_creation(node_manager.nodes)
    dynamic_json = dynamic_nodes_json_creation(node_manager.nodes)

    for node_type, records in static_json.items():
        if not records:
            continue
        path = node_filename(node_type, "static", output_path, batch_num)
        with open(path, "w") as f:
            json.dump(records, f, indent=4)
        print(f"  Wrote {len(records):>6} {node_type} static nodes  -> {path}")

    for node_type, records in dynamic_json.items():
        if not records:
            continue
        path = node_filename(node_type, "dynamic", output_path, batch_num)
        with open(path, "w") as f:
            json.dump(records, f, indent=4)
        print(f"  Wrote {len(records):>6} {node_type} dynamic nodes -> {path}")


def save_edge_batch(edge_manager: EdgesManaging, output_path: str, batch_num: int):
    """
    Serialises the current batch of edges.
    Saves static edges, and saves dynamic edges ONLY if dynamic_records is non-empty.
    """
    static_records  = static_edges_json_creation(edge_manager.edges)
    dynamic_records = dynamic_edges_json_creation(edge_manager.edges)

    # 1. Always write static edges
    static_path = edge_filename("static", output_path, batch_num)
    with open(static_path, "w") as f:
        json.dump(static_records, f, indent=4)
    print(f"  Wrote {len(static_records):>6} static edges  -> {static_path}")

    # 2. Write dynamic edges ONLY if there are records (avoiding empty [] files which cause 0-column downstream loads)
    if dynamic_records:
        dynamic_path = edge_filename("dynamic", output_path, batch_num)
        with open(dynamic_path, "w") as f:
            json.dump(dynamic_records, f, indent=4)
        print(f"  Wrote {len(dynamic_records):>6} dynamic edges -> {dynamic_path}")


# ============================================================
# GENERIC BATCHED CSV -> NODE INGESTION
# ============================================================

def ingest_node_csv(path: str, row_to_node, node_manager: NodesManaging,
                     output_path: str, batch_num_start: int) -> int:
    batch_num     = batch_num_start
    rows_in_batch = 0
    total_rows    = _count_rows(path)

    with open(path, encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in tqdm(reader, total=total_rows, desc=Path(path).name):
            row_to_node(row, node_manager)
            rows_in_batch += 1

            if rows_in_batch >= batch_size:
                save_node_batch(node_manager, output_path, batch_num)
                node_manager.reset_nodes()
                rows_in_batch = 0
                batch_num += 1

    if rows_in_batch > 0:
        save_node_batch(node_manager, output_path, batch_num)
        node_manager.reset_nodes()
        batch_num += 1

    return batch_num


def ingest_edges_csv(path: str, edge_manager: EdgesManaging,
                      output_path: str, batch_num_start: int) -> int:
    batch_num     = batch_num_start
    rows_in_batch = 0
    total_rows    = _count_rows(path)

    with open(path, encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in tqdm(reader, total=total_rows, desc=Path(path).name):
            edge_from_row(row, edge_manager)
            rows_in_batch += 1

            if rows_in_batch >= batch_size:
                save_edge_batch(edge_manager, output_path, batch_num)
                edge_manager.reset_edges()
                rows_in_batch = 0
                batch_num += 1

    if rows_in_batch > 0:
        save_edge_batch(edge_manager, output_path, batch_num)
        edge_manager.reset_edges()
        batch_num += 1

    return batch_num


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    Path(output_path).mkdir(parents=True, exist_ok=True)

    node_manager = NodesManaging()
    edge_manager = EdgesManaging()
    batch_num    = 0

    print("Ingesting Entities.csv...")
    batch_num = ingest_node_csv(ENTITIES_CSV, entity_from_row, node_manager, output_path, batch_num)

    print("Ingesting Officers.csv...")
    batch_num = ingest_node_csv(OFFICERS_CSV, officer_from_row, node_manager, output_path, batch_num)

    print("Ingesting Intermediaries.csv...")
    batch_num = ingest_node_csv(INTERMEDIARIES_CSV, intermediary_from_row, node_manager, output_path, batch_num)

    print("Ingesting Addresses.csv...")
    batch_num = ingest_node_csv(ADDRESSES_CSV, address_from_row, node_manager, output_path, batch_num)

    print("Ingesting all_edges.csv...")
    batch_num = ingest_edges_csv(EDGES_CSV, edge_manager, output_path, batch_num)

    print("\nDone!")
