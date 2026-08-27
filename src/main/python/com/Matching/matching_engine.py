"""
matching_engine.py

Finds every embedding of a query into the target graph, given the
candidate sets compute_compatibility() (compatibility_domain.py) produces.
Implemented as a sequence of pairwise hash joins over per-query-edge
"relations" of (src_target_id, dst_target_id, edge_id) rows -- the same
multiway-join approach a Spark job would use to combine candidate
DataFrames, just executed in-memory rather than distributed. Candidate
set sizes here are thousands-to-low-hundred-thousands per query edge, not
billions, so a distributed join isn't needed, and staying in plain Python
keeps this a single `python3 file.py`, consistent with the rest of this
port. Swapping the join step for real PySpark DataFrames later wouldn't
need any change to the algorithm above it, only IF throughput ever
actually warrants it.

ALGORITHM
---------
1. Build a join plan: an ordering of query edges (as pairwise joins) and
   any isolated query nodes (as cross products), such that every step
   after the first shares at least one already-bound query variable with
   the accumulated partial result -- required for the join to make sense
   at all (a "connected" join order), not just for performance.
2. Walk the plan, hash-joining each relation into the accumulated partial
   bindings on whatever query variable(s) it shares with what's already
   joined, enforcing injectivity (no two query NODES may bind to the same
   target node id -- standard subgraph-isomorphism requirement) at every
   step, not deferred to the end, to keep intermediate result sets small.
3. Post-filter the resulting complete bindings through the query's WHERE
   clause. Properties are intentionally not touched anywhere before this
   -- compatibility-domain building and the join itself are both purely
   structural (per Micale et al.: "Node and edge properties are not used
   to build compatibility domains").

EXTENSION POINTS (deliberately left as-is / simple defaults for now --
see the three follow-up items this is building toward)
-------------------------------------------------------------------------
- n.prop > m.prop conditions: WHERE evaluation already runs against a
  COMPLETE binding (every query variable resolved), so a cross-variable
  condition is no harder to evaluate than a single-variable one -- it
  just needs a new condition type WhereClause.conditions can hold, and a
  branch in `_evaluate_condition` to dispatch on it. No change needed to
  the join engine itself.
- Symmetry breaking: `find_solutions(..., extra_predicates=[...])` already
  accepts arbitrary `Callable[[dict], bool]` predicates checked against
  each complete binding. Symmetry-breaking constraints (e.g.
  `int(binding["q1"]) < int(binding["q2"])` for query nodes the query
  treats interchangeably) are just more predicates in that list. Checking
  them earlier, inside the join loop against partial bindings, would prune
  the search sooner -- once real symmetry constraints exist (which
  requires detecting query automorphisms first), that's the optimization
  to make; a post-filter is still correct today, just less efficient.
- Ordering: `find_solutions(..., join_order=...)` takes the join plan as
  an explicit, overridable parameter instead of hardcoding traversal
  order inside the join loop. `default_join_order` is one strategy (a
  simple connected frontier expansion, not cost-based); a smarter one
  (e.g. cheapest/most-selective relation first) can be swapped in without
  touching the join mechanics in `find_solutions`.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from com.queryStructure.query_structure import QueryStructure, WhereClause


# ============================================================
# JOIN PLAN
# ============================================================

@dataclass(frozen=True)
class EdgeStep:
    """Join step: bind a query edge's (src, dst, edge) relation into the partial result."""
    edge_name: str
    src: str
    dst: str


@dataclass(frozen=True)
class NodeStep:
    """Join step: cross an isolated query node's candidate set into the partial result."""
    node_name: str


def default_join_order(query: QueryStructure) -> list:
    """
    A simple, correct-by-construction join order: repeatedly add any
    not-yet-joined edge touching an already-joined node, starting a new
    component when none remain. Isolated nodes (no edges) are appended as
    NodeSteps at the end, joined via cross product.

    This is the "ordering" extension point's default -- it makes no
    attempt at picking a cheap/selective order, just a valid one.
    """
    adjacency = defaultdict(list)  # node_name -> [(edge_name, other_node_name)]
    for edge in query.edges.values():
        if edge.src != edge.dst:
            adjacency[edge.src].append((edge.name, edge.dst))
            adjacency[edge.dst].append((edge.name, edge.src))

    remaining_edges = {name for name, e in query.edges.items() if e.src != e.dst}
    visited_nodes = set()
    visited_edges = set()
    steps = []

    def add_edge_step(edge_name: str) -> None:
        edge = query.edges[edge_name]
        steps.append(EdgeStep(edge.name, edge.src, edge.dst))
        visited_edges.add(edge.name)
        visited_nodes.update((edge.src, edge.dst))
        remaining_edges.discard(edge.name)

    while remaining_edges:
        progressed = False
        for node_name in list(visited_nodes):
            for edge_name, _other in adjacency[node_name]:
                if edge_name not in visited_edges:
                    add_edge_step(edge_name)
                    progressed = True
                    break
            if progressed:
                break
        if not progressed:
            add_edge_step(next(iter(remaining_edges)))  # start a new (disconnected) component

    for node_name in query.nodes:
        if node_name not in visited_nodes:
            steps.append(NodeStep(node_name))

    return steps


# ============================================================
# JOIN EXECUTION
# ============================================================

def _used_node_ids(binding: dict, query: QueryStructure) -> set:
    return {binding[name] for name in query.nodes if name in binding}


