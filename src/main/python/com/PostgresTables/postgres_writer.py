"""
postgres_writer.py

Replaces the JSON-file staging step from the original Spark/Iceberg pipeline.
Takes the record dicts produced by panama_json.py (static/dynamic node and
edge records, each carrying a flat "props" dict) and writes them directly
into PostgreSQL, exploding each props dict into one EAV row per property to
match the node_static_props / node_dynamic_props / edge_static_props /
edge_dynamic_props schema created by create_postgres_tables.py.

Tables populated here:
    node_static_props, node_dynamic_props,
    edge_static_props, edge_dynamic_props,
    metadata_node_labels, metadata_edge_types

Tables NOT populated here (they belong to the downstream graph-matching
stage, not raw import):
    node_label_pair, node_pair_matches, edges_matches
"""

import os
from datetime import datetime, timezone
from itertools import count

import psycopg2
from psycopg2.extras import execute_values, Json


# ============================================================
# CONNECTION
# ============================================================

def get_connection_params():
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": os.environ.get("PGPORT", "5432"),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
    }


def get_db_connection(db_name: str):
    conn = psycopg2.connect(dbname=db_name, **get_connection_params())
    conn.autocommit = False
    return conn


# ============================================================
# PROPERTY EXPLOSION
# ============================================================
#
# Each props dict (e.g. Entity.__dict__ minus excluded fields, or
# {"source_dataset": "Panama Papers"}) becomes one row per key, routed
# into whichever value column matches its Python type. Empty/None
# values are skipped entirely rather than written as empty rows.

def _explode_props(props: dict):
    rows = []
    for name, value in (props or {}).items():
        if value is None:
            continue

        string_value = None
        numeric_value = None
        datetime_value = None
        string_values = None
        numeric_values = None
        datetime_values = None

        if isinstance(value, bool):
            string_value = "true" if value else "false"
        elif isinstance(value, str):
            if value == "":
                continue
            string_value = value
        elif isinstance(value, (int, float)):
            numeric_value = value
        elif isinstance(value, datetime):
            datetime_value = value
        elif isinstance(value, list):
            if not value:
                continue
            if all(isinstance(v, bool) for v in value):
                string_values = ["true" if v else "false" for v in value]
            elif all(isinstance(v, str) for v in value):
                string_values = value
            elif all(isinstance(v, (int, float)) for v in value):
                numeric_values = value
            elif all(isinstance(v, datetime) for v in value):
                datetime_values = value
            else:
                # Mixed-type list: fall back to stringifying elements
                # rather than dropping the property.
                string_values = [str(v) for v in value]
        else:
            # Fallback for any other type: stringify rather than drop.
            string_value = str(value)

        rows.append((
            name, string_value, numeric_value, datetime_value,
            string_values, numeric_values, datetime_values,
        ))
    return rows


def _utc_now():
    return datetime.now(timezone.utc)


# ============================================================
# WRITER
# ============================================================

