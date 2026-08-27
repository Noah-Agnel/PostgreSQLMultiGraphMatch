"""
properties.py

Port of com.properties.* (Operator, Property, IntegerProp, DoubleProp,
StringProp, IntegerArrayProp, DoubleArrayProp, StringArrayProp).
"""

from dataclasses import dataclass
from typing import Any


class Operator:
    EQUAL = "="
    NOT_EQUAL = "!="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    IN = "IN"
    NOT_IN = "NOT IN"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"
    CONTAINS = "CONTAINS"
    NOT_CONTAINS = "NOT CONTAINS"
    STARTS_WITH = "STARTS WITH"
    ENDS_WITH = "ENDS WITH"
    SOME_IN = "SOME IN"
    ARRAY_EMPTY = "IS EMPTY"
    ARRAY_NOT_EMPTY = "IS NOT EMPTY"


def _to_int(v: Any) -> int:
    if isinstance(v, bool):
        raise ValueError(f"Cannot convert {type(v)} to Int")
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        return int(v)
    raise ValueError(f"Cannot convert {type(v)} to Int")


def _to_float(v: Any) -> float:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        return float(v)
    raise ValueError(f"Cannot convert {type(v)} to Double")


def _to_str(v: Any) -> str:
    if v is None:
        return None
    return str(v)


def _to_array(v: Any, convert) -> list:
    if v is None:
        return None
    if isinstance(v, (list, tuple, set)):
        return [convert(x) for x in v]
    return [convert(v)]


@dataclass(frozen=True)
class Property:
    """Base for all typed property conditions. Subclasses implement evaluate()."""
    name: str
    operator: str
    value: Any

    def evaluate(self, actual_value: Any) -> bool:
        raise NotImplementedError

    def __str__(self) -> str:
        return f"{self.name} {self.operator} {self.value}"


@dataclass(frozen=True)
class IntegerProp(Property):
    def evaluate(self, actual_value: Any) -> bool:
        op = self.operator
        if op == Operator.IS_NULL:
            return actual_value is None
        if op == Operator.IS_NOT_NULL:
            return actual_value is not None
        if actual_value is None:
            return False  # NULL semantics: a missing property never matches any other operator
        v = _to_int(actual_value)
        if op == Operator.EQUAL:
            return v == self.value
        if op == Operator.NOT_EQUAL:
            return v != self.value
        if op == Operator.GREATER_THAN:
            return v > self.value
        if op == Operator.GREATER_THAN_OR_EQUAL:
            return v >= self.value
        if op == Operator.LESS_THAN:
            return v < self.value
        if op == Operator.LESS_THAN_OR_EQUAL:
            return v <= self.value
        return False

    @staticmethod
    def equal(name, value): return IntegerProp(name, Operator.EQUAL, value)
    @staticmethod
    def not_equal(name, value): return IntegerProp(name, Operator.NOT_EQUAL, value)
    @staticmethod
    def greater_than(name, value): return IntegerProp(name, Operator.GREATER_THAN, value)
    @staticmethod
    def greater_than_or_equal(name, value): return IntegerProp(name, Operator.GREATER_THAN_OR_EQUAL, value)
    @staticmethod
    def less_than(name, value): return IntegerProp(name, Operator.LESS_THAN, value)
    @staticmethod
    def less_than_or_equal(name, value): return IntegerProp(name, Operator.LESS_THAN_OR_EQUAL, value)
    @staticmethod
    def is_null(name): return IntegerProp(name, Operator.IS_NULL, None)
    @staticmethod
    def is_not_null(name): return IntegerProp(name, Operator.IS_NOT_NULL, None)

    def __str__(self) -> str:
        return f"{self.name} {self.operator} {self.value}"


@dataclass(frozen=True)
class DoubleProp(Property):
    def evaluate(self, actual_value: Any) -> bool:
        op = self.operator
        if op == Operator.IS_NULL:
            return actual_value is None
        if op == Operator.IS_NOT_NULL:
            return actual_value is not None
        if actual_value is None:
            return False  # NULL semantics: a missing property never matches any other operator
        v = _to_float(actual_value)
        if op == Operator.EQUAL:
            return v == self.value
        if op == Operator.NOT_EQUAL:
            return v != self.value
        if op == Operator.GREATER_THAN:
            return v > self.value
        if op == Operator.GREATER_THAN_OR_EQUAL:
            return v >= self.value
        if op == Operator.LESS_THAN:
            return v < self.value
        if op == Operator.LESS_THAN_OR_EQUAL:
            return v <= self.value
        return False

    @staticmethod
    def equal(name, value): return DoubleProp(name, Operator.EQUAL, value)
    @staticmethod
    def not_equal(name, value): return DoubleProp(name, Operator.NOT_EQUAL, value)
    @staticmethod
    def greater_than(name, value): return DoubleProp(name, Operator.GREATER_THAN, value)
    @staticmethod
    def greater_than_or_equal(name, value): return DoubleProp(name, Operator.GREATER_THAN_OR_EQUAL, value)
    @staticmethod
    def less_than(name, value): return DoubleProp(name, Operator.LESS_THAN, value)
    @staticmethod
    def less_than_or_equal(name, value): return DoubleProp(name, Operator.LESS_THAN_OR_EQUAL, value)
    @staticmethod
    def is_null(name): return DoubleProp(name, Operator.IS_NULL, None)
    @staticmethod
    def is_not_null(name): return DoubleProp(name, Operator.IS_NOT_NULL, None)

    def __str__(self) -> str:
        return f"{self.name} {self.operator} {self.value}"


