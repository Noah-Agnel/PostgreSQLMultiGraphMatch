import os
import sys

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def get_connection_params():
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": os.environ.get("PGPORT", "5432"),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
    }


def create_database_if_not_exists(db_name: str) -> None:
    """Connects to the admin database and creates db_name if missing."""
    admin_db = os.environ.get("PGADMINDB", "postgres")
    params = get_connection_params()

    conn = psycopg2.connect(dbname=admin_db, **params)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
                print(f"Created database: {db_name}")
            else:
                print(f"Database already exists: {db_name}")
    finally:
        conn.close()


def get_db_connection(db_name: str):
    params = get_connection_params()
    conn = psycopg2.connect(dbname=db_name, **params)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def create_node_label_pair_table(cur) -> None:
    print("Creating node_label_pair table...")
    # NOTE: pair_id is not globally unique. It's generated as
    # dense_rank() OVER (PARTITION BY src_labels, dst_labels ...), i.e. it
    # restarts at 1 for every distinct label-pair combination. The real
    # uniqueness is the composite (pair_id, src_labels, dst_labels).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS node_label_pair (
            pair_id           BIGINT NOT NULL,
            src_labels        TEXT[],
            dst_labels        TEXT[],
            edge_1_2_types    JSONB,
            edge_2_1_types    JSONB,
            edge_bi_types     JSONB,
            created_at        TIMESTAMP NOT NULL,
            UNIQUE (pair_id, src_labels, dst_labels)
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_label_pair_pair_id "
        "ON node_label_pair (pair_id)"
    )


