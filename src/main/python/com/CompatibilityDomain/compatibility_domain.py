"""
compatibility_domain.py

Builds MultiGraphMatch's compatibility domains: for every pair of connected
query nodes (qi, qj) with id(qi) < id(qj), Dom(qi, qj) is the set of pairs
of connected target nodes (ti, tj) compatible with (qi, qj) -- matching on
edge direction/type between qi and qj, node labels, and type-dependent
in/out-degree.
"""

import time
from collections import defaultdict
from contextlib import contextmanager

from com.queryStructure.query_structure import QueryStructure


@contextmanager
def _timed(label: str):
    t0 = time.time()
    yield
    print(f"  [timing] {label}: {time.time() - t0:.2f}s")


# ============================================================
# BIT SIGNATURE CONFIG
# ============================================================

class BitSignatureConfig:
    def __init__(self, node_labels: list, edge_types: list):
        self.label_idx = {label: i for i, label in enumerate(node_labels)}
        self.type_idx = {etype: i for i, etype in enumerate(edge_types)}
        L, E = len(node_labels), len(edge_types)
        self.first_label_offset = 0
        self.in_edge_offset = L
        self.out_edge_offset = L + E
        self.second_label_offset = L + 2 * E

    def signature(self, first_labels, second_labels, out_types=(), in_types=()) -> int:
        bits = 0
        for label in first_labels or ():
            idx = self.label_idx.get(label)
            if idx is not None:
                bits |= 1 << (self.first_label_offset + idx)
        for etype in in_types or ():
            idx = self.type_idx.get(etype)
            if idx is not None:
                bits |= 1 << (self.in_edge_offset + idx)
        for etype in out_types or ():
            idx = self.type_idx.get(etype)
            if idx is not None:
                bits |= 1 << (self.out_edge_offset + idx)
        for label in second_labels or ():
            idx = self.label_idx.get(label)
            if idx is not None:
                bits |= 1 << (self.second_label_offset + idx)
        return bits


def load_config(cur) -> BitSignatureConfig:
    cur.execute("SELECT label FROM metadata_node_labels ORDER BY label_id")
    node_labels = [row[0] for row in cur.fetchall()]
    cur.execute("SELECT edge_type FROM metadata_edge_types ORDER BY type_id")
    edge_types = [row[0] for row in cur.fetchall()]
    return BitSignatureConfig(node_labels, edge_types)


def _contains(row_bits: int, other_bits: int) -> bool:
    """True if `row_bits` has every bit set that `other_bits` has."""
    return (row_bits & other_bits) == other_bits


# ============================================================
# QUERY SIDE: pair signatures + per-node type degrees
# ============================================================

def _empty_degree() -> dict:
    return {"in": defaultdict(int), "out": defaultdict(int)}


def build_query_pair_signatures(query: QueryStructure, config: BitSignatureConfig) -> dict:
    """
    Returns {(a, b): bitmask} for every ordered pair of connected query
    nodes (both (qi, qj) and (qj, qi) for each connected unordered pair),
    accumulating every edge between them in either direction.
    """
    signatures = {}
    for qi, qj in query.connected_pairs():
        edges = query.edges_between(qi, qj)
        out_from_qi = [e.edge_type for e in edges if e.src == qi]
        out_from_qj = [e.edge_type for e in edges if e.src == qj]

        node_qi, node_qj = query.nodes[qi], query.nodes[qj]
        signatures[(qi, qj)] = config.signature(
            node_qi.labels, node_qj.labels, out_types=out_from_qi, in_types=out_from_qj,
        )
        signatures[(qj, qi)] = config.signature(
            node_qj.labels, node_qi.labels, out_types=out_from_qj, in_types=out_from_qi,
        )
    return signatures


def compute_query_degrees(query: QueryStructure) -> dict:
    """{node_name: {"in": {edge_type: count}, "out": {edge_type: count}}} across ALL query edges."""
    degrees = {name: _empty_degree() for name in query.nodes}
    for edge in query.edges.values():
        if edge.src == edge.dst:
            continue
        degrees[edge.src]["out"][edge.edge_type] += 1
        degrees[edge.dst]["in"][edge.edge_type] += 1
    return degrees


# ============================================================
# TARGET SIDE: signatures (deduplicated) + instances + per-node type degrees
# ============================================================

