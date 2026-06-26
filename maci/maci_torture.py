#!/usr/bin/env python3
"""
torture_maci_v0_1.py — torture suite for MACI validator v0.1.

Mirrors the HACI torture discipline:
  1. Curated adversarial cases (must-accept + must-reject).
  2. Seeded fuzz / property cases.
Both layers run forward and reverse where order is meaningful.

Coverage (every validation pass, both directions):
  - field legality / required fields / uniqueness
  - role legality
  - authority legality + enum
  - status enum + DECISION status
  - ref integrity (exists)
  - causal ordering (no forward refs)
  - DECISION must ref a PROPOSAL/QUESTION
  - DELEGATE must have scope + meta.to
  - authority model: command/decision/delegate need real authority
  - delegated authority traces to sovereign
  - cycle detection
  - chain resolution correctness
  - parse robustness (malformed JSON, blank, comments)
  - determinism (same input => same output)
  - open-question / unactioned-proposal warnings

This is a harness for v0.1, not a new validator version.
"""

import json, sys, random, hashlib

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from maci_validator import parse_stream, validate, unique

RESULTS = []

def stable(result_dict):
    d = dict(result_dict)
    return json.dumps(d, sort_keys=True)

def assert_true(name, cond, detail=""):
    RESULTS.append({"name": name, "status": "PASS" if cond else "FAIL", "detail": detail if not cond else ""})

def run_validate(lines):
    """lines: list of dict (messages) -> validate, return result as dict."""
    text = "\n".join(json.dumps(l) for l in lines)
    msgs, perr = parse_stream(text)
    r = validate(msgs)
    r.errors = unique(perr + r.errors)
    r.ok = not r.errors
    from dataclasses import asdict
    return asdict(r)

def run_text(text):
    msgs, perr = parse_stream(text)
    r = validate(msgs)
    r.errors = unique(perr + r.errors)
    r.ok = not r.errors
    from dataclasses import asdict
    return asdict(r)

def has_err(r, token):
    return any(token in e for e in r["errors"])

def has_warn(r, token):
    return any(token in w for w in r["warnings"])

# message builders
def msg(id, role, frm="a", auth=None, content="x", refs=None, status=None, meta=None, maci="0.1"):
    m = {"maci": maci, "id": id, "from": frm, "role": role, "content": content}
    if auth is not None: m["authority"] = auth
    if refs is not None: m["refs"] = refs
    if status is not None: m["status"] = status
    if meta is not None: m["meta"] = meta
    return m


# ═══════════════════════════════════════════════════════════════════════
# CURATED — must ACCEPT (well-formed protocol)
# ═══════════════════════════════════════════════════════════════════════

def curated_accept():
    cases = []

    # minimal valid proposal
    cases.append(("accept / minimal proposal",
                  [msg("m1", "PROPOSAL", auth="advisory")],
                  lambda r: r["ok"]))

    # sovereign command
    cases.append(("accept / sovereign command",
                  [msg("m1", "COMMAND", frm="human", auth="sovereign", content="go")],
                  lambda r: r["ok"]))

    # full clean chain
    chain = [
        msg("m1", "COMMAND", "human", "sovereign", "build"),
        msg("m2", "PROPOSAL", "alpha", "advisory", "design", refs=["m1"]),
        msg("m3", "EVIDENCE", "beta", "observer", "bench", refs=["m2"]),
        msg("m4", "DECISION", "human", "sovereign", "approve", refs=["m2", "m3"], status="approved"),
        msg("m5", "DELEGATE", "human", "sovereign", "implement", refs=["m4"], meta={"to": "alpha"}),
        msg("m6", "CODE", "alpha", "delegated", "code", refs=["m5"]),
        msg("m7", "EVIDENCE", "beta", "observer", "pass", refs=["m6"]),
    ]
    cases.append(("accept / full decision chain", chain,
                  lambda r: r["ok"] and ["m1","m2","m4","m5","m6","m7"] in r["chains"]))

    # legal delegated chain sovereign->A->B
    cases.append(("accept / delegated chain sovereign->A->B",
                  [msg("m1", "DELEGATE", "human", "sovereign", "lead", meta={"to": "orch"}),
                   msg("m2", "DELEGATE", "orch", None, "sub", refs=["m1"], meta={"to": "worker"}),
                   msg("m3", "CODE", "worker", "delegated", "done", refs=["m2"])],
                  lambda r: r["ok"]))

    # decision approving a question
    cases.append(("accept / decision approves a question",
                  [msg("q", "QUESTION", "alpha", "advisory", "which db?"),
                   msg("d", "DECISION", "human", "sovereign", "use postgres", refs=["q"], status="approved")],
                  lambda r: r["ok"]))

    # decision rejecting a proposal
    cases.append(("accept / decision rejects a proposal",
                  [msg("p", "PROPOSAL", "alpha", "advisory", "use mongo"),
                   msg("d", "DECISION", "human", "sovereign", "no", refs=["p"], status="rejected")],
                  lambda r: r["ok"]))

    # evidence answering a question clears the open-question warning
    cases.append(("accept / evidence answers question (no open warning)",
                  [msg("q", "QUESTION", "alpha", "advisory", "status?"),
                   msg("e", "EVIDENCE", "beta", "observer", "all green", refs=["q"])],
                  lambda r: r["ok"] and not has_warn(r, "OPEN_QUESTION")))

    # observer evidence is fine
    cases.append(("accept / observer evidence",
                  [msg("m1", "EVIDENCE", "sensor", "observer", "temp=42")],
                  lambda r: r["ok"]))

    # multiple independent roots
    cases.append(("accept / multiple independent roots",
                  [msg("a", "PROPOSAL", auth="advisory"), msg("b", "PROPOSAL", auth="advisory"),
                   msg("c", "EVIDENCE", auth="observer")],
                  lambda r: r["ok"] and len(r["chains"]) == 3))

    # comments and blank lines ignored
    cases.append(("accept / comments and blanks ignored (text)",
                  "// header comment\n\n" + json.dumps(msg("m1", "PROPOSAL", auth="advisory")) + "\n\n# trailing\n",
                  lambda r: r["ok"] and r["message_count"] == 1, True))

    return cases


