import hashlib
import json
from dataclasses import dataclass
from datetime    import datetime


# ============================================================
# DATE PARSING
# ============================================================
# ICIJ dates arrive as "DD-MON-YYYY" (e.g. "23-MAR-2006") or empty string
# when unknown/not applicable. This normalises both into either an
# ISO-8601 string or None.

def parse_icij_date(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d-%b-%Y").isoformat()
    except ValueError:
        return None


def earliest_date(*raw_dates: str) -> str | None:
    """
    Given several raw ICIJ date strings (e.g. inactivation_date,
    struck_off_date, dorm_date), returns the earliest one that parses,
    or None if none of them do. Used to pick a single "to" date for
    Entity dynamic props out of three overlapping end-date columns.
    """
    parsed = [parse_icij_date(d) for d in raw_dates]
    parsed = [d for d in parsed if d is not None]
    return min(parsed) if parsed else None


def split_multivalue(raw: str) -> list[str]:
    """
    ICIJ occasionally semicolon-delimits country_codes/countries for
    entities tied to multiple jurisdictions. Splits defensively; returns
    a single-element list for the common single-value case.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(";") if part.strip()]


# ============================================================
# NODE MODELS
# ============================================================
# Unlike Enron's Person (deduplicated by email, assigned a fresh
# sequential id), Panama Papers node types reuse ICIJ's own node_id
# directly: it is already globally unique across Entities, Officers,
# Intermediaries, and Addresses, and all_edges.csv references these
# exact ids. Reassigning ids would require a translation table for
# no benefit.

@dataclass
class Entity:
    """
    Represents an offshore Entity (company, trust, or fund).

    Dynamic props (the only node type carrying real temporal info):
        status  : from incorporation_date, to earliest of
                  inactivation_date / struck_off_date / dorm_date
    """
    def __init__(self, row: dict):
        self.labels           = ["Entity"]
        self.id                = int(row["node_id"])
        self.name              = row.get("name", "").strip()
        self.original_name      = row.get("original_name", "").strip()
        self.former_name        = row.get("former_name", "").strip()
        self.jurisdiction       = row.get("jurisdiction", "").strip()
        self.jurisdiction_desc  = row.get("jurisdiction_description", "").strip()
        self.company_type       = row.get("company_type", "").strip()
        self.address            = row.get("address", "").strip()
        self.internal_id        = row.get("internal_id", "").strip()
        self.service_provider   = row.get("service_provider", "").strip()
        self.ibcRUC             = row.get("ibcRUC", "").strip()
        self.country_codes      = split_multivalue(row.get("country_codes", ""))
        self.countries          = split_multivalue(row.get("countries", ""))
        self.note               = row.get("note", "").strip()
        self.source_id          = row.get("sourceID", "").strip()

        # raw dates kept only long enough to compute dynamic props;
        # not emitted as static props themselves
        self._incorporation_date_raw = row.get("incorporation_date", "")
        self._inactivation_date_raw  = row.get("inactivation_date", "")
        self._struck_off_date_raw    = row.get("struck_off_date", "")
        self._dorm_date_raw          = row.get("dorm_date", "")
        self.status                  = row.get("status", "").strip()

    def get_id(self) -> int:
        return self.id

    def dynamic_status_period(self) -> tuple[str | None, str | None]:
        """Returns (from_date, to_date) ISO strings for the status dynamic prop."""
        frm = parse_icij_date(self._incorporation_date_raw)
        to  = earliest_date(
            self._inactivation_date_raw,
            self._struck_off_date_raw,
            self._dorm_date_raw,
        )
        return frm, to


@dataclass
class Officer:
    """Represents an Officer (person or company playing a role in an entity). Fully static."""
    def __init__(self, row: dict):
        self.labels        = ["Officer"]
        self.id             = int(row["node_id"])
        self.name           = row.get("name", "").strip()
        self.icij_id        = row.get("icij_id", "").strip()
        self.country_codes  = split_multivalue(row.get("country_codes", ""))
        self.countries      = split_multivalue(row.get("countries", ""))
        self.note           = row.get("note", "").strip()
        self.source_id      = row.get("sourceID", "").strip()

    def get_id(self) -> int:
        return self.id


@dataclass
class Intermediary:
    """Represents an Intermediary (offshore service go-between). Static, with a status snapshot."""
    def __init__(self, row: dict):
        self.labels        = ["Intermediary"]
        self.id             = int(row["node_id"])
        self.name           = row.get("name", "").strip()
        self.internal_id    = row.get("internal_id", "").strip()
        self.address        = row.get("address", "").strip()
        self.country_codes  = split_multivalue(row.get("country_codes", ""))
        self.countries      = split_multivalue(row.get("countries", ""))
        self.status         = row.get("status", "").strip()
        self.note           = row.get("note", "").strip()
        self.source_id      = row.get("sourceID", "").strip()

    def get_id(self) -> int:
        return self.id


@dataclass
class Address:
    """Represents an Address. Fully static."""
    def __init__(self, row: dict):
        self.labels        = ["Address"]
        self.id             = int(row["node_id"])
        self.address        = row.get("address", "").strip()
        self.icij_id        = row.get("icij_id", "").strip()
        self.country_codes  = split_multivalue(row.get("country_codes", ""))
        self.countries      = split_multivalue(row.get("countries", ""))
        self.note           = row.get("note", "").strip()
        self.source_id      = row.get("sourceID", "").strip()

    def get_id(self) -> int:
        return self.id


# ============================================================
# NODES MANAGING
# ============================================================

@dataclass
class NodesManaging:
    """
    Tracks Entity, Officer, Intermediary, and Address nodes.

    Unlike Enron's NodesManaging, no id-assignment or dedup-by-content
    registry is needed: ICIJ node_ids are already unique per row, and
    each CSV is read exactly once per pipeline run.
    """
    def __init__(self):
        self.nodes: dict[str, list] = {
            "entity"       : [],
            "officer"      : [],
            "intermediary" : [],
            "address"      : [],
        }
        self._seen_ids: set[int] = set()

    def reset_nodes(self):
        self.nodes = {"entity": [], "officer": [], "intermediary": [], "address": []}

    def _add(self, node_type: str, node) -> int | None:
        node_id = node.get_id()
        if node_id in self._seen_ids:
            return node_id
        self._seen_ids.add(node_id)
        self.nodes[node_type].append(node)
        return node_id

    def add_entity(self, entity: Entity) -> int | None:
        return self._add("entity", entity)

    def add_officer(self, officer: Officer) -> int | None:
        return self._add("officer", officer)

    def add_intermediary(self, intermediary: Intermediary) -> int | None:
        return self._add("intermediary", intermediary)

    def add_address(self, address: Address) -> int | None:
        return self._add("address", address)


# ============================================================
# EDGES MANAGING
# ============================================================

@dataclass
class EdgesManaging:
    """
    Tracks edges from all_edges.csv: node_1 -[rel_type]-> node_2,
    optionally carrying a start_date/end_date pair as dynamic props.

    Unlike Enron edges (one row per message reaching one recipient,
    deduplicated by src+dst+type+timestamp), all_edges.csv rows have
    no natural per-row uniqueness beyond the row content itself, so
    the same hash-based dedup strategy is reused, extended to include
    start_date/end_date in the hash payload.
    """
    def __init__(self):
        self.edges: list[dict] = []
        self._seen: set[str]   = set()

    def reset_edges(self):
        self.edges = []

    def add_edge(self, src_id: int, dst_id: int, rel_type: str,
                 start_date_raw: str = "", end_date_raw: str = ""):
        if src_id is None or dst_id is None:
            return
        if src_id == dst_id:
            return

        start_date = parse_icij_date(start_date_raw)
        end_date   = parse_icij_date(end_date_raw)

        payload = {
            "src": src_id, "dst": dst_id, "rel_type": rel_type,
            "start_date": start_date, "end_date": end_date,
        }
        edge_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        if edge_hash in self._seen:
            return
        self._seen.add(edge_hash)

        edge = {
            "edge_id"   : edge_hash,
            "src"       : src_id,
            "dst"       : dst_id,
            "type"      : rel_type,
            "start_date": start_date,   # None if not present on this row
            "end_date"  : end_date,     # None if not present on this row
        }
        self.edges.append(edge)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def entity_from_row(row: dict, node_manager: NodesManaging) -> int | None:
    return node_manager.add_entity(Entity(row))

def officer_from_row(row: dict, node_manager: NodesManaging) -> int | None:
    return node_manager.add_officer(Officer(row))

def intermediary_from_row(row: dict, node_manager: NodesManaging) -> int | None:
    return node_manager.add_intermediary(Intermediary(row))

def address_from_row(row: dict, node_manager: NodesManaging) -> int | None:
    return node_manager.add_address(Address(row))

def edge_from_row(row: dict, edge_manager: EdgesManaging):
    """
    Converts one all_edges.csv row into an edge.
    node_1/node_2 reference ICIJ node_ids directly across whichever
    node type they belong to (Entity/Officer/Intermediary/Address) —
    the edge itself doesn't need to know which type either end is.
    """
    src_id = int(row["node_1"]) if row.get("node_1") else None
    dst_id = int(row["node_2"]) if row.get("node_2") else None
    rel_type = row.get("rel_type", "").strip()

    edge_manager.add_edge(
        src_id, dst_id, rel_type,
        start_date_raw=row.get("start_date", ""),
        end_date_raw=row.get("end_date", ""),
    )
