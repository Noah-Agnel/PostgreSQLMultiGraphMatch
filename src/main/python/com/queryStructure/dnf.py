"""
dnf.py

Port of dnf/BooleanExpression.scala + BooleanExpressionParser.scala +
DNFTransformer.scala: an AST for boolean expressions, a recursive-descent
parser for them, and the push-negations / distribute-or / simplify
algorithm that converts any expression into Disjunctive Normal Form.
"""

import re
from dataclasses import dataclass


# ============================================================
# AST
# ============================================================

class BooleanExpression:
    def evaluate(self, assignment: dict) -> bool:
        raise NotImplementedError

    @property
    def variables(self) -> set:
        raise NotImplementedError


@dataclass(frozen=True)
class Variable(BooleanExpression):
    name: str

    def evaluate(self, assignment: dict) -> bool:
        if self.name not in assignment:
            raise ValueError(f"Variable {self.name} not found in assignment")
        return assignment[self.name]

    @property
    def variables(self) -> set:
        return {self.name}

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Constant(BooleanExpression):
    value: bool

    def evaluate(self, assignment: dict) -> bool:
        return self.value

    @property
    def variables(self) -> set:
        return set()

    def __str__(self) -> str:
        return "TRUE" if self.value else "FALSE"


TRUE = Constant(True)
FALSE = Constant(False)


@dataclass(frozen=True)
class Negation(BooleanExpression):
    operand: BooleanExpression

    def evaluate(self, assignment: dict) -> bool:
        return not self.operand.evaluate(assignment)

    @property
    def variables(self) -> set:
        return self.operand.variables

    def __str__(self) -> str:
        return f"¬({self.operand})"


@dataclass(frozen=True)
class Conjunction(BooleanExpression):
    left: BooleanExpression
    right: BooleanExpression

    def evaluate(self, assignment: dict) -> bool:
        return self.left.evaluate(assignment) and self.right.evaluate(assignment)

    @property
    def variables(self) -> set:
        return self.left.variables | self.right.variables

    def __str__(self) -> str:
        return f"({self.left} ∧ {self.right})"


@dataclass(frozen=True)
class Disjunction(BooleanExpression):
    left: BooleanExpression
    right: BooleanExpression

    def evaluate(self, assignment: dict) -> bool:
        return self.left.evaluate(assignment) or self.right.evaluate(assignment)

    @property
    def variables(self) -> set:
        return self.left.variables | self.right.variables

    def __str__(self) -> str:
        return f"({self.left} ∨ {self.right})"


# ============================================================
# PARSER
# ============================================================

_TOKEN_RE = re.compile(r"""
    \s*(?:
        (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<op>[|&!~]|∨|∧|¬)
      | (?P<word>[a-zA-Z_][a-zA-Z0-9_]*)
    )
""", re.VERBOSE)

_OR_WORDS = {"or", "OR"}
_AND_WORDS = {"and", "AND"}
_NOT_WORDS = {"not", "NOT"}
_TRUE_WORDS = {"TRUE", "true", "T", "1"}
_FALSE_WORDS = {"FALSE", "false", "F", "0"}


class DNFParseError(ValueError):
    pass


class _Tokenizer:
    def __init__(self, text: str):
        self.tokens = []
        pos = 0
        while pos < len(text):
            m = _TOKEN_RE.match(text, pos)
            if not m or m.end() == pos:
                if text[pos:].strip() == "":
                    break
                raise DNFParseError(f"Unexpected character at position {pos}: {text[pos:pos + 10]!r}")
            pos = m.end()
            kind = m.lastgroup
            value = m.group(kind)
            self.tokens.append((kind, value))
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def advance(self):
        tok = self.peek()
        self.i += 1
        return tok


def parse_boolean_expression(text: str) -> BooleanExpression:
    """
    Parses a boolean expression string, e.g. "A & (B | !C)".
    Supported: variables (identifiers), TRUE/FALSE/T/F/1/0, operators
    !/~/¬ (NOT), &/∧ (AND), |/∨ (OR), and parentheses. Raises
    DNFParseError on malformed input.
    """
    tok = _Tokenizer(text)
    expr = _parse_or(tok)
    if tok.peek() != (None, None):
        raise DNFParseError(f"Unexpected trailing token: {tok.peek()}")
    return expr


def _parse_or(tok: _Tokenizer) -> BooleanExpression:
    left = _parse_and(tok)
    while True:
        kind, value = tok.peek()
        if (kind == "op" and value in ("|", "∨")) or (kind == "word" and value in _OR_WORDS):
            tok.advance()
            right = _parse_and(tok)
            left = Disjunction(left, right)
        else:
            return left


def _parse_and(tok: _Tokenizer) -> BooleanExpression:
    left = _parse_not(tok)
    while True:
        kind, value = tok.peek()
        if (kind == "op" and value in ("&", "∧")) or (kind == "word" and value in _AND_WORDS):
            tok.advance()
            right = _parse_not(tok)
            left = Conjunction(left, right)
        else:
            return left


def _parse_not(tok: _Tokenizer) -> BooleanExpression:
    kind, value = tok.peek()
    if (kind == "op" and value in ("!", "~", "¬")) or (kind == "word" and value in _NOT_WORDS):
        tok.advance()
        return Negation(_parse_not(tok))
    return _parse_atom(tok)