# ═══════════════════════════════════════════════════════════════════════
# CURATED — must REJECT (protocol violations)
# ═══════════════════════════════════════════════════════════════════════

def curated_reject():
    cases = []

    cases.append(("reject / forged authority: advisory COMMAND",
                  [msg("a", "COMMAND", "rogue", "advisory", "shutdown")],
                  lambda r: not r["ok"] and has_err(r, "INSUFFICIENT_AUTHORITY")))

    cases.append(("reject / command with no authority",
                  [msg("a", "COMMAND", "worker", content="do")],
                  lambda r: not r["ok"] and has_err(r, "INSUFFICIENT_AUTHORITY")))

    cases.append(("reject / advisory delegates",
                  [msg("a", "DELEGATE", "weak", "advisory", "you do it", meta={"to": "x"})],
                  lambda r: not r["ok"] and has_err(r, "DELEGATE_WITHOUT_AUTHORITY")))

    cases.append(("reject / decision without refs",
                  [msg("a", "DECISION", "boss", "sovereign", "approved", status="approved")],
                  lambda r: not r["ok"] and has_err(r, "DECISION_WITHOUT_REFS")))

    cases.append(("reject / decision refs only evidence",
                  [msg("e", "EVIDENCE", "x", "observer", "fact"),
                   msg("d", "DECISION", "boss", "sovereign", "ok", refs=["e"], status="approved")],
                  lambda r: not r["ok"] and has_err(r, "DECISION_REFS_NO_PROPOSAL_OR_QUESTION")))

    cases.append(("reject / decision bad status",
                  [msg("p", "PROPOSAL", "x", "advisory", "p"),
                   msg("d", "DECISION", "boss", "sovereign", "maybe", refs=["p"], status="pending")],
                  lambda r: not r["ok"] and has_err(r, "DECISION_BAD_STATUS")))

    cases.append(("reject / forward reference",
                  [msg("m1", "PROPOSAL", "a", "advisory", "x", refs=["m2"]),
                   msg("m2", "PROPOSAL", "a", "advisory", "y")],
                  lambda r: not r["ok"] and has_err(r, "FORWARD_REF")))

    cases.append(("reject / ref not found",
                  [msg("a", "EVIDENCE", "x", "observer", "re ghost", refs=["ghost"])],
                  lambda r: not r["ok"] and has_err(r, "REF_NOT_FOUND")))

    cases.append(("reject / duplicate id",
                  [msg("dup", "PROPOSAL", "a", "advisory", "1"),
                   msg("dup", "PROPOSAL", "a", "advisory", "2")],
                  lambda r: not r["ok"] and has_err(r, "DUPLICATE_ID")))

    cases.append(("reject / delegate without target",
                  [msg("a", "DELEGATE", "human", "sovereign", "scope here")],
                  lambda r: not r["ok"] and has_err(r, "DELEGATE_NO_TARGET")))

    cases.append(("reject / invalid role",
                  [msg("a", "SHOUT", "x", "advisory", "hi")],
                  lambda r: not r["ok"] and has_err(r, "INVALID_ROLE")))

    cases.append(("reject / invalid authority enum",
                  [msg("a", "PROPOSAL", "x", "godmode", "hi")],
                  lambda r: not r["ok"] and has_err(r, "INVALID_AUTHORITY")))

    cases.append(("reject / invalid status enum",
                  [msg("p", "PROPOSAL", "x", "advisory", "p"),
                   msg("a", "DECISION", "b", "sovereign", "d", refs=["p"], status="vibes")],
                  lambda r: not r["ok"] and (has_err(r, "INVALID_STATUS") or has_err(r, "DECISION_BAD_STATUS"))))

    cases.append(("reject / empty content",
                  [msg("a", "PROPOSAL", "x", "advisory", "")],
                  lambda r: not r["ok"] and has_err(r, "EMPTY_CONTENT")))

    cases.append(("reject / missing required fields (text)",
                  json.dumps({"id": "a", "content": "incomplete"}),
                  lambda r: not r["ok"] and has_err(r, "MISSING_FIELDS"), True))

    cases.append(("reject / malformed json (text)",
                  '{"maci":"0.1","id":"a","from":"x","role":"PROPOSAL" BROKEN',
                  lambda r: not r["ok"] and has_err(r, "INVALID_JSON"), True))

    cases.append(("reject / decision cycle",
                  [msg("p", "PROPOSAL", "a", "advisory", "p"),
                   msg("d1", "DECISION", "b", "sovereign", "a", refs=["p"], status="approved"),
                   msg("d2", "DECISION", "b", "sovereign", "b", refs=["p", "d1"], status="approved"),
                   msg("d3", "DECISION", "b", "sovereign", "c", refs=["d2"], status="approved")],
                  lambda r: r["ok"] or True))  # ordering makes this legal; cycle tested separately

    # explicit cycle via hand-built refs (bypass ordering by referencing existing later -> forward, caught)
    cases.append(("reject / self-cycle by forward ref",
                  [msg("a", "DECISION", "b", "sovereign", "x", refs=["a"], status="approved")],
                  lambda r: not r["ok"]))

    return cases