@dataclass(frozen=True)
class StringProp(Property):
    def evaluate(self, actual_value: Any) -> bool:
        op = self.operator
        if op == Operator.IS_NULL:
            return actual_value is None
        if op == Operator.IS_NOT_NULL:
            return actual_value is not None
        if actual_value is None:
            return False  # NULL semantics: a missing property never matches any other operator
        v = _to_str(actual_value)
        if op == Operator.EQUAL:
            return v == self.value
        if op == Operator.NOT_EQUAL:
            return v != self.value
        if op == Operator.GREATER_THAN:
            return v > self.value
        if op == Operator.GREATER_THAN_OR_EQUAL:
            return v >= self.value
        if op == Operator.LESS_THAN:
            return v < self.value
        if op == Operator.LESS_THAN_OR_EQUAL:
            return v <= self.value
        if op == Operator.CONTAINS:
            return self.value in v
        if op == Operator.STARTS_WITH:
            return v.startswith(self.value)
        if op == Operator.ENDS_WITH:
            return v.endswith(self.value)
        if op == Operator.IN:
            return v in self.value
        if op == Operator.NOT_IN:
            return v not in self.value
        return False

    @staticmethod
    def equal(name, value): return StringProp(name, Operator.EQUAL, value)
    @staticmethod
    def not_equal(name, value): return StringProp(name, Operator.NOT_EQUAL, value)
    @staticmethod
    def greater_than(name, value): return StringProp(name, Operator.GREATER_THAN, value)
    @staticmethod
    def greater_than_or_equal(name, value): return StringProp(name, Operator.GREATER_THAN_OR_EQUAL, value)
    @staticmethod
    def less_than(name, value): return StringProp(name, Operator.LESS_THAN, value)
    @staticmethod
    def less_than_or_equal(name, value): return StringProp(name, Operator.LESS_THAN_OR_EQUAL, value)
    @staticmethod
    def contains(name, value): return StringProp(name, Operator.CONTAINS, value)
    @staticmethod
    def starts_with(name, value): return StringProp(name, Operator.STARTS_WITH, value)
    @staticmethod
    def ends_with(name, value): return StringProp(name, Operator.ENDS_WITH, value)
    @staticmethod
    def is_null(name): return StringProp(name, Operator.IS_NULL, None)
    @staticmethod
    def is_not_null(name): return StringProp(name, Operator.IS_NOT_NULL, None)

    def __str__(self) -> str:
        return f"{self.name} {self.operator} '{self.value}'"


def _array_evaluate(operator: str, array_value, value) -> bool:
    if operator == Operator.EQUAL:
        return array_value == value
    if operator == Operator.NOT_EQUAL:
        return array_value != value
    if operator == Operator.IN:
        return all(elem in value for elem in array_value)
    if operator == Operator.NOT_IN:
        return not all(elem in value for elem in array_value)
    if operator == Operator.SOME_IN:
        return any(elem in value for elem in array_value)
    if operator == Operator.CONTAINS:
        return all(elem in array_value for elem in value)
    if operator == Operator.NOT_CONTAINS:
        return not all(elem in array_value for elem in value)
    if operator == Operator.ARRAY_EMPTY:
        return len(array_value) == 0
    if operator == Operator.ARRAY_NOT_EMPTY:
        return len(array_value) > 0
    return False