def load_target_signatures(cur, config: BitSignatureConfig) -> tuple:
    """
    Returns (signatures, signature_edges):
        signatures      : {(pair_id, src_labels, dst_labels): bitmask} --
                           one entry per DISTINCT row of node_label_pair
                           (931 for the Panama dataset, vs. the 1.4M
                           node_pair_matches instances that share them).
        signature_edges : {same key: (edge_1_2_types dict, edge_2_1_types dict)}
    """
    with _timed("  fetch + build node_label_pair signatures"):
        cur.execute("SELECT pair_id, src_labels, dst_labels, edge_1_2_types, edge_2_1_types FROM node_label_pair")
        signatures = {}
        signature_edges = {}
        for pair_id, src_labels, dst_labels, e12, e21 in cur.fetchall():
            key = (pair_id, tuple(src_labels or ()), tuple(dst_labels or ()))
            e12, e21 = e12 or {}, e21 or {}
            signatures[key] = config.signature(key[1], key[2], out_types=e12.keys(), in_types=e21.keys())
            signature_edges[key] = (e12, e21)
    print(f"    ({len(signatures)} distinct signatures)")
    return signatures, signature_edges


def load_target_instances_and_degrees(cur, signature_edges: dict) -> tuple:
    """
    Returns (instances_by_signature, target_degrees, node_labels):
        instances_by_signature : {signature_key: [(ti, tj), ...]} -- every
                                  node_pair_matches row, grouped by which
                                  node_label_pair signature it belongs to.
        target_degrees         : {node_id: {"in": {...}, "out": {...}}},
                                  aggregated across every instance the node
                                  participates in.
        node_labels             : {node_id: labels}, fetched here anyway to
                                  resolve each instance's signature, and
                                  returned so callers (e.g. TargetIndex) can
                                  reuse it instead of re-querying node_labels
                                  again for the same purpose.
    """
    with _timed("  fetch node_labels"):
        cur.execute("SELECT node_id, labels FROM node_labels")
        node_labels = {node_id: tuple(labels) for node_id, labels in cur.fetchall()}
    print(f"    ({len(node_labels)} nodes)")

    with _timed("  fetch node_pair_matches"):
        cur.execute("SELECT pair_id, source_node_id, target_node_id FROM node_pair_matches")
        rows = cur.fetchall()
    print(f"    ({len(rows)} rows)")

    instances_by_signature = defaultdict(list)
    target_degrees = defaultdict(_empty_degree)
    skipped = 0

    with _timed("  group instances + aggregate degrees"):
        for pair_id, ti, tj in rows:
            labels_ti = node_labels.get(ti)
            labels_tj = node_labels.get(tj)
            key = (pair_id, labels_ti, labels_tj)
            entry = signature_edges.get(key)
            if entry is None:
                skipped += 1
                continue
            e12, e21 = entry  # e12: ti->tj types, e21: tj->ti types
            instances_by_signature[key].append((ti, tj))

            for etype, count in e12.items():
                target_degrees[ti]["out"][etype] += count
                target_degrees[tj]["in"][etype] += count
            for etype, count in e21.items():
                target_degrees[tj]["out"][etype] += count
                target_degrees[ti]["in"][etype] += count

    if skipped:
        print(f"  Warning: skipped {skipped} node_pair_matches row(s) with no "
              f"matching node_label_pair entry (missing node_labels or stale data)")

    return instances_by_signature, target_degrees, node_labels


# ============================================================
# TargetIndex: build the target side ONCE, reuse across many queries
# ============================================================

class TargetIndex:
    """
    Precomputed target-side data (config, deduplicated signatures,
    instances, degrees, node labels), built once from a database snapshot
    via TargetIndex.build(cur) and reusable across many
    compute_compatibility()/compute_compatibility_domains() calls against
    that same snapshot -- see the module docstring's "REUSABLE TargetIndex"
    section. Mirrors TargetGraph building its TargetBitmatrix once in the
    reference Java implementation instead of rebuilding it per query.
    """

    def __init__(self, config, signatures, instances_by_signature, target_degrees, node_labels):
        self.config = config
        self.signatures = signatures
        self.instances_by_signature = instances_by_signature
        self.target_degrees = target_degrees
        self.node_labels = node_labels
        self._edges_index_cache = {}  # frozenset(edge_types) -> index dict

    @classmethod
    def build(cls, cur) -> "TargetIndex":
        print("TargetIndex.build():")
        with _timed("TOTAL"):
            with _timed("load_config"):
                config = load_config(cur)
            with _timed("load_target_signatures"):
                signatures, signature_edges = load_target_signatures(cur, config)
            with _timed("load_target_instances_and_degrees"):
                instances_by_signature, target_degrees, node_labels = load_target_instances_and_degrees(cur, signature_edges)
        return cls(config, signatures, instances_by_signature, target_degrees, node_labels)

    def edges_index(self, cur, edge_types: set) -> dict:
        """Memoized per distinct set of edge types actually requested so far."""
        key = frozenset(edge_types)
        if key in self._edges_index_cache:
            print(f"  [timing] edges_index for {sorted(edge_types)}: cache hit, 0.00s")
            return self._edges_index_cache[key]
        with _timed(f"edges_index for {sorted(edge_types)} (cache miss)"):
            result = _load_edges_index(cur, edge_types)
        print(f"    ({sum(len(v) for v in result.values())} edges)")
        self._edges_index_cache[key] = result
        return result