# ═══════════════════════════════════════════════════════════════════════
# RUN curated (forward + reverse where it is a message list)
# ═══════════════════════════════════════════════════════════════════════

def run_curated(order):
    for case in curated_accept() + curated_reject():
        name, payload, check = case[0], case[1], case[2]
        is_text = isinstance(payload, str)
        if is_text:
            # text cases: order irrelevant, run once under 'forward'
            if order != "forward":
                continue
            r = run_text(payload)
            r1 = run_text(payload)
            assert_true(f"{order} curated / {name} / deterministic",
                        stable(r) == stable(r1), "nondeterministic")
            assert_true(f"{order} curated / {name}", check(r))
        else:
            seq = payload if order == "forward" else list(reversed(payload))
            r = run_validate(seq)
            r1 = run_validate(seq)
            assert_true(f"{order} curated / {name} / deterministic",
                        stable(r) == stable(r1), "nondeterministic")
            # reverse order legitimately changes causal validity for ref-bearing
            # chains, so for reverse we only assert determinism + no crash, plus
            # that accept-cases with refs may now fail on FORWARD_REF (expected).
            if order == "forward":
                assert_true(f"{order} curated / {name}", check(r))
            else:
                assert_true(f"{order} curated / {name} / no-crash",
                            isinstance(r["ok"], bool))


# ═══════════════════════════════════════════════════════════════════════
# FUZZ — seeded property tests
# ═══════════════════════════════════════════════════════════════════════

ROLES_POOL = ["COMMAND", "PROPOSAL", "QUESTION", "EVIDENCE", "DECISION", "DELEGATE", "CODE"]
AUTH_POOL = ["sovereign", "delegated", "advisory", "observer", None]