class PostgresGraphWriter:
    """
    Holds one long-lived connection/cursor for the whole ingestion run.
    Id counters for the four EAV tables are seeded once from the current
    MAX(id) in each table (0 if empty), then incremented in-process —
    this assumes a single writer process per run, which matches how
    panama_reader.py drives ingestion.
    """

    def __init__(self, db_name: str):
        self.conn = get_db_connection(db_name)
        self.cur = self.conn.cursor()
        self._id_seqs = {}
        self._known_labels = None
        self._known_edge_types = None

    def close(self):
        self.cur.close()
        self.conn.close()

    def commit(self):
        self.conn.commit()

    # ---------- id sequencing ----------

    def _next_id_seq(self, table: str, id_col: str):
        if table not in self._id_seqs:
            self.cur.execute(f"SELECT COALESCE(MAX({id_col}), 0) FROM {table}")
            (max_id,) = self.cur.fetchone()
            self._id_seqs[table] = count(start=max_id + 1)
        return self._id_seqs[table]

    # ---------- node props ----------

    def write_node_static_props(self, node_type: str, records: list):
        """records: output of static_nodes_json_creation()[node_type]"""
        if not records:
            return
        id_seq = self._next_id_seq("node_static_props", "snproperty_id")
        created_at = _utc_now()
        rows = []
        for record in records:
            node_id = str(record["node_id"])
            for (name, sval, nval, dval, svals, nvals, dvals) in _explode_props(record["static_props"]):
                rows.append((
                    next(id_seq), node_id, name, sval, nval, dval,
                    svals, nvals, dvals, created_at, record["is_active"],
                ))
        if not rows:
            return
        execute_values(
            self.cur,
            """
            INSERT INTO node_static_props
                (snproperty_id, node_id, property_name, string_value,
                 numeric_value, datetime_value, string_values,
                 numeric_values, datetime_values, created_at, is_active)
            VALUES %s
            """,
            rows,
            page_size=1000,
        )

    def write_node_dynamic_props(self, node_type: str, records: list):
        """records: output of dynamic_nodes_json_creation()[node_type]"""
        if not records:
            return
        id_seq = self._next_id_seq("node_dynamic_props", "dnproperty_id")
        created_at = _utc_now()
        rows = []
        for record in records:
            node_id = str(record["node_id"])
            for (name, sval, nval, dval, svals, nvals, dvals) in _explode_props(record["dynamic_props"]):
                rows.append((
                    next(id_seq), node_id, name, sval, nval, dval,
                    svals, nvals, dvals, record["from"], record["to"], created_at,
                ))
        if not rows:
            return
        execute_values(
            self.cur,
            """
            INSERT INTO node_dynamic_props
                (dnproperty_id, node_id, property_name, string_value,
                 numeric_value, datetime_value, string_values,
                 numeric_values, datetime_values, "from", "to", created_at)
            VALUES %s
            """,
            rows,
            page_size=1000,
        )

    # ---------- edge props ----------

    def write_edge_static_props(self, records: list):
        """records: output of static_edges_json_creation()"""
        if not records:
            return
        id_seq = self._next_id_seq("edge_static_props", "seproperty_id")
        created_at = _utc_now()
        rows = []
        for record in records:
            for (name, sval, nval, dval, svals, nvals, dvals) in _explode_props(record["static_props"]):
                rows.append((
                    next(id_seq), record["edge_id"], name, sval, nval, dval,
                    svals, nvals, dvals, created_at,
                ))
        if not rows:
            return
        execute_values(
            self.cur,
            """
            INSERT INTO edge_static_props
                (seproperty_id, edge_id, property_name, string_value,
                 numeric_value, datetime_value, string_values,
                 numeric_values, datetime_values, created_at)
            VALUES %s
            """,
            rows,
            page_size=1000,
        )

    def write_edge_dynamic_props(self, records: list):
        """records: output of dynamic_edges_json_creation()"""
        if not records:
            return
        id_seq = self._next_id_seq("edge_dynamic_props", "deproperty_id")
        created_at = _utc_now()
        rows = []
        for record in records:
            for (name, sval, nval, dval, svals, nvals, dvals) in _explode_props(record["dynamic_props"]):
                rows.append((
                    next(id_seq), record["edge_id"], name, sval, nval, dval,
                    svals, nvals, dvals, record["from"], record["to"], created_at,
                ))
        if not rows:
            return
        execute_values(
            self.cur,
            """
            INSERT INTO edge_dynamic_props
                (deproperty_id, edge_id, property_name, string_value,
                 numeric_value, datetime_value, string_values,
                 numeric_values, datetime_values, "from", "to", created_at)
            VALUES %s
            """,
            rows,
            page_size=1000,
        )

    # ---------- matching tables ----------

    def write_node_label_pair(self, rows: list):
        """
        rows: list of tuples
            (pair_id, src_labels, dst_labels, edge_1_2_types, edge_2_1_types,
             edge_bi_types, created_at)
        edge_1_2_types/edge_2_1_types/edge_bi_types are plain dicts or None;
        wrapped with psycopg2.extras.Json for JSONB adaptation.
        """
        if not rows:
            return
        wrapped = [
            (pair_id, src_labels, dst_labels,
             Json(e12t) if e12t is not None else None,
             Json(e21t) if e21t is not None else None,
             Json(ebit) if ebit is not None else None,
             created_at)
            for (pair_id, src_labels, dst_labels, e12t, e21t, ebit, created_at) in rows
        ]
        execute_values(
            self.cur,
            """
            INSERT INTO node_label_pair
                (pair_id, src_labels, dst_labels, edge_1_2_types,
                 edge_2_1_types, edge_bi_types, created_at)
            VALUES %s
            """,
            wrapped,
            page_size=1000,
        )

    def write_node_pair_matches(self, rows: list):
        """rows: list of (nodes_match_id, pair_id, source_node_id, target_node_id, created_at)"""
        if not rows:
            return
        execute_values(
            self.cur,
            """
            INSERT INTO node_pair_matches
                (nodes_match_id, pair_id, source_node_id, target_node_id, created_at)
            VALUES %s
            """,
            rows,
            page_size=1000,
        )

    def write_edges_matches(self, rows: list):
        """rows: list of (edge_id, pair_id, nodes_match_id, edge_type, edge_direction, created_at)"""
        if not rows:
            return
        execute_values(
            self.cur,
            """
            INSERT INTO edges_matches
                (edge_id, pair_id, nodes_match_id, edge_type, edge_direction, created_at)
            VALUES %s
            """,
            rows,
            page_size=1000,
        )

    def write_node_labels(self, rows: list):
        """rows: list of (node_id, labels)"""
        if not rows:
            return
        execute_values(
            self.cur,
            """
            INSERT INTO node_labels (node_id, labels)
            VALUES %s
            ON CONFLICT (node_id) DO NOTHING
            """,
            rows,
            page_size=1000,
        )

    # ---------- metadata ----------

    def register_labels(self, labels):
        """Accumulates node labels seen during ingestion for later flush."""
        if self._known_labels is None:
            self._known_labels = set()
        self._known_labels.update(labels)

    def register_edge_type(self, edge_type: str):
        """Accumulates edge types seen during ingestion for later flush."""
        if self._known_edge_types is None:
            self._known_edge_types = set()
        if edge_type:
            self._known_edge_types.add(edge_type)

    def flush_metadata(self):
        """
        Writes any newly-seen labels/edge types to metadata_node_labels /
        metadata_edge_types, skipping ones already present. Call once at
        the end of ingestion.
        """
        if self._known_labels:
            self.cur.execute("SELECT label FROM metadata_node_labels")
            existing = {row[0] for row in self.cur.fetchall()}
            new_labels = sorted(self._known_labels - existing)
            if new_labels:
                self.cur.execute("SELECT COALESCE(MAX(label_id), 0) FROM metadata_node_labels")
                (next_id,) = self.cur.fetchone()
                rows = [(next_id + i + 1, label) for i, label in enumerate(new_labels)]
                execute_values(
                    self.cur,
                    "INSERT INTO metadata_node_labels (label_id, label) VALUES %s",
                    rows,
                )

        if self._known_edge_types:
            self.cur.execute("SELECT edge_type FROM metadata_edge_types")
            existing = {row[0] for row in self.cur.fetchall()}
            new_types = sorted(self._known_edge_types - existing)
            if new_types:
                self.cur.execute("SELECT COALESCE(MAX(type_id), 0) FROM metadata_edge_types")
                (next_id,) = self.cur.fetchone()
                rows = [(next_id + i + 1, edge_type) for i, edge_type in enumerate(new_types)]
                execute_values(
                    self.cur,
                    "INSERT INTO metadata_edge_types (type_id, edge_type) VALUES %s",
                    rows,
                )