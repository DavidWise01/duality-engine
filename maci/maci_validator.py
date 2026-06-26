#!/usr/bin/env python3
"""
maci_validator.py — MACI v0.1 message-protocol validator.

MACI = Machine Artfully Crafted Intelligence.
The machine-to-machine member of the ACI family. No human in the loop,
so no case convention: authority is an explicit field, not typography.

A .maci file is JSON Lines: one message object per line. The validator
checks PROTOCOL soundness, not prose:

  - every ref points to a real, earlier message
  - every DECISION references at least one PROPOSAL/QUESTION
  - no agent exercises authority it was not granted or delegated
  - the reply/decision DAG is acyclic
  - roles and transitions are legal
  - the stream is causally ordered (no message refs the future)

Output: JSON ValidationResult (deterministic, hashable).

Author: David Lee Wise / Bridge-Burners LLC
"""

from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Set, Tuple
import json, sys, argparse, hashlib

# ═══════════════════════════════════════════════════════════════════════
# SCHEMA
# ═══════════════════════════════════════════════════════════════════════

ROLES = {
    "COMMAND",    # authoritative instruction        (was: ! human)
    "PROPOSAL",   # advisory suggestion              (was: lowercase ai)
    "QUESTION",   # request for info/decision        (was: ?)
    "EVIDENCE",   # observed fact / result           (was: >)
    "DECISION",   # approve/reject a prior message   (M2M-only)
    "DELEGATE",   # transfer authority               (M2M-only)
    "CODE",       # executable artifact
}

AUTHORITY = {"sovereign", "delegated", "advisory", "observer"}
STATUS = {None, "pending", "approved", "rejected", "executed", "superseded"}

# which roles MAY carry which authority by default
ROLE_MIN_AUTHORITY = {
    "COMMAND":  {"sovereign", "delegated"},   # commands require real authority
    "DECISION": {"sovereign", "delegated"},   # only authority can decide
    "DELEGATE": {"sovereign", "delegated"},   # only authority can delegate
    "PROPOSAL": {"sovereign", "delegated", "advisory"},
    "QUESTION": {"sovereign", "delegated", "advisory", "observer"},
    "EVIDENCE": {"sovereign", "delegated", "advisory", "observer"},
    "CODE":     {"sovereign", "delegated", "advisory"},
}

REQUIRED_FIELDS = {"maci", "id", "from", "role", "content"}


@dataclass
class Message:
    maci: str
    id: str
    from_agent: str
    role: str
    content: str
    ts: Optional[str] = None
    refs: List[str] = field(default_factory=list)
    authority: Optional[str] = None
    status: Optional[str] = None
    meta: dict = field(default_factory=dict)
    line: int = 0

    @staticmethod
    def from_obj(obj: dict, line: int) -> Tuple[Optional["Message"], List[str]]:
        errs = []
        missing = REQUIRED_FIELDS - set(obj.keys())
        if missing:
            errs.append(f"L{line}:MISSING_FIELDS:{','.join(sorted(missing))}")
            return None, errs
        m = Message(
            maci=str(obj["maci"]),
            id=str(obj["id"]),
            from_agent=str(obj["from"]),
            role=str(obj["role"]),
            content=str(obj["content"]),
            ts=obj.get("ts"),
            refs=list(obj.get("refs", [])),
            authority=obj.get("authority"),
            status=obj.get("status"),
            meta=obj.get("meta", {}),
            line=line,
        )
        return m, errs


@dataclass
class ValidationResult:
    ok: bool
    message_count: int
    agents: List[str]
    roles: Dict[str, int]
    chains: List[List[str]]      # resolved decision chains (root -> ... -> leaf)
    cycles: List[List[str]]
    delegations: List[dict]      # who delegated what authority to whom
    errors: List[str]
    warnings: List[str]


# ═══════════════════════════════════════════════════════════════════════
# VALIDATION PASSES
# ═══════════════════════════════════════════════════════════════════════

