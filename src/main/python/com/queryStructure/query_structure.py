"""
query_structure.py

Port of com.query's QueryNode.scala, QueryEdge.scala, QueryStructure.scala,
WhereClause.scala, ReturnClause.scala, and StatCondPropsMG.scala.
"""

from dataclasses import dataclass, field


# ============================================================
# STAT-COND PROPS (WHERE-condition properties attached to a node/edge)
# ============================================================

class StatCondPropsMixin:
    """
    Mixed into QueryNode/QueryEdge. Requires the subclass to declare a
    `stat_cond_props: dict` field: {status: {property_name: Property}}.
    `status` groups conditions the same way the original Scala Integer key
    does (its exact meaning is set by whatever populates it, e.g. an
    ordinal used to correlate a condition to a DNF clause).
    """

    def add_stat_cond_prop(self, status: int, key: str, prop) -> None:
        self.stat_cond_props.setdefault(status, {})[key] = prop

    def get_stat_cond_prop(self, status: int, key: str):
        return self.stat_cond_props.get(status, {}).get(key)

    def remove_stat_cond_prop(self, status: int, key: str) -> None:
        inner = self.stat_cond_props.get(status)
        if inner and key in inner:
            del inner[key]
            if not inner:
                del self.stat_cond_props[status]

    def has_stat(self, status: int) -> bool:
        return status in self.stat_cond_props

    def has_stat_cond_prop(self, status: int, key: str) -> bool:
        return key in self.stat_cond_props.get(status, {})

    @property
    def stat_cond_prop_size(self) -> int:
        return sum(len(props) for props in self.stat_cond_props.values())

    def clear_stat_cond_props(self) -> None:
        self.stat_cond_props.clear()

    def _stat_cond_props_str(self, indent: str = "\t") -> str:
        if not self.stat_cond_props:
            return ""
        lines = [f"{indent}statCondProps={{"]
        for status in sorted(self.stat_cond_props):
            lines.append(f"{indent}\tstatus:{status}->{{")
            for key in sorted(self.stat_cond_props[status]):
                lines.append(f"{indent}\t\t{key}->Property({self.stat_cond_props[status][key]})")
            lines.append(f"{indent}\t}}")
        lines.append(f"{indent}}}")
        return "\n".join(lines) + "\n"


# ============================================================
# NODE / EDGE
# ============================================================

@dataclass
class QueryNode(StatCondPropsMixin):
    name: str
    labels: list = field(default_factory=list)
    stat_cond_props: dict = field(default_factory=dict)

    def has_label(self, label: str) -> bool:
        return label in self.labels

    def add_label(self, label: str) -> None:
        if label not in self.labels:
            self.labels.append(label)

    def remove_label(self, label: str) -> None:
        if label in self.labels:
            self.labels.remove(label)

    def __str__(self) -> str:
        s = f"QueryNode(\n\tname={self.name}\n\tlabels=[{', '.join(self.labels)}]\n"
        s += self._stat_cond_props_str()
        return s + ")"


@dataclass
class QueryEdge(StatCondPropsMixin):
    name: str
    src: str
    dst: str
    edge_type: str = ""
    stat_cond_props: dict = field(default_factory=dict)

    def __str__(self) -> str:
        s = (f"QueryEdge(\n\tname={self.name}\n\tsrcNodeName={self.src}\n"
             f"\tdstNodeName={self.dst}\n\ttype={self.edge_type}\n")
        s += self._stat_cond_props_str()
        return s + ")"


# ============================================================
# WHERE / RETURN CLAUSES
# ============================================================

@dataclass
class WhereClause:
    """
    expression : a dnf.BooleanExpression (typically already in DNF).
    conditions : {letter: (node_or_edge_name, Property)} -- the atomic
                 conditions the expression's variables refer to.
    """
    expression: object = None
    conditions: dict = field(default_factory=dict)

    def add_condition(self, variable: str, node_or_edge_name: str, condition) -> None:
        self.conditions[variable] = (node_or_edge_name, condition)

    def remove_condition(self, variable: str) -> None:
        self.conditions.pop(variable, None)


@dataclass
class ReturnClause:
    nodes: dict = field(default_factory=dict)       # {name: QueryNode}
    edges: dict = field(default_factory=dict)        # {name: QueryEdge}
    properties: dict = field(default_factory=dict)   # {alias: (varName, propName)}

    def add_node(self, name: str, node: QueryNode) -> None:
        self.nodes[name] = node

    def remove_node(self, name: str) -> None:
        self.nodes.pop(name, None)

    def add_edge(self, name: str, edge: QueryEdge) -> None:
        self.edges[name] = edge

    def remove_edge(self, name: str) -> None:
        self.edges.pop(name, None)

    def add_property(self, alias: str, variable_name: str, property_name: str) -> None:
        self.properties[alias] = (variable_name, property_name)

    def remove_property(self, alias: str) -> None:
        self.properties.pop(alias, None)

    def __str__(self) -> str:
        nodes = " ".join(self.nodes) if self.nodes else ""
        edges = " ".join(self.edges) if self.edges else ""
        props = " ".join(f"{v}.{p}" for v, p in self.properties.values())
        return f"nodes={{{nodes}}}\nedges={{{edges}}}properties={{{props}}}"