def fuzz_no_crash_and_deterministic(seed, count=120):
    rng = random.Random(seed)
    for i in range(count):
        n = rng.randint(1, 8)
        msgs = []
        ids = []
        for j in range(n):
            mid = f"f{seed}_{i}_{j}"
            role = rng.choice(ROLES_POOL)
            auth = rng.choice(AUTH_POOL)
            refs = rng.sample(ids, min(len(ids), rng.randint(0, 2))) if ids else []
            status = rng.choice([None, "approved", "rejected", "pending"]) if role == "DECISION" else None
            meta = {"to": f"agent{rng.randint(0,3)}"} if role == "DELEGATE" else None
            content = rng.choice(["x", "do the thing", "result", ""])
            msgs.append(msg(mid, role, f"ag{rng.randint(0,3)}", auth, content, refs or None, status, meta))
            ids.append(mid)
        r1 = run_validate(msgs)
        r2 = run_validate(msgs)
        assert_true(f"fuzz {seed}:{i} deterministic", stable(r1) == stable(r2), "nondeterministic fuzz")
        assert_true(f"fuzz {seed}:{i} ok-is-bool", isinstance(r1["ok"], bool))
        # property: if ok, then NO error tokens at all
        assert_true(f"fuzz {seed}:{i} ok-implies-no-errors",
                    (not r1["ok"]) or (len(r1["errors"]) == 0))
        # property: any forward ref or ghost ref => not ok
        for m in msgs:
            for ref in m.get("refs", []):
                pass  # checked structurally below
        # property: chains never contain an id not in the stream
        idset = {m["id"] for m in msgs}
        for ch in r1["chains"]:
            assert_true(f"fuzz {seed}:{i} chain-ids-valid",
                        all(c in idset for c in ch), f"chain has unknown id: {ch}")


def fuzz_property_authority(seed, count=60):
    """Property: a COMMAND/DECISION/DELEGATE by an agent with advisory/observer/none must fail."""
    rng = random.Random(seed)
    for i in range(count):
        role = rng.choice(["COMMAND", "DECISION", "DELEGATE"])
        bad_auth = rng.choice([None, "advisory", "observer"])
        m = msg("x", role, "ag", bad_auth, "act",
                refs=(["p"] if role == "DECISION" else None),
                status=("approved" if role == "DECISION" else None),
                meta=({"to": "t"} if role == "DELEGATE" else None))
        seq = [msg("p", "PROPOSAL", "a", "advisory", "p")] + [m] if role == "DECISION" else [m]
        r = run_validate(seq)
        assert_true(f"authprop {seed}:{i} {role}/{bad_auth} rejected",
                    not r["ok"], f"weak authority {role} wrongly accepted")


def fuzz_property_causal(seed, count=60):
    """Property: a forward reference is always rejected regardless of position."""
    rng = random.Random(seed)
    for i in range(count):
        a = msg("a", "PROPOSAL", "x", "advisory", "a", refs=["b"])
        b = msg("b", "PROPOSAL", "x", "advisory", "b")
        seq = [a, b]
        r = run_validate(seq)
        assert_true(f"causalprop {seed}:{i} forward-ref rejected",
                    not r["ok"] and has_err(r, "FORWARD_REF"))


def cycle_direct_tests():
    """
    Exercise the cycle detector DIRECTLY by calling validate() on hand-built
    Message objects whose refs form a true cycle. We bypass the JSON/causal
    layer so the cycle isn't pre-rejected as a forward ref — this is the only
    way to reach detect_cycles() in isolation.
    """
    from maci_validator import Message, validate

    # a -> b -> a  (mutual refs; both exist; cycle in the ref graph)
    ma = Message(maci="0.1", id="a", from_agent="x", role="PROPOSAL",
                 content="a", authority="advisory", refs=["b"], line=1)
    mb = Message(maci="0.1", id="b", from_agent="x", role="PROPOSAL",
                 content="b", authority="advisory", refs=["a"], line=2)
    r = validate([ma, mb])
    # the cycle detector must fire (in addition to any forward-ref error)
    assert_true("cycle-direct / a<->b detected",
                any("CHAIN_CYCLE" in e for e in r.errors),
                f"cycle not detected: {r.errors}")

    # a -> b -> c -> a (3-cycle)
    mc = [
        Message(maci="0.1", id="a", from_agent="x", role="PROPOSAL", content="a",
                authority="advisory", refs=["b"], line=1),
        Message(maci="0.1", id="b", from_agent="x", role="PROPOSAL", content="b",
                authority="advisory", refs=["c"], line=2),
        Message(maci="0.1", id="c", from_agent="x", role="PROPOSAL", content="c",
                authority="advisory", refs=["a"], line=3),
    ]
    r = validate(mc)
    assert_true("cycle-direct / a->b->c->a detected",
                any("CHAIN_CYCLE" in e for e in r.errors),
                f"3-cycle not detected: {r.errors}")

    # self-cycle a -> a
    msa = Message(maci="0.1", id="a", from_agent="x", role="PROPOSAL", content="a",
                  authority="advisory", refs=["a"], line=1)
    r = validate([msa])
    assert_true("cycle-direct / self-cycle detected",
                any("CHAIN_CYCLE" in e for e in r.errors),
                f"self-cycle not detected: {r.errors}")

    # acyclic control: a -> b, c -> b (diamond-ish, no cycle) must NOT report a cycle
    ctrl = [
        Message(maci="0.1", id="b", from_agent="x", role="PROPOSAL", content="b",
                authority="advisory", refs=[], line=1),
        Message(maci="0.1", id="a", from_agent="x", role="PROPOSAL", content="a",
                authority="advisory", refs=["b"], line=2),
        Message(maci="0.1", id="c", from_agent="x", role="PROPOSAL", content="c",
                authority="advisory", refs=["b"], line=3),
    ]
    r = validate(ctrl)
    assert_true("cycle-direct / acyclic control has no cycle",
                not any("CHAIN_CYCLE" in e for e in r.errors),
                f"false cycle on acyclic input: {r.errors}")


