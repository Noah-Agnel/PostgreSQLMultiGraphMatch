"""
cypher_wrapper.py

Port of com.query.wrapper's CypherQueryWrapper.scala + MatchClauseConverter.scala
+ WhereClauseConverter.scala + ReturnClauseConverter.scala: takes a Cypher-style
query string and returns a QueryStructure.
"""

import re

from com.queryStructure.query_structure import QueryStructure, WhereClause, ReturnClause
from com.queryStructure.properties import IntegerProp, DoubleProp, StringProp, StringArrayProp, Operator
from com.queryStructure import dnf


class CypherParseError(ValueError):
    pass


# ============================================================
# TOKENIZER
# ============================================================

_TOKEN_SPEC = [
    ("STRING", r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""),
    # Backtick-quoted identifier, standard Cypher escaping for labels/types/
    # variable names containing spaces or other characters IDENT can't match
    # (e.g. an edge type like `director of`).
    ("BACKTICK_IDENT", r"`[^`]+`"),
    ("ARROW_R", r"->"),
    ("ARROW_L", r"<-"),
    ("LE", r"<="),
    ("GE", r">="),
    ("NE", r"<>"),
    ("LBRACE", r"\{"),
    ("RBRACE", r"\}"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("LBRACKET", r"\["),
    ("RBRACKET", r"\]"),
    ("COLON", r":"),
    ("COMMA", r","),
    ("DOT", r"\."),
    ("EQ", r"="),
    ("LT", r"<"),
    ("GT", r">"),
    ("DASH", r"-"),
    ("FLOAT", r"\d+\.\d+"),
    ("INT", r"\d+"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("WS", r"\s+"),
]
_MASTER_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC))

_KEYWORDS = {
    "MATCH", "WHERE", "RETURN", "AND", "OR", "NOT", "XOR", "AS",
    "IN", "IS", "NULL", "STARTS", "ENDS", "WITH", "CONTAINS", "TRUE", "FALSE",
}


class Token:
    __slots__ = ("kind", "text")

    def __init__(self, kind, text):
        self.kind = kind
        self.text = text

    def __repr__(self):
        return f"{self.kind}({self.text!r})"