# ============================================================
# QUERY STRUCTURE
# ============================================================

class QueryStructure:
    """
    Nodes and edges are kept in insertion-ordered dicts. A node's position
    in that insertion order is its id(), used for the id(qi) < id(qj)
    canonical ordering compatibility-domain building requires.
    """

    def __init__(self):
        self.nodes: dict[str, QueryNode] = {}
        self.edges: dict[str, QueryEdge] = {}
        self.node_in_edges: dict[str, list] = {}
        self.node_out_edges: dict[str, list] = {}
        self.node_in_out_edges: dict[str, list] = {}
        self.where_clause: WhereClause = None
        self.return_clause: ReturnClause = None

    # ---------- nodes/edges ----------

    def add_node(self, name: str, labels: list = None) -> QueryNode:
        node = QueryNode(name, list(labels or []))
        self.nodes[name] = node
        return node

    def add_edge(self, name: str, src: str, dst: str, edge_type: str = "") -> QueryEdge:
        if src not in self.nodes or dst not in self.nodes:
            raise ValueError(f"Edge {name!r} references an unknown node ({src!r} -> {dst!r})")
        edge = QueryEdge(name, src, dst, edge_type)
        self.edges[name] = edge
        return edge

    def remove_node(self, name: str) -> None:
        self.nodes.pop(name, None)

    def remove_edge(self, name: str) -> None:
        self.edges.pop(name, None)

    def get_node(self, name: str) -> QueryNode:
        return self.nodes.get(name)

    def get_edge(self, name: str) -> QueryEdge:
        return self.edges.get(name)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def node_id(self, name: str) -> int:
        """Position of `name` in insertion order -- the id() used for id(qi) < id(qj)."""
        return list(self.nodes.keys()).index(name)

    # ---------- edge direction indices ----------

    def get_node_in_edges(self, name: str) -> list:
        return self.node_in_edges.get(name, [])

    def get_node_out_edges(self, name: str) -> list:
        return self.node_out_edges.get(name, [])

    def get_node_in_out_edges(self, name: str) -> list:
        return self.node_in_out_edges.get(name, [])

    def add_edge_to_node_in_edges(self, name: str, edge_name: str) -> None:
        edges = self.node_in_edges.setdefault(name, [])
        edges.append(edge_name)
        edges.sort()

    def add_edge_to_node_out_edges(self, name: str, edge_name: str) -> None:
        edges = self.node_out_edges.setdefault(name, [])
        edges.append(edge_name)
        edges.sort()

    def add_edge_to_node_in_out_edges(self, name: str, edge_name: str) -> None:
        edges = self.node_in_out_edges.setdefault(name, [])
        edges.append(edge_name)
        edges.sort()

    # ---------- where / return ----------

    def set_where_clause(self, wc: WhereClause) -> None:
        self.where_clause = wc

    def set_return_clause(self, rc: ReturnClause) -> None:
        self.return_clause = rc

    # ---------- compatibility-domain helpers ----------

    def edges_between(self, a: str, b: str) -> list:
        """All edges connecting a and b, in either direction (excludes self-loops)."""
        if a == b:
            return []
        return [e for e in self.edges.values() if {e.src, e.dst} == {a, b}]

    def connected_pairs(self):
        """
        Yields (qi, qj) for every unordered pair of distinct nodes connected
        by at least one edge, canonically ordered so id(qi) < id(qj).
        """
        seen = set()
        for edge in self.edges.values():
            if edge.src == edge.dst:
                continue
            a, b = edge.src, edge.dst
            pair = (a, b) if self.node_id(a) < self.node_id(b) else (b, a)
            if pair not in seen:
                seen.add(pair)
                yield pair

    # ---------- to string ----------

    def __str__(self) -> str:
        lines = ["QueryStructure(", "\tnodes={"]
        for name, node in self.nodes.items():
            lines.append(f"\t\t{name} -> " + str(node).replace("\n", "\n\t\t"))
        lines.append("\t}")
        lines.append("\tedges={")
        for name, edge in self.edges.items():
            lines.append(f"\t\t{name} -> " + str(edge).replace("\n", "\n\t\t"))
        lines.append("\t}")
        lines.append(")")

        if self.where_clause is not None:
            lines.append("--- WHERE CLAUSE ---")
            lines.append(f"DNF Expression: {self.where_clause.expression}")
            lines.append("Conditions:")
            for letter, (name, prop) in self.where_clause.conditions.items():
                lines.append(f"  {letter} -> node='{name}', condition={prop}")

        if self.return_clause is not None:
            lines.append("--- RETURN CLAUSE ---")
            lines.append(str(self.return_clause))

        return "\n".join(lines)