def parse_stream(text: str) -> Tuple[List[Message], List[str]]:
    messages, errors = [], []
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("//") or s.startswith("#"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            errors.append(f"L{i}:INVALID_JSON:{e.msg}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"L{i}:NOT_AN_OBJECT")
            continue
        m, errs = Message.from_obj(obj, i)
        errors.extend(errs)
        if m:
            messages.append(m)
    return messages, errors


def validate(messages: List[Message]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    index: Dict[str, Message] = {}
    order: Dict[str, int] = {}     # id -> position in stream
    agents: Set[str] = set()
    roles: Dict[str, int] = {}

    # ── pass 1: index, uniqueness, field legality ──────────────────────
    for pos, m in enumerate(messages):
        if m.id in index:
            errors.append(f"L{m.line}:DUPLICATE_ID:{m.id}")
            continue
        index[m.id] = m
        order[m.id] = pos
        agents.add(m.from_agent)
        roles[m.role] = roles.get(m.role, 0) + 1

        if m.role not in ROLES:
            errors.append(f"L{m.line}:INVALID_ROLE:{m.role}")
        if m.authority is not None and m.authority not in AUTHORITY:
            errors.append(f"L{m.line}:INVALID_AUTHORITY:{m.authority}")
        if m.status not in STATUS:
            errors.append(f"L{m.line}:INVALID_STATUS:{m.status}")
        if not m.content.strip():
            errors.append(f"L{m.line}:EMPTY_CONTENT:{m.id}")

    # ── pass 2: ref integrity + causal ordering ────────────────────────
    for m in messages:
        for r in m.refs:
            if r not in index:
                errors.append(f"L{m.line}:REF_NOT_FOUND:{m.id}->{r}")
            elif order.get(r, 1e9) >= order.get(m.id, -1):
                # a message may only reference EARLIER messages (causal stream)
                errors.append(f"L{m.line}:FORWARD_REF:{m.id}->{r}")

    # ── pass 3: role-specific protocol rules ───────────────────────────
    for m in messages:
        if m.role == "DECISION":
            if not m.refs:
                errors.append(f"L{m.line}:DECISION_WITHOUT_REFS:{m.id}")
            else:
                kinds = {index[r].role for r in m.refs if r in index}
                if not (kinds & {"PROPOSAL", "QUESTION"}):
                    errors.append(f"L{m.line}:DECISION_REFS_NO_PROPOSAL_OR_QUESTION:{m.id}")
            if m.status not in {"approved", "rejected"}:
                errors.append(f"L{m.line}:DECISION_BAD_STATUS:{m.id}:{m.status}")

        if m.role == "DELEGATE":
            if not m.content.strip():
                errors.append(f"L{m.line}:DELEGATE_NO_SCOPE:{m.id}")
            if not m.meta.get("to"):
                errors.append(f"L{m.line}:DELEGATE_NO_TARGET:{m.id} (meta.to required)")

    # ── pass 4: authority model ────────────────────────────────────────
    # an agent's standing authority = max it was granted via DELEGATE, or its
    # self-declared authority if sovereign. delegated authority must trace to
    # a sovereign source.
    delegations: List[dict] = []
    granted: Dict[str, str] = {}   # agent -> highest authority currently held

    for m in messages:
        # record delegations
        if m.role == "DELEGATE":
            target = m.meta.get("to")
            scope = m.content.strip()
            # the delegator must itself hold sovereign or delegated authority
            delegator_auth = m.authority or granted.get(m.from_agent)
            if delegator_auth not in {"sovereign", "delegated"}:
                errors.append(f"L{m.line}:DELEGATE_WITHOUT_AUTHORITY:{m.from_agent}")
            else:
                granted[target] = "delegated"
                delegations.append({
                    "from": m.from_agent, "to": target,
                    "scope": scope, "via": m.id,
                    "source_authority": delegator_auth,
                })

        # check that authority-bearing roles are backed
        if m.role in {"COMMAND", "DECISION", "DELEGATE"}:
            claimed = m.authority or granted.get(m.from_agent)
            allowed = ROLE_MIN_AUTHORITY.get(m.role, set())
            if claimed not in allowed:
                errors.append(
                    f"L{m.line}:INSUFFICIENT_AUTHORITY:{m.id}:"
                    f"{m.role} by {m.from_agent} needs {sorted(allowed)}, "
                    f"has {claimed or 'none'}")

    # ── pass 5: decision-chain DAG + cycle detection ───────────────────
    graph: Dict[str, List[str]] = {m.id: list(m.refs) for m in messages if m.id in index}
    cycles = detect_cycles(graph)
    for c in cycles:
        errors.append("CHAIN_CYCLE:" + "->".join(c))

    # ── pass 6: resolved chains (root COMMAND/QUESTION -> leaf) ─────────
    chains = build_chains(messages, index, order)

    # ── warnings: open questions, unactioned proposals ─────────────────
    answered: Set[str] = set()
    for m in messages:
        if m.role in {"DECISION", "EVIDENCE"}:
            answered.update(m.refs)
    for m in messages:
        if m.role == "QUESTION" and m.id not in answered:
            warnings.append(f"L{m.line}:OPEN_QUESTION:{m.id}")
        if m.role == "PROPOSAL" and m.id not in answered:
            warnings.append(f"L{m.line}:UNACTIONED_PROPOSAL:{m.id}")

    return ValidationResult(
        ok=not errors,
        message_count=len([m for m in messages if m.id in index]),
        agents=sorted(agents),
        roles=dict(sorted(roles.items())),
        chains=chains,
        cycles=cycles,
        delegations=delegations,
        errors=unique(errors),
        warnings=unique(warnings),
    )


def detect_cycles(graph: Dict[str, List[str]]) -> List[List[str]]:
    cycles, visiting, visited = [], [], set()

    def dfs(n):
        if n in visiting:
            i = visiting.index(n)
            cycles.append(visiting[i:] + [n])
            return
        if n in visited or n not in graph:
            return
        visiting.append(n)
        for nxt in graph.get(n, []):
            dfs(nxt)
        visiting.pop()
        visited.add(n)

    for n in list(graph):
        dfs(n)
    seen, out = set(), []
    for c in cycles:
        k = "->".join(c)
        if k not in seen:
            seen.add(k); out.append(c)
    return out


def build_chains(messages, index, order) -> List[List[str]]:
    """Resolve each leaf back to its root via refs; emit root->...->leaf paths."""
    referenced: Set[str] = set()
    for m in messages:
        referenced.update(m.refs)
    leaves = [m.id for m in messages if m.id in index and m.id not in referenced]

    chains = []
    for leaf in leaves:
        # walk back along first ref to a root (no refs)
        path = [leaf]
        cur = index[leaf]
        guard = 0
        while cur.refs and guard < 1000:
            nxt = cur.refs[0]
            if nxt not in index:
                break
            path.append(nxt)
            cur = index[nxt]
            guard += 1
        chains.append(list(reversed(path)))
    return sorted(chains, key=lambda c: (c[0], len(c)))


def unique(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x); out.append(x)
    return out


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main(argv=None):
    p = argparse.ArgumentParser(description="MACI v0.1 message-protocol validator")
    p.add_argument("file", help="path to a .maci (JSONL) file, or - for stdin")
    p.add_argument("--strict", action="store_true", help="warnings become errors")
    args = p.parse_args(argv)

    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()

    messages, parse_errors = parse_stream(text)
    result = validate(messages)
    # parse errors are hard failures — merge them AND re-derive ok
    result.errors = unique(parse_errors + result.errors)
    result.ok = not result.errors
    if args.strict and result.warnings:
        result.errors = unique(result.errors + [f"STRICT:{w}" for w in result.warnings])
        result.ok = not result.errors

    out = asdict(result)
    out["result_hash"] = hashlib.sha256(
        json.dumps(out, sort_keys=True).encode()).hexdigest()[:16]
    print(json.dumps(out, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