# ============================================================
# DOMAIN COMPUTATION
# ============================================================

def _degree_ok(query_degree: dict, target_degree: dict) -> bool:
    for direction in ("in", "out"):
        for etype, needed in query_degree[direction].items():
            if target_degree[direction].get(etype, 0) < needed:
                return False
    return True


def compute_compatibility_domains(query: QueryStructure, cur, target_index: TargetIndex = None) -> dict:
    """
    Returns {(qi, qj): [(ti, tj), ...]} -- Dom(qi, qj) for every connected
    query-node pair with id(qi) < id(qj), per Micale et al. Sec 5.2.

    The bitmask check runs once per DISTINCT signature (~931 for the
    Panama dataset), not once per node-pair instance (~1.4M) -- see
    load_target_signatures(). Only signatures that actually pass get their
    instances fanned out for the (necessarily per-instance) degree check.
    """
    if target_index is None:
        target_index = TargetIndex.build(cur)
    config = target_index.config
    query_sigs = build_query_pair_signatures(query, config)
    query_degrees = compute_query_degrees(query)

    signatures = target_index.signatures
    instances_by_signature = target_index.instances_by_signature
    target_degrees = target_index.target_degrees

    domains = {}
    with _timed(f"compute_compatibility_domains matching loop ({len(signatures)} signatures)"):
        for qi, qj in query.connected_pairs():
            direct_sig = query_sigs[(qi, qj)]
            swapped_sig = query_sigs[(qj, qi)]
            deg_qi, deg_qj = query_degrees[qi], query_degrees[qj]

            matches = []
            for sig_key, bitmask in signatures.items():
                direct_match = _contains(bitmask, direct_sig)
                swapped_match = _contains(bitmask, swapped_sig)
                if not direct_match and not swapped_match:
                    continue
                for ti, tj in instances_by_signature.get(sig_key, ()):
                    if direct_match and _degree_ok(deg_qi, target_degrees[ti]) and _degree_ok(deg_qj, target_degrees[tj]):
                        matches.append((ti, tj))
                    if swapped_match and _degree_ok(deg_qi, target_degrees[tj]) and _degree_ok(deg_qj, target_degrees[ti]):
                        matches.append((tj, ti))
            domains[(qi, qj)] = matches
            print(f"    ({qi}, {qj}): {len(matches)} matches")

    return domains


# ============================================================
# CANDIDATE MAPS (query node/edge -> compatible target nodes/edges)
# ============================================================

def _load_isolated_node_candidates(node_labels: dict, query: QueryStructure, isolated_names: list) -> dict:
    """
    Query nodes with no edges never appear in any Dom(qi, qj), so they can't
    be constrained by the pair-domain scan above. Fall back to a plain label
    lookup: a target node is a candidate iff it carries at least the query
    node's labels. `node_labels` comes from the TargetIndex (already loaded
    for signature resolution) rather than a fresh query.
    """
    if not isolated_names:
        return {}
    result = {}
    for name in isolated_names:
        required = set(query.nodes[name].labels)
        result[name] = {node_id for node_id, labels in node_labels.items() if required.issubset(labels or ())}
    return result