@dataclass(frozen=True)
class StringArrayProp(Property):
    def evaluate(self, actual_value: Any) -> bool:
        if self.operator == Operator.IS_NULL:
            return actual_value is None
        if self.operator == Operator.IS_NOT_NULL:
            return actual_value is not None
        if actual_value is None:
            return False  # NULL semantics: a missing property never matches any other operator
        array_value = _to_array(actual_value, _to_str)
        return _array_evaluate(self.operator, array_value, self.value)

    @staticmethod
    def equal(name, value): return StringArrayProp(name, Operator.EQUAL, value)
    @staticmethod
    def not_equal(name, value): return StringArrayProp(name, Operator.NOT_EQUAL, value)
    @staticmethod
    def in_(name, values): return StringArrayProp(name, Operator.IN, values)
    @staticmethod
    def not_in(name, values): return StringArrayProp(name, Operator.NOT_IN, values)
    @staticmethod
    def some_in(name, values): return StringArrayProp(name, Operator.SOME_IN, values)
    @staticmethod
    def contains(name, values): return StringArrayProp(name, Operator.CONTAINS, values)
    @staticmethod
    def not_contains(name, values): return StringArrayProp(name, Operator.NOT_CONTAINS, values)
    @staticmethod
    def is_empty(name): return StringArrayProp(name, Operator.ARRAY_EMPTY, None)
    @staticmethod
    def is_not_empty(name): return StringArrayProp(name, Operator.ARRAY_NOT_EMPTY, None)
    @staticmethod
    def is_null(name): return StringArrayProp(name, Operator.IS_NULL, None)
    @staticmethod
    def is_not_null(name): return StringArrayProp(name, Operator.IS_NOT_NULL, None)

    def __str__(self) -> str:
        return f"{self.name} {self.operator} [{', '.join(self.value or [])}]"


@dataclass(frozen=True)
class IntegerArrayProp(Property):
    def evaluate(self, actual_value: Any) -> bool:
        if self.operator == Operator.IS_NULL:
            return actual_value is None
        if self.operator == Operator.IS_NOT_NULL:
            return actual_value is not None
        if actual_value is None:
            return False  # NULL semantics: a missing property never matches any other operator
        array_value = _to_array(actual_value, _to_int)
        return _array_evaluate(self.operator, array_value, self.value)

    @staticmethod
    def equal(name, value): return IntegerArrayProp(name, Operator.EQUAL, value)
    @staticmethod
    def not_equal(name, value): return IntegerArrayProp(name, Operator.NOT_EQUAL, value)
    @staticmethod
    def in_(name, values): return IntegerArrayProp(name, Operator.IN, values)
    @staticmethod
    def not_in(name, values): return IntegerArrayProp(name, Operator.NOT_IN, values)
    @staticmethod
    def some_in(name, values): return IntegerArrayProp(name, Operator.SOME_IN, values)
    @staticmethod
    def contains(name, values): return IntegerArrayProp(name, Operator.CONTAINS, values)
    @staticmethod
    def not_contains(name, values): return IntegerArrayProp(name, Operator.NOT_CONTAINS, values)
    @staticmethod
    def is_empty(name): return IntegerArrayProp(name, Operator.ARRAY_EMPTY, None)
    @staticmethod
    def is_not_empty(name): return IntegerArrayProp(name, Operator.ARRAY_NOT_EMPTY, None)
    @staticmethod
    def is_null(name): return IntegerArrayProp(name, Operator.IS_NULL, None)
    @staticmethod
    def is_not_null(name): return IntegerArrayProp(name, Operator.IS_NOT_NULL, None)

    def __str__(self) -> str:
        return f"{self.name} {self.operator} [{', '.join(str(v) for v in (self.value or []))}]"


@dataclass(frozen=True)
class DoubleArrayProp(Property):
    def evaluate(self, actual_value: Any) -> bool:
        if self.operator == Operator.IS_NULL:
            return actual_value is None
        if self.operator == Operator.IS_NOT_NULL:
            return actual_value is not None
        if actual_value is None:
            return False  # NULL semantics: a missing property never matches any other operator
        array_value = _to_array(actual_value, _to_float)
        return _array_evaluate(self.operator, array_value, self.value)

    @staticmethod
    def equal(name, value): return DoubleArrayProp(name, Operator.EQUAL, value)
    @staticmethod
    def not_equal(name, value): return DoubleArrayProp(name, Operator.NOT_EQUAL, value)
    @staticmethod
    def in_(name, values): return DoubleArrayProp(name, Operator.IN, values)
    @staticmethod
    def not_in(name, values): return DoubleArrayProp(name, Operator.NOT_IN, values)
    @staticmethod
    def some_in(name, values): return DoubleArrayProp(name, Operator.SOME_IN, values)
    @staticmethod
    def contains(name, values): return DoubleArrayProp(name, Operator.CONTAINS, values)
    @staticmethod
    def not_contains(name, values): return DoubleArrayProp(name, Operator.NOT_CONTAINS, values)
    @staticmethod
    def is_empty(name): return DoubleArrayProp(name, Operator.ARRAY_EMPTY, None)
    @staticmethod
    def is_not_empty(name): return DoubleArrayProp(name, Operator.ARRAY_NOT_EMPTY, None)
    @staticmethod
    def is_null(name): return DoubleArrayProp(name, Operator.IS_NULL, None)
    @staticmethod
    def is_not_null(name): return DoubleArrayProp(name, Operator.IS_NOT_NULL, None)

    def __str__(self) -> str:
        return f"{self.name} {self.operator} [{', '.join(str(v) for v in (self.value or []))}]"
