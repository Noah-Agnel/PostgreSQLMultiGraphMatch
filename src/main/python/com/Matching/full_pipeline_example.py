"""
full_pipeline_example.py

Runs the complete pipeline end to end: a Cypher-style query string is
parsed into a QueryStructure, compatibility domains are computed against
the target database, and the multiway join in matching_engine.py finds
every solution.
"""

import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from com.PostgresTables.create_postgres_tables import get_db_connection
from com.queryStructure import cypher_wrapper
from com.CompatibilityDomain.compatibility_domain import compute_compatibility, TargetIndex
from com.Matching.matching_engine import find_solutions


QUERIES = [
    "MATCH (o:Officer)-[r1:`director of`]->(e:Entity)<-[r2:`intermediary of`]-(i:Intermediary) RETURN o",
    "MATCH (o:Officer)-[r1:`director of`]->(e:Entity)<-[r2:`intermediary of`]-(i:Intermediary) RETURN o",
]


def run_query(cypher: str, cur, target_index: TargetIndex) -> None:
    qs = cypher_wrapper.convert(cypher)
    print(f"\nQuery: {cypher}")

    t0 = time.time()
    node_candidates, edge_candidates = compute_compatibility(qs, cur, target_index=target_index)
    t1 = time.time()
    print(f"Compatibility domains computed in {t1 - t0:.2f}s:")
    for name, candidates in node_candidates.items():
        print(f"  node {name}: {len(candidates)} candidate(s)")
    for name, candidates in edge_candidates.items():
        print(f"  edge {name}: {len(candidates)} candidate(s)")

    solutions = find_solutions(qs, node_candidates, edge_candidates, cur=cur)
    t2 = time.time()
    print(f"Join found {len(solutions)} solution(s) in {t2 - t1:.2f}s")
    for solution in solutions[:5]:
        print(" ", solution)
    if len(solutions) > 5:
        print(f"  ... and {len(solutions) - 5} more")


def main() -> None:
    db_name = sys.argv[1] if len(sys.argv) > 1 else "panama_db"

    conn = get_db_connection(db_name)
    try:
        with conn.cursor() as cur:
            t0 = time.time()
            target_index = TargetIndex.build(cur)
            t1 = time.time()
            print(f"TargetIndex.build(): {t1 - t0:.2f}s (one-time cost, reused by every query below)")

            for cypher in QUERIES:
                run_query(cypher, cur, target_index)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