def _load_edges_index(cur, edge_types: set) -> dict:
    """
    {(nodes_match_id, edge_direction, edge_type): [edge_id, ...]}, restricted
    to `edge_types` -- edges_matches has one row per edge in the whole target
    graph (1.5M+ for the Panama dataset, spanning 287 distinct edge types),
    but a query only ever needs the handful of types its own edges use, so
    filtering server-side avoids fetching and indexing the other ~99% of it.
    """
    if not edge_types:
        return {}
    cur.execute(
        "SELECT nodes_match_id, edge_direction, edge_type, edge_id FROM edges_matches "
        "WHERE edge_type = ANY(%s)",
        (list(edge_types),),
    )
    index = defaultdict(list)
    for nodes_match_id, edge_direction, edge_type, edge_id in cur.fetchall():
        index[(nodes_match_id, edge_direction, edge_type)].append(edge_id)
    return index


def build_candidate_maps(query: QueryStructure, domains: dict, cur, target_index: TargetIndex = None) -> tuple:
    """
    Derives the final, directly-usable output from the pair domains:
        node_candidates: {query_node_name: set(target_node_id)}
        edge_candidates: {query_edge_name: set((src_target_id, dst_target_id, target_edge_id))}

    edge_candidates rows carry the (src, dst) target-node pair each
    candidate edge connects, not just a bare edge id -- matching_engine.py
    needs that pairing to join candidate relations together on shared
    query-node variables; a flat set of edge ids alone can't be joined.

    A node's candidate set is the INTERSECTION of its projections across
    every Dom(...) it appears in (it must be simultaneously compatible with
    all of its query neighbors), not just the union from one pair.

    Pass the same target_index used for compute_compatibility_domains() to
    reuse its cached node_labels and edges_index (memoized per edge-type
    set) instead of re-querying them.
    """
    if target_index is None:
        target_index = TargetIndex.build(cur)

    with _timed("build_candidate_maps: node candidate intersection"):
        node_candidates = {name: None for name in query.nodes}
        for (qi, qj), pairs in domains.items():
            ti_set = {ti for ti, _ in pairs}
            tj_set = {tj for _, tj in pairs}
            node_candidates[qi] = ti_set if node_candidates[qi] is None else node_candidates[qi] & ti_set
            node_candidates[qj] = tj_set if node_candidates[qj] is None else node_candidates[qj] & tj_set

        isolated = [name for name, candidates in node_candidates.items() if candidates is None]
        node_candidates.update(_load_isolated_node_candidates(target_index.node_labels, query, isolated))
        node_candidates = {name: (candidates or set()) for name, candidates in node_candidates.items()}

    edge_types = {edge.edge_type for edge in query.edges.values() if edge.src != edge.dst}
    edges_index = target_index.edges_index(cur, edge_types)

    with _timed("build_candidate_maps: edge candidate resolution"):
        edge_candidates = {}
        for edge in query.edges.values():
            if edge.src == edge.dst:
                print(f"  Warning: query edge {edge.name!r} is a self-loop, unsupported "
                      f"(target self-loops are excluded from node_pair_matches) -- no candidates")
                edge_candidates[edge.name] = set()
                continue

            qi, qj = edge.src, edge.dst
            a, b = (qi, qj) if query.node_id(qi) < query.node_id(qj) else (qj, qi)
            pairs = domains.get((a, b), [])

            candidates = set()
            for ta, tb in pairs:
                src_t, dst_t = (ta, tb) if a == qi else (tb, ta)
                if int(src_t) < int(dst_t):
                    nodes_match_id, direction = f"{src_t}_{dst_t}", "min_to_max"
                else:
                    nodes_match_id, direction = f"{dst_t}_{src_t}", "max_to_min"
                for edge_id in edges_index.get((nodes_match_id, direction, edge.edge_type), ()):
                    candidates.add((src_t, dst_t, edge_id))
            edge_candidates[edge.name] = candidates

    return node_candidates, edge_candidates


def compute_compatibility(query: QueryStructure, cur, target_index: TargetIndex = None) -> tuple:
    """
    Entry point: input is a QueryStructure and an open Postgres cursor on
    the target database, output is (node_candidates, edge_candidates) as
    described in build_candidate_maps().

    For repeated queries against the same target snapshot, build a
    TargetIndex ONCE (TargetIndex.build(cur)) and pass it in here every
    time instead of leaving target_index unset -- see the module
    docstring's "REUSABLE TargetIndex" section. Without it, each call
    rebuilds the target side from scratch (the original, still-correct
    behavior, just slower under repeated use).
    """
    with _timed("compute_compatibility TOTAL"):
        if target_index is None:
            target_index = TargetIndex.build(cur)
        domains = compute_compatibility_domains(query, cur, target_index)
        result = build_candidate_maps(query, domains, cur, target_index)
    return result