def create_node_labels_table(cur) -> None:
    print("Creating node_labels table...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS node_labels (
            node_id     TEXT PRIMARY KEY,
            labels      TEXT[] NOT NULL
        )
        """
    )


def create_node_pair_matches_table(cur) -> None:
    print("Creating node_pair_matches table...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS node_pair_matches (
            nodes_match_id    TEXT,
            pair_id           BIGINT NOT NULL,
            source_node_id    TEXT,
            target_node_id    TEXT,
            created_at        TIMESTAMP NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_pair_matches_pair_id "
        "ON node_pair_matches (pair_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_pair_matches_source_node_id "
        "ON node_pair_matches (source_node_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_pair_matches_target_node_id "
        "ON node_pair_matches (target_node_id)"
    )


def create_match_edges_table(cur) -> None:
    print("Creating edges_matches table...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS edges_matches (
            edge_id           TEXT NOT NULL,
            pair_id           BIGINT NOT NULL,
            nodes_match_id    TEXT NOT NULL,
            edge_type         TEXT NOT NULL,
            -- 'min_to_max': edge points source_node_id -> target_node_id
            -- (see node_pair_matches); 'max_to_min': the reverse. Needed to
            -- reconstruct actual edge direction, since nodes_match_id alone
            -- (an unordered pair key) doesn't carry it.
            edge_direction    TEXT NOT NULL CHECK (edge_direction IN ('min_to_max', 'max_to_min')),
            created_at        TIMESTAMP NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_edges_matches_pair_id "
        "ON edges_matches (pair_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_edges_matches_nodes_match_id "
        "ON edges_matches (nodes_match_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_edges_matches_edge_id "
        "ON edges_matches (edge_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_edges_matches_edge_type "
        "ON edges_matches (edge_type)"
    )


def create_node_static_props_table(cur) -> None:
    print("Creating node_static_props table...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS node_static_props (
            snproperty_id   BIGINT NOT NULL,
            node_id         TEXT NOT NULL,
            property_name   TEXT NOT NULL,
            string_value    TEXT,
            numeric_value   DOUBLE PRECISION,
            datetime_value  TIMESTAMP,
            string_values   TEXT[],
            numeric_values  DOUBLE PRECISION[],
            datetime_values TIMESTAMP[],
            created_at      TIMESTAMP NOT NULL,
            is_active       BOOLEAN NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_static_props_node_id "
        "ON node_static_props (node_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_static_props_property_name "
        "ON node_static_props (property_name)"
    )


def create_node_dynamic_props_table(cur) -> None:
    print("Creating node_dynamic_props table...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS node_dynamic_props (
            dnproperty_id   BIGINT NOT NULL,
            node_id         TEXT NOT NULL,
            property_name   TEXT NOT NULL,
            string_value    TEXT,
            numeric_value   DOUBLE PRECISION,
            datetime_value  TIMESTAMP,
            string_values   TEXT[],
            numeric_values  DOUBLE PRECISION[],
            datetime_values TIMESTAMP[],
            "from"          TIMESTAMP,
            "to"            TIMESTAMP,
            created_at      TIMESTAMP NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_dynamic_props_node_id "
        "ON node_dynamic_props (node_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_dynamic_props_property_name "
        "ON node_dynamic_props (property_name)"
    )


def create_edge_static_props_table(cur) -> None:
    print("Creating edge_static_props table...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_static_props (
            seproperty_id   BIGINT NOT NULL,
            edge_id         TEXT NOT NULL,
            property_name   TEXT NOT NULL,
            string_value    TEXT,
            numeric_value   DOUBLE PRECISION,
            datetime_value  TIMESTAMP,
            string_values   TEXT[],
            numeric_values  DOUBLE PRECISION[],
            datetime_values TIMESTAMP[],
            created_at      TIMESTAMP NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_edge_static_props_edge_id "
        "ON edge_static_props (edge_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_edge_static_props_property_name "
        "ON edge_static_props (property_name)"
    )


def create_edge_dynamic_props_table(cur) -> None:
    print("Creating edge_dynamic_props table...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS edge_dynamic_props (
            deproperty_id   BIGINT NOT NULL,
            edge_id         TEXT NOT NULL,
            property_name   TEXT NOT NULL,
            string_value    TEXT,
            numeric_value   DOUBLE PRECISION,
            datetime_value  TIMESTAMP,
            string_values   TEXT[],
            numeric_values  DOUBLE PRECISION[],
            datetime_values TIMESTAMP[],
            "from"          TIMESTAMP,
            "to"            TIMESTAMP,
            created_at      TIMESTAMP NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_edge_dynamic_props_edge_id "
        "ON edge_dynamic_props (edge_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_edge_dynamic_props_property_name "
        "ON edge_dynamic_props (property_name)"
    )


def create_metadata_node_labels_table(cur) -> None:
    print("Creating metadata_node_labels table...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata_node_labels (
            label_id    INTEGER NOT NULL,
            label       TEXT NOT NULL
        )
        """
    )


def create_metadata_edge_types_table(cur) -> None:
    print("Creating metadata_edge_types table...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata_edge_types (
            type_id     INTEGER NOT NULL,
            edge_type   TEXT NOT NULL
        )
        """
    )


def show_tables(cur) -> None:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    for (table_name,) in cur.fetchall():
        print(f"  - {table_name}")


def main() -> None:
    db_name = sys.argv[1] if len(sys.argv) > 1 else "graph_db"

    print(f"Creating PostgreSQL tables in database: {db_name}")

    create_database_if_not_exists(db_name)

    conn = get_db_connection(db_name)
    try:
        with conn.cursor() as cur:
            print(f"Successfully connected to database: {db_name}")

            create_node_label_pair_table(cur)
            create_node_labels_table(cur)
            create_node_pair_matches_table(cur)
            create_match_edges_table(cur)
            create_node_static_props_table(cur)
            create_node_dynamic_props_table(cur)
            create_edge_static_props_table(cur)
            create_edge_dynamic_props_table(cur)
            create_metadata_node_labels_table(cur)
            create_metadata_edge_types_table(cur)

            print(f"Successfully created tables in {db_name}:")
            show_tables(cur)
    except Exception as e:
        print(f"Error creating tables: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()