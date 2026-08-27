"""
drop_postgres_tables.py

Drops the graph-model tables in PostgreSQL. This is a PostgreSQL/Python
port of the original Spark/Iceberg DropIcebergTables.scala job.

Usage:
    python drop_postgres_tables.py [db_name]

    If db_name is omitted, it defaults to "graph_db".

"""

import os
import sys

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

TABLE_NAMES = [
    "node_label_pair",
    "node_labels",
    "node_pair_matches",
    "edges_matches",
    "node_static_props",
    "node_dynamic_props",
    "edge_static_props",
    "edge_dynamic_props",
    "metadata_node_labels",
    "metadata_edge_types",
]


def get_connection_params():
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": os.environ.get("PGPORT", "5432"),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
    }


def database_exists(db_name: str) -> bool:
    admin_db = os.environ.get("PGADMINDB", "postgres")
    params = get_connection_params()

    conn = psycopg2.connect(dbname=admin_db, **params)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def get_db_connection(db_name: str):
    params = get_connection_params()
    conn = psycopg2.connect(dbname=db_name, **params)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def get_remaining_tables(cur) -> list:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    return [row[0] for row in cur.fetchall()]


def drop_database(db_name: str) -> None:
    """Connects to the admin database and drops db_name."""
    admin_db = os.environ.get("PGADMINDB", "postgres")
    params = get_connection_params()

    conn = psycopg2.connect(dbname=admin_db, **params)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(db_name)))
        print(f"Successfully dropped database {db_name}")
    finally:
        conn.close()


def main() -> None:
    db_name = sys.argv[1] if len(sys.argv) > 1 else "graph_db"

    print(f"Dropping PostgreSQL tables in database: {db_name}")

    if not database_exists(db_name):
        print(f"Database {db_name} does not exist!")
        return

    conn = get_db_connection(db_name)
    try:
        with conn.cursor() as cur:
            # Drop each table
            for table_name in TABLE_NAMES:
                try:
                    print(f"Dropping table {table_name}...")
                    cur.execute(
                        sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                            sql.Identifier(table_name)
                        )
                    )
                    print(f"Successfully dropped {table_name}")
                except Exception as e:
                    print(f"Error dropping table {table_name}: {e}")

            # Optionally drop the database if it's empty
            remaining_tables = get_remaining_tables(cur)
            db_is_empty = len(remaining_tables) == 0
    finally:
        conn.close()

    if db_is_empty:
        print(f"Dropping empty database {db_name}...")
        drop_database(db_name)


if __name__ == "__main__":
    main()