def _parse_atom(tok: _Tokenizer) -> BooleanExpression:
    kind, value = tok.advance()
    if kind == "lparen":
        expr = _parse_or(tok)
        kind2, _ = tok.advance()
        if kind2 != "rparen":
            raise DNFParseError("Expected ')'")
        return expr
    if kind == "word":
        if value in _TRUE_WORDS:
            return TRUE
        if value in _FALSE_WORDS:
            return FALSE
        return Variable(value)
    raise DNFParseError(f"Expected variable, constant, or '(' but found {(kind, value)}")


# ============================================================
# DNF TRANSFORMER
# ============================================================

def _push_negations_inward(expr: BooleanExpression) -> BooleanExpression:
    if isinstance(expr, (Variable, Constant)):
        return expr
    if isinstance(expr, Conjunction):
        return Conjunction(_push_negations_inward(expr.left), _push_negations_inward(expr.right))
    if isinstance(expr, Disjunction):
        return Disjunction(_push_negations_inward(expr.left), _push_negations_inward(expr.right))
    if isinstance(expr, Negation):
        return _push_negation_inward(expr.operand)
    raise TypeError(f"Unexpected expression type: {type(expr)}")


def _push_negation_inward(expr: BooleanExpression) -> BooleanExpression:
    if isinstance(expr, Variable):
        return Negation(expr)
    if isinstance(expr, Constant):
        return Constant(not expr.value)
    if isinstance(expr, Negation):
        return _push_negations_inward(expr.operand)  # double negation elimination
    if isinstance(expr, Conjunction):
        return Disjunction(_push_negation_inward(expr.left), _push_negation_inward(expr.right))
    if isinstance(expr, Disjunction):
        return Conjunction(_push_negation_inward(expr.left), _push_negation_inward(expr.right))
    raise TypeError(f"Unexpected expression type: {type(expr)}")


def _distribute_and(left: BooleanExpression, right: BooleanExpression) -> BooleanExpression:
    """A ∧ (B ∨ C) -> (A∧B) ∨ (A∧C), recursively -- the actual DNF distribution rule."""
    if isinstance(left, Disjunction):
        return Disjunction(_distribute_and(left.left, right), _distribute_and(left.right, right))
    if isinstance(right, Disjunction):
        return Disjunction(_distribute_and(left, right.left), _distribute_and(left, right.right))
    return Conjunction(left, right)


def _distribute_and_over_or(expr: BooleanExpression) -> BooleanExpression:
    if isinstance(expr, (Variable, Constant)):
        return expr
    if isinstance(expr, Negation):
        return Negation(_distribute_and_over_or(expr.operand))
    if isinstance(expr, Disjunction):
        return Disjunction(_distribute_and_over_or(expr.left), _distribute_and_over_or(expr.right))
    if isinstance(expr, Conjunction):
        return _distribute_and(_distribute_and_over_or(expr.left), _distribute_and_over_or(expr.right))
    raise TypeError(f"Unexpected expression type: {type(expr)}")


def _simplify_once(expr: BooleanExpression) -> BooleanExpression:
    if isinstance(expr, (Variable, Constant)):
        return expr
    if isinstance(expr, Negation):
        inner = _simplify_once(expr.operand)
        return Constant(not inner.value) if isinstance(inner, Constant) else Negation(inner)
    if isinstance(expr, Conjunction):
        l, r = _simplify_once(expr.left), _simplify_once(expr.right)
        if isinstance(l, Constant) and l.value:
            return r
        if isinstance(r, Constant) and r.value:
            return l
        if isinstance(l, Constant) and not l.value:
            return FALSE
        if isinstance(r, Constant) and not r.value:
            return FALSE
        if l == r:
            return l
        if isinstance(r, Negation) and r.operand == l:
            return FALSE
        if isinstance(l, Negation) and l.operand == r:
            return FALSE
        return Conjunction(l, r)
    if isinstance(expr, Disjunction):
        l, r = _simplify_once(expr.left), _simplify_once(expr.right)
        if isinstance(l, Constant) and not l.value:
            return r
        if isinstance(r, Constant) and not r.value:
            return l
        if isinstance(l, Constant) and l.value:
            return TRUE
        if isinstance(r, Constant) and r.value:
            return TRUE
        if l == r:
            return l
        if isinstance(r, Negation) and r.operand == l:
            return TRUE
        if isinstance(l, Negation) and l.operand == r:
            return TRUE
        return Disjunction(l, r)
    raise TypeError(f"Unexpected expression type: {type(expr)}")


def _simplify(expr: BooleanExpression) -> BooleanExpression:
    simplified = _simplify_once(expr)
    return simplified if simplified == expr else _simplify(simplified)


def to_dnf(expr: BooleanExpression) -> BooleanExpression:
    """Transforms a boolean expression into Disjunctive Normal Form."""
    return _simplify(_distribute_and_over_or(_push_negations_inward(expr)))


def _is_literal(expr: BooleanExpression) -> bool:
    return isinstance(expr, (Variable, Constant)) or (isinstance(expr, Negation) and isinstance(expr.operand, Variable))


def _is_conjunction_of_literals(expr: BooleanExpression) -> bool:
    if _is_literal(expr):
        return True
    if isinstance(expr, Conjunction):
        return _is_conjunction_of_literals(expr.left) and _is_conjunction_of_literals(expr.right)
    return False


def is_dnf(expr: BooleanExpression) -> bool:
    if _is_literal(expr) or _is_conjunction_of_literals(expr):
        return True
    if isinstance(expr, Disjunction):
        return _is_conjunction_of_literals(expr.left) and is_dnf(expr.right)
    return False