def tokenize(text: str) -> list:
    tokens = []
    pos = 0
    while pos < len(text):
        m = _MASTER_RE.match(text, pos)
        if not m:
            raise CypherParseError(f"Unexpected character at position {pos}: {text[pos:pos + 10]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "WS":
            continue
        value = m.group(kind)
        if kind == "IDENT" and value.upper() in _KEYWORDS:
            kind = value.upper()
        elif kind == "STRING":
            value = value[1:-1]
        elif kind == "BACKTICK_IDENT":
            kind, value = "IDENT", value[1:-1]  # never a keyword -- it's explicitly escaped
        tokens.append(Token(kind, value))
    return tokens


class TokenStream:
    def __init__(self, tokens: list):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> Token:
        return self.tokens[self.i] if self.i < len(self.tokens) else Token("EOF", "")

    def peek_kind(self) -> str:
        return self.peek().kind

    def advance(self) -> Token:
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.advance()
        if tok.kind != kind:
            raise CypherParseError(f"Expected {kind} but found {tok}")
        return tok


# ============================================================
# TOP-LEVEL: split into MATCH / WHERE / RETURN clauses
# ============================================================

_CLAUSE_KEYWORDS = {"MATCH", "WHERE", "RETURN"}


def _split_clauses(tokens: list) -> dict:
    """Splits the token stream into {keyword: [tokens after it]} at depth 0."""
    clauses = {}
    depth = 0
    current_kw = None
    current_tokens = []

    def flush():
        if current_kw is not None:
            clauses.setdefault(current_kw, []).extend(current_tokens)

    for tok in tokens:
        if tok.kind in ("LPAREN", "LBRACKET", "LBRACE"):
            depth += 1
        elif tok.kind in ("RPAREN", "RBRACKET", "RBRACE"):
            depth -= 1

        if depth == 0 and tok.kind in _CLAUSE_KEYWORDS:
            flush()
            current_kw = tok.kind
            current_tokens = []
        else:
            current_tokens.append(tok)
    flush()
    return clauses


# ============================================================
# MATCH CLAUSE
# ============================================================

_anon_counter = {"node": 0, "edge": 0}


def _fresh_anon(kind: str) -> str:
    _anon_counter[kind] += 1
    return f"_anon{'Edge' if kind == 'edge' else ''}{_anon_counter[kind]}"


def _skip_brace_block(ts: TokenStream) -> None:
    """Consumes a {...} block without interpreting it (inline props aren't used)."""
    ts.expect("LBRACE")
    depth = 1
    while depth > 0:
        tok = ts.advance()
        if tok.kind == "EOF":
            raise CypherParseError("Unterminated {...} block")
        if tok.kind == "LBRACE":
            depth += 1
        elif tok.kind == "RBRACE":
            depth -= 1


def _parse_node_pattern(ts: TokenStream, qs: QueryStructure) -> str:
    """Parses (name:Label1:Label2 {...}) and ensures the node exists in qs. Returns its name."""
    ts.expect("LPAREN")
    name = None
    if ts.peek_kind() == "IDENT":
        name = ts.advance().text
    labels = []
    while ts.peek_kind() == "COLON":
        ts.advance()
        labels.append(ts.expect("IDENT").text)
    if ts.peek_kind() == "LBRACE":
        _skip_brace_block(ts)
    ts.expect("RPAREN")

    if name is None:
        name = _fresh_anon("node")
    if qs.get_node(name) is None:
        qs.add_node(name, labels)
    return name


def _parse_relationship_body(ts: TokenStream) -> tuple:
    """Parses the optional [name:TYPE {...}] inside a relationship. Returns (name, type)."""
    if ts.peek_kind() != "LBRACKET":
        return None, None
    ts.advance()
    rel_name = None
    if ts.peek_kind() == "IDENT":
        rel_name = ts.advance().text
    rel_type = None
    if ts.peek_kind() == "COLON":
        ts.advance()
        rel_type = ts.expect("IDENT").text
    if ts.peek_kind() == "LBRACE":
        _skip_brace_block(ts)
    ts.expect("RBRACKET")
    return rel_name, rel_type


def _parse_relationship(ts: TokenStream) -> tuple:
    """Parses a relationship pattern. Returns (name, type, direction) where direction is
    'OUTGOING', 'INCOMING', or 'BOTH'."""
    kind = ts.peek_kind()
    if kind == "ARROW_L":
        ts.advance()
        rel_name, rel_type = _parse_relationship_body(ts)
        ts.expect("DASH")
        return rel_name, rel_type, "INCOMING"
    if kind == "DASH":
        ts.advance()
        rel_name, rel_type = _parse_relationship_body(ts)
        end_kind = ts.peek_kind()
        if end_kind == "ARROW_R":
            ts.advance()
            return rel_name, rel_type, "OUTGOING"
        if end_kind == "DASH":
            ts.advance()
            return rel_name, rel_type, "BOTH"
        raise CypherParseError(f"Malformed relationship, expected '-' or '->' but found {ts.peek()}")
    raise CypherParseError(f"Expected relationship pattern but found {ts.peek()}")


def _add_relationship(qs: QueryStructure, rel_name, rel_type, direction, left_name, right_name) -> None:
    if rel_name is None:
        rel_name = _fresh_anon("edge")
    rel_type = rel_type or ""

    if direction == "OUTGOING":
        qs.add_edge(rel_name, left_name, right_name, rel_type)
        qs.add_edge_to_node_out_edges(left_name, rel_name)
        qs.add_edge_to_node_in_edges(right_name, rel_name)
    elif direction == "INCOMING":
        qs.add_edge(rel_name, right_name, left_name, rel_type)
        qs.add_edge_to_node_out_edges(right_name, rel_name)
        qs.add_edge_to_node_in_edges(left_name, rel_name)
    else:  # BOTH
        qs.add_edge(rel_name, left_name, right_name, rel_type)
        qs.add_edge_to_node_in_out_edges(left_name, rel_name)
        qs.add_edge_to_node_in_out_edges(right_name, rel_name)


def _parse_pattern_element(ts: TokenStream, qs: QueryStructure) -> None:
    left_name = _parse_node_pattern(ts, qs)
    while ts.peek_kind() in ("DASH", "ARROW_L"):
        rel_name, rel_type, direction = _parse_relationship(ts)
        right_name = _parse_node_pattern(ts, qs)
        _add_relationship(qs, rel_name, rel_type, direction, left_name, right_name)
        left_name = right_name


def parse_match_clause(tokens: list, qs: QueryStructure) -> None:
    ts = TokenStream(tokens)
    if not tokens:
        raise CypherParseError("Empty MATCH clause")
    _parse_pattern_element(ts, qs)
    while ts.peek_kind() == "COMMA":
        ts.advance()
        _parse_pattern_element(ts, qs)
    if ts.peek_kind() != "EOF":
        raise CypherParseError(f"Unexpected token in MATCH clause: {ts.peek()}")


# ============================================================
# WHERE CLAUSE
# ============================================================

_COMPARISON_OPS = {
    "EQ": Operator.EQUAL, "NE": Operator.NOT_EQUAL,
    "GT": Operator.GREATER_THAN, "GE": Operator.GREATER_THAN_OR_EQUAL,
    "LT": Operator.LESS_THAN, "LE": Operator.LESS_THAN_OR_EQUAL,
}


class _WhereParser:
    def __init__(self, tokens: list):
        self.ts = TokenStream(tokens)
        self.counter = 0
        self.conditions = {}

    def parse(self) -> dnf.BooleanExpression:
        expr = self._parse_or()
        if self.ts.peek_kind() != "EOF":
            raise CypherParseError(f"Unexpected token in WHERE clause: {self.ts.peek()}")
        return expr

    def _next_letter(self) -> str:
        letter = chr(ord("A") + self.counter)
        self.counter += 1
        return letter

    def _parse_or(self) -> dnf.BooleanExpression:
        left = self._parse_and()
        while self.ts.peek_kind() in ("OR", "XOR"):
            is_xor = self.ts.advance().kind == "XOR"
            right = self._parse_and()
            if is_xor:
                left = dnf.Conjunction(
                    dnf.Disjunction(left, right),
                    dnf.Negation(dnf.Conjunction(left, right)),
                )
            else:
                left = dnf.Disjunction(left, right)
        return left

    def _parse_and(self) -> dnf.BooleanExpression:
        left = self._parse_not()
        while self.ts.peek_kind() == "AND":
            self.ts.advance()
            right = self._parse_not()
            left = dnf.Conjunction(left, right)
        return left

    def _parse_not(self) -> dnf.BooleanExpression:
        if self.ts.peek_kind() == "NOT":
            self.ts.advance()
            return dnf.Negation(self._parse_not())
        if self.ts.peek_kind() == "LPAREN":
            self.ts.advance()
            expr = self._parse_or()
            self.ts.expect("RPAREN")
            return expr
        return self._parse_comparison()

    def _parse_comparison(self) -> dnf.BooleanExpression:
        node_name = self.ts.expect("IDENT").text
        self.ts.expect("DOT")
        prop_name = self.ts.expect("IDENT").text

        kind = self.ts.peek_kind()

        if kind == "IS":
            self.ts.advance()
            if self.ts.peek_kind() == "NOT":
                self.ts.advance()
                self.ts.expect("NULL")
                prop = StringProp(prop_name, Operator.IS_NOT_NULL, None)
            else:
                self.ts.expect("NULL")
                prop = StringProp(prop_name, Operator.IS_NULL, None)
            return self._record_condition(node_name, prop)

        if kind == "STARTS":
            self.ts.advance()
            self.ts.expect("WITH")
            value = self._parse_string_literal()
            return self._record_condition(node_name, StringProp.starts_with(prop_name, value))

        if kind == "ENDS":
            self.ts.advance()
            self.ts.expect("WITH")
            value = self._parse_string_literal()
            return self._record_condition(node_name, StringProp.ends_with(prop_name, value))

        if kind == "CONTAINS":
            self.ts.advance()
            value = self._parse_string_literal()
            return self._record_condition(node_name, StringProp.contains(prop_name, value))

        if kind == "IN":
            self.ts.advance()
            values = self._parse_string_list()
            return self._record_condition(node_name, StringArrayProp.in_(prop_name, values))

        if kind in _COMPARISON_OPS:
            self.ts.advance()
            operator = _COMPARISON_OPS[kind]
            value = self._parse_value()
            if isinstance(value, bool):
                raise CypherParseError("Boolean literals are not supported in comparisons")
            if isinstance(value, int):
                prop = IntegerProp(prop_name, operator, value)
            elif isinstance(value, float):
                prop = DoubleProp(prop_name, operator, value)
            else:
                prop = StringProp(prop_name, operator, value)
            return self._record_condition(node_name, prop)

        raise CypherParseError(f"Expected a comparison operator but found {self.ts.peek()}")

    def _record_condition(self, node_name: str, prop) -> dnf.Variable:
        letter = self._next_letter()
        self.conditions[letter] = (node_name, prop)
        return dnf.Variable(letter)

    def _parse_string_literal(self) -> str:
        return self.ts.expect("STRING").text

    def _parse_value(self):
        tok = self.ts.advance()
        if tok.kind == "INT":
            return int(tok.text)
        if tok.kind == "FLOAT":
            return float(tok.text)
        if tok.kind == "STRING":
            return tok.text
        if tok.kind == "TRUE":
            return True
        if tok.kind == "FALSE":
            return False
        raise CypherParseError(f"Expected a literal value but found {tok}")

    def _parse_string_list(self) -> list:
        self.ts.expect("LBRACKET")
        values = []
        if self.ts.peek_kind() != "RBRACKET":
            values.append(self._parse_string_literal())
            while self.ts.peek_kind() == "COMMA":
                self.ts.advance()
                values.append(self._parse_string_literal())
        self.ts.expect("RBRACKET")
        return values


def parse_where_clause(tokens: list) -> WhereClause:
    parser = _WhereParser(tokens)
    expr = parser.parse()
    dnf_expr = dnf.to_dnf(expr)
    return WhereClause(dnf_expr, parser.conditions)


# ============================================================
# RETURN CLAUSE
# ============================================================

def parse_return_clause(tokens: list, qs: QueryStructure) -> ReturnClause:
    ts = TokenStream(tokens)
    rc = ReturnClause()
    if not tokens:
        raise CypherParseError("Empty RETURN clause")

    def parse_item():
        var_name = ts.expect("IDENT").text
        if ts.peek_kind() == "DOT":
            ts.advance()
            prop_name = ts.expect("IDENT").text
            alias = f"{var_name}.{prop_name}"
            if ts.peek_kind() == "AS":
                ts.advance()
                alias = ts.expect("IDENT").text
            rc.add_property(alias, var_name, prop_name)
        else:
            node = qs.get_node(var_name)
            if node is not None:
                rc.add_node(var_name, node)
            edge = qs.get_edge(var_name)
            if edge is not None:
                rc.add_edge(var_name, edge)

    parse_item()
    while ts.peek_kind() == "COMMA":
        ts.advance()
        parse_item()
    if ts.peek_kind() != "EOF":
        raise CypherParseError(f"Unexpected token in RETURN clause: {ts.peek()}")
    return rc


# ============================================================
# ENTRY POINT
# ============================================================

def convert(cypher_query: str) -> QueryStructure:
    """
    Parses a Cypher-style MATCH/WHERE/RETURN query into a QueryStructure.
    Raises CypherParseError on malformed or unsupported syntax.
    """
    tokens = tokenize(cypher_query)
    clauses = _split_clauses(tokens)

    if "MATCH" not in clauses:
        raise CypherParseError("No MATCH clause found")
    if "RETURN" not in clauses:
        raise CypherParseError("No RETURN clause found")

    qs = QueryStructure()
    parse_match_clause(clauses["MATCH"], qs)

    if "WHERE" in clauses:
        qs.set_where_clause(parse_where_clause(clauses["WHERE"]))

    qs.set_return_clause(parse_return_clause(clauses["RETURN"], qs))

    return qs
