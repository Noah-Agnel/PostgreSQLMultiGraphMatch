"""
list_postgres_tables.py

Lists the graph-model tables in PostgreSQL, along with schema, indexes, and
row counts. This is a PostgreSQL/Python port of the original Spark/Iceberg
ListIcebergTables.scala job.

Usage:
    python list_postgres_tables.py [db_name]

    If db_name is omitted, it defaults to "graph_db".

"""

import os
import sys

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def get_connection_params():
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": os.environ.get("PGPORT", "5432"),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
    }


def show_databases() -> list:
    admin_db = os.environ.get("PGADMINDB", "postgres")
    params = get_connection_params()

    conn = psycopg2.connect(dbname=admin_db, **params)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_db_connection(db_name: str):
    params = get_connection_params()
    conn = psycopg2.connect(dbname=db_name, **params)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def list_tables(cur) -> list:
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


def describe_table(cur, table_name: str) -> None:
    print("Schema:")
    cur.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    for column_name, data_type, is_nullable in cur.fetchall():
        nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
        print(f"  {column_name:<20} {data_type:<25} {nullable}")


def show_table_size(cur, table_name: str) -> None:
    print("Table Properties:")
    cur.execute("SELECT pg_size_pretty(pg_total_relation_size(%s))", (table_name,))
    (size,) = cur.fetchone()
    print(f"  total_size: {size}")


def show_indexes(cur, table_name: str) -> None:
    cur.execute(
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = %s
        ORDER BY indexname
        """,
        (table_name,),
    )
    indexes = cur.fetchall()
    if indexes:
        print("Indexes:")
        for indexname, indexdef in indexes:
            print(f"  {indexname}: {indexdef}")


def show_row_count(cur, table_name: str) -> None:
    cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
    (count,) = cur.fetchone()
    print(f"Row count: {count}")


def main() -> None:
    db_name = sys.argv[1] if len(sys.argv) > 1 else "graph_db"

    print(f"Listing PostgreSQL tables in database: {db_name}")

    print("Available databases:")
    for name in show_databases():
        print(f"  - {name}")

    if db_name not in show_databases():
        print(f"Database {db_name} does not exist!")
        return

    conn = get_db_connection(db_name)
    try:
        with conn.cursor() as cur:
            print(f"\nTables in database '{db_name}':")
            tables = list_tables(cur)
            for table_name in tables:
                print(f"  - {table_name}")

            if tables:
                print(f"\nDetailed information for tables in '{db_name}':")
                for table_name in tables:
                    print(f"\n=== Table: {table_name} ===")
                    try:
                        describe_table(cur, table_name)
                        show_table_size(cur, table_name)
                        show_indexes(cur, table_name)
                        show_row_count(cur, table_name)
                    except Exception as e:
                        print(f"Error getting details for table {table_name}: {e}")
            else:
                print(f"No tables found in database '{db_name}'")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