def _join_edge_step(partial_results: list, bound_vars: set, step: EdgeStep,
                     relation: set, query: QueryStructure) -> list:
    src_bound = step.src in bound_vars
    dst_bound = step.dst in bound_vars
    new_results = []

    if src_bound or dst_bound:
        # Hash join: index the smaller/known side on the shared key(s), then probe with the relation.
        index = defaultdict(list)
        for binding in partial_results:
            key = (binding[step.src] if src_bound else None, binding[step.dst] if dst_bound else None)
            index[key].append(binding)

        for src_t, dst_t, edge_id in relation:
            key = (src_t if src_bound else None, dst_t if dst_bound else None)
            for binding in index.get(key, ()):
                used = _used_node_ids(binding, query)
                if (not src_bound and src_t in used) or (not dst_bound and dst_t in used):
                    continue
                new_binding = dict(binding)
                new_binding[step.src] = src_t
                new_binding[step.dst] = dst_t
                new_binding[step.edge_name] = edge_id
                new_results.append(new_binding)
    else:
        # Neither endpoint bound yet: first edge of a (new) component -- cross join.
        for binding in partial_results:
            used = _used_node_ids(binding, query)
            for src_t, dst_t, edge_id in relation:
                if src_t == dst_t or src_t in used or dst_t in used:
                    continue
                new_binding = dict(binding)
                new_binding[step.src] = src_t
                new_binding[step.dst] = dst_t
                new_binding[step.edge_name] = edge_id
                new_results.append(new_binding)

    return new_results


def _join_node_step(partial_results: list, step: NodeStep, relation: set, query: QueryStructure) -> list:
    new_results = []
    for binding in partial_results:
        used = _used_node_ids(binding, query)
        for target_id in relation:
            if target_id in used:
                continue
            new_binding = dict(binding)
            new_binding[step.node_name] = target_id
            new_results.append(new_binding)
    return new_results


# ============================================================
# WHERE-CLAUSE POST-FILTER (simple, single-variable conditions only)
# ============================================================

_PROP_TABLES = {
    False: ("node_static_props", "node_dynamic_props", "node_id"),
    True: ("edge_static_props", "edge_dynamic_props", "edge_id"),
}


def _fetch_property_value(cur, entity_id: str, property_name: str, is_edge: bool):
    """Looks up a single property's value for a node/edge id from the *_static_props /
    *_dynamic_props EAV tables, returning None if it isn't set."""
    static_table, dynamic_table, id_col = _PROP_TABLES[is_edge]
    for table in (static_table, dynamic_table):
        cur.execute(
            f"SELECT string_value, numeric_value, datetime_value, "
            f"string_values, numeric_values, datetime_values "
            f"FROM {table} WHERE {id_col} = %s AND property_name = %s LIMIT 1",
            (entity_id, property_name),
        )
        row = cur.fetchone()
        if row is None:
            continue
        for value in row:
            if value is not None:
                return value
    return None


def _evaluate_condition(condition: tuple, binding: dict, query: QueryStructure, cur) -> bool:
    """
    Dispatches on the condition's shape. Today WhereClause.conditions only
    holds (node_or_edge_name, Property) tuples -- single-variable conditions
    like `n.age > 25`. Once cross-variable conditions (n.prop > m.prop) are
    added as a new condition type, add a branch here; nothing about the
    join engine or evaluate_where_clause()'s caller needs to change, since
    it already runs against a complete binding with every query variable
    resolved.
    """
    node_or_edge_name, prop = condition
    entity_id = binding[node_or_edge_name]
    is_edge = node_or_edge_name in query.edges
    actual_value = _fetch_property_value(cur, entity_id, prop.name, is_edge)
    return prop.evaluate(actual_value)


def evaluate_where_clause(where_clause: WhereClause, binding: dict, query: QueryStructure, cur) -> bool:
    if where_clause is None or where_clause.expression is None:
        return True
    assignment = {
        letter: _evaluate_condition(condition, binding, query, cur)
        for letter, condition in where_clause.conditions.items()
    }
    return where_clause.expression.evaluate(assignment)


# ============================================================
# ENTRY POINT
# ============================================================

def find_solutions(query: QueryStructure, node_candidates: dict, edge_candidates: dict,
                    cur=None, join_order: list = None,
                    extra_predicates: list = None) -> list:
    """
    Finds every solution (embedding) of `query` into the target graph.

    node_candidates : {query_node_name: set(target_node_id)}
    edge_candidates : {query_edge_name: set((src_target_id, dst_target_id, target_edge_id))}
                       (compute_compatibility()'s output, unchanged)
    cur             : open db cursor, required only if query has a WHERE clause
    join_order      : overrides default_join_order(query) -- the ORDERING extension point
    extra_predicates: additional Callable[[dict], bool] checks against each
                       complete solution -- the SYMMETRY BREAKING extension point

    Returns a list of solutions, each a dict mapping every query node and
    edge name to its bound target node/edge id.
    """
    if join_order is None:
        join_order = default_join_order(query)

    partial_results = [{}]
    bound_vars = set()

    for step in join_order:
        if not partial_results:
            break
        if isinstance(step, EdgeStep):
            relation = edge_candidates.get(step.edge_name, set())
            partial_results = _join_edge_step(partial_results, bound_vars, step, relation, query)
            bound_vars |= {step.src, step.dst, step.edge_name}
        elif isinstance(step, NodeStep):
            relation = node_candidates.get(step.node_name, set())
            partial_results = _join_node_step(partial_results, step, relation, query)
            bound_vars.add(step.node_name)
        else:
            raise TypeError(f"Unknown join step type: {type(step)}")

    solutions = partial_results

    if query.where_clause is not None:
        if cur is None:
            raise ValueError("query has a WHERE clause but no db cursor was given to evaluate it")
        solutions = [s for s in solutions if evaluate_where_clause(query.where_clause, s, query, cur)]

    if extra_predicates:
        for predicate in extra_predicates:
            solutions = [s for s in solutions if predicate(s)]

    return solutions