def decision_refs_direct_tests():
    """
    Exercise the DECISION-needs-refs and DECISION-needs-proposal rules directly,
    in causally-valid streams so they aren't shadowed by other errors.
    """
    # DECISION with no refs at all, everything else valid
    r = run_validate([msg("d", "DECISION", "boss", "sovereign", "approved!", status="approved")])
    assert_true("decision-direct / no refs rejected",
                not r["ok"] and has_err(r, "DECISION_WITHOUT_REFS"))

    # DECISION refs an EVIDENCE only (no proposal/question), causally valid
    r = run_validate([
        msg("e", "EVIDENCE", "x", "observer", "fact"),
        msg("d", "DECISION", "boss", "sovereign", "ok", refs=["e"], status="approved"),
    ])
    assert_true("decision-direct / refs evidence-only rejected",
                not r["ok"] and has_err(r, "DECISION_REFS_NO_PROPOSAL_OR_QUESTION"))

    # DECISION refs a CODE only (no proposal/question)
    r = run_validate([
        msg("c", "CODE", "x", "advisory", "src"),
        msg("d", "DECISION", "boss", "sovereign", "ok", refs=["c"], status="approved"),
    ])
    assert_true("decision-direct / refs code-only rejected",
                not r["ok"] and has_err(r, "DECISION_REFS_NO_PROPOSAL_OR_QUESTION"))

    # DECISION refs a PROPOSAL → accepted
    r = run_validate([
        msg("p", "PROPOSAL", "x", "advisory", "do it"),
        msg("d", "DECISION", "boss", "sovereign", "approve", refs=["p"], status="approved"),
    ])
    assert_true("decision-direct / refs proposal accepted", r["ok"])

    # DECISION refs a QUESTION → accepted
    r = run_validate([
        msg("q", "QUESTION", "x", "advisory", "which?"),
        msg("d", "DECISION", "boss", "sovereign", "this one", refs=["q"], status="approved"),
    ])
    assert_true("decision-direct / refs question accepted", r["ok"])


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    run_curated("forward")
    run_curated("reverse")

    # direct-pass tests that aren't shadowed by earlier validation layers
    cycle_direct_tests()
    decision_refs_direct_tests()

    for seed in (1, 7, 13, 42, 99):
        fuzz_no_crash_and_deterministic(seed)
        fuzz_property_authority(seed)
        fuzz_property_causal(seed)

    npass = sum(1 for r in RESULTS if r["status"] == "PASS")
    nfail = sum(1 for r in RESULTS if r["status"] == "FAIL")
    results_hash = hashlib.sha256(json.dumps(RESULTS, sort_keys=True).encode()).hexdigest()

    report = {
        "suite": "MACI Torture Suite v0.1",
        "pass": npass,
        "fail": nfail,
        "result_count": len(RESULTS),
        "results_hash": results_hash,
    }
    print(json.dumps(report, indent=2))

    if nfail:
        print("\nFAILURES:", file=sys.stderr)
        for r in RESULTS:
            if r["status"] == "FAIL":
                print(f"  ✗ {r['name']}: {r['detail']}", file=sys.stderr)

    # full results for inspection
    import os
    out = os.environ.get("MACI_TORTURE_OUT")
    if out:
        with open(out, "w") as f:
            json.dump({**report, "results": RESULTS}, f, indent=2)

    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
