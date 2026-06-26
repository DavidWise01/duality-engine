#!/usr/bin/env python3
"""
HACI Torture Suite x2 for Validator v2.5

No new HACI features.
No validator changes.

x2:
1. Curated adversarial suite.
2. Seeded fuzz/property suite.

Both layers run:
- forward order
- reverse order

v2.5-specific:
- declaration + > commits
- declaration + ! commits
- declaration + ? is pending, not committed
- declaration with no suffix is pending, not committed
- pending declarations do not mutate committed meaning/authority
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import random
import json
import traceback
import hashlib

from haci_validator import validate_project

PASS = 0
FAIL = 0
RESULTS = []

def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p

def stable_json(result):
    data = json.loads(json.dumps(result.__dict__, default=lambda o: o.__dict__))
    root = data.get("root", "")
    raw = json.dumps(data, sort_keys=True)
    if root:
        raw = raw.replace(root, "<ROOT>")
    return raw

def assert_true(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append({"name": name, "status": "PASS"})
    else:
        FAIL += 1
        RESULTS.append({"name": name, "status": "FAIL", "detail": detail})
        raise AssertionError(f"{name}: {detail}")

def run_case(name, builder, checker, strict=False):
    with tempfile.TemporaryDirectory() as tmp:
        builder(Path(tmp))
        r1 = validate_project(Path(tmp), strict=strict)
        r2 = validate_project(Path(tmp), strict=strict)
        assert_true(name + " / deterministic", stable_json(r1) == stable_json(r2), "same input produced different output")
        checker(name, r1)

def has_error(r, token):
    return any(token in e for e in r.errors)

def ask_convs(r):
    return [c for c in r.conversations if c["kind"] == "conversation" and c["start"]["outbound"] == "ask"]

def has_diag(c, token):
    return token in c.get("diagnostics", [])

# -----------------------
# Curated adversarial cases
# -----------------------

def b_pending_question_decl(root):
    write(root, "10_memory/m.haci", "! m memory ?")

def c_pending_question_decl(name, r):
    sym = r.symbols.get("memory.m", {})
    ok = (
        not r.ok
        and has_error(r, "DECLARATION_PENDING_NOT_COMMITTED")
        and has_error(r, "INBOUND_QUESTION_UNRESOLVED")
        and "meaning" not in sym
        and "authority" not in sym
        and bool(sym.get("pending_declarations"))
    )
    assert_true(name, ok, str(r.errors) + json.dumps(sym, indent=2))

def b_pending_no_suffix_decl(root):
    write(root, "10_memory/m.haci", "! m memory")

def c_pending_no_suffix_decl(name, r):
    sym = r.symbols.get("memory.m", {})
    ok = (
        not r.ok
        and has_error(r, "DECLARATION_PENDING_NOT_COMMITTED")
        and "meaning" not in sym
        and "authority" not in sym
        and bool(sym.get("pending_declarations"))
    )
    assert_true(name, ok, str(r.errors) + json.dumps(sym, indent=2))

def b_committed_observe_decl(root):
    write(root, "10_memory/m.haci", "! m memory >")

def c_committed_observe_decl(name, r):
    sym = r.symbols.get("memory.m", {})
    ok = r.ok and sym.get("meaning") == "memory" and sym.get("authority") == "human" and sym.get("commit_state") == "committed"
    assert_true(name, ok, str(r.errors) + json.dumps(sym, indent=2))

def b_committed_bang_decl(root):
    write(root, "10_memory/m.haci", "! m memory !")

def c_committed_bang_decl(name, r):
    sym = r.symbols.get("memory.m", {})
    ok = r.ok and sym.get("meaning") == "memory" and sym.get("authority") == "human"
    assert_true(name, ok, str(r.errors) + json.dumps(sym, indent=2))

def b_pending_then_commit_different(root):
    write(root, "10_memory/m.haci", """! m memory ?
! m model >
""")

def c_pending_then_commit_different(name, r):
    sym = r.symbols.get("memory.m", {})
    ok = (
        not r.ok
        and has_error(r, "DECLARATION_PENDING_NOT_COMMITTED")
        and not has_error(r, "DUPLICATE_OR_CONFLICTING_SYMBOL")
        and not has_error(r, "AUTHORITY_MUTATION")
        and sym.get("meaning") == "model"
        and bool(sym.get("pending_declarations"))
    )
    assert_true(name, ok, str(r.errors) + json.dumps(sym, indent=2))

def b_inbound_question_open(root):
    write(root, "10_memory/m.haci", "? m clarify this ?")

def c_inbound_question_open(name, r):
    ok = (
        not r.ok
        and has_error(r, "INBOUND_QUESTION_UNRESOLVED")
        and has_error(r, "OPEN_CONVERSATION")
        and has_error(r, "ASK_WITHOUT_RETURN")
    )
    assert_true(name, ok, str(r.errors))

def b_inbound_observe_complete(root):
    write(root, "10_memory/m.haci", "? m clarify this >")

def c_inbound_observe_complete(name, r):
    assert_true(name, r.ok, str(r.errors))

def b_inbound_commit_complete(root):
    write(root, "10_memory/m.haci", "? m commit this !")

def c_inbound_commit_complete(name, r):
    assert_true(name, r.ok, str(r.errors))

def b_return_question_open(root):
    write(root, "10_memory/m.haci", """? m needle
m needle ?
""")

def c_return_question_open(name, r):
    ok = not r.ok and has_error(r, "OPEN_CONVERSATION") and has_error(r, "ASK_WITHOUT_RETURN")
    assert_true(name, ok, str(r.errors) + json.dumps(r.conversations, indent=2))

def b_return_question_then_answer(root):
    write(root, "10_memory/m.haci", """? m needle
m needle ?
m needle >
""")

def c_return_question_then_answer(name, r):
    convs = ask_convs(r)
    ok = r.ok and convs and any(ret["inbound"] == "ask" for ret in convs[0]["returns"]) and any(ret["inbound"] == "observe" for ret in convs[0]["returns"])
    assert_true(name, ok, str(r.errors) + json.dumps(r.conversations, indent=2))

def b_return_observe_complete(root):
    write(root, "10_memory/m.haci", """? m needle
m needle >
""")

def c_return_observe_complete(name, r):
    assert_true(name, r.ok, str(r.errors))

def b_clean_deep_dot(root):
    write(root, "10_memory/m.haci", "! m memory >")
    write(root, "10_memory/m/parser/last.haci", "! last prior result >")
    write(root, "20_runtime/runtime.haci", "? m.parser.last previous result >")

def c_clean_deep_dot(name, r):
    assert_true(name, r.ok, str(r.errors))

def b_phantom_dot(root):
    write(root, "10_memory/m.haci", "! m memory >")
    write(root, "20_runtime/runtime.haci", "? m.parser.last previous result >")

def c_phantom_dot(name, r):
    assert_true(name, not r.ok and has_error(r, "DOT_PATH_NOT_FOUND"), str(r.errors))

def b_ambiguous_alias(root):
    write(root, "10_memory/cache.haci", "! cache memory cache >")
    write(root, "20_code/cache.haci", "! cache code cache >")
    write(root, "30_runtime/runtime.haci", "? cache status >")

def c_ambiguous_alias(name, r):
    assert_true(name, not r.ok and has_error(r, "AMBIGUOUS_OBJECT:cache"), str(r.errors))

def b_canonical_alias(root):
    write(root, "10_memory/cache.haci", "! cache memory cache >")
    write(root, "20_code/cache.haci", "! cache code cache >")
    write(root, "30_runtime/runtime.haci", "? memory.cache status >")

def c_canonical_alias(name, r):
    assert_true(name, r.ok, str(r.errors))

def b_pairing_first_second(root):
    write(root, "10_memory/m.haci", """? m first question
? m second question
m second answer >
m first answer >
""")

def c_pairing_first_second(name, r):
    convs = ask_convs(r)
    first = [c for c in convs if "first question" in c["start"]["payload"]][0]
    second = [c for c in convs if "second question" in c["start"]["payload"]][0]
    ok = "first answer" in first["returns"][0]["payload"] and "second answer" in second["returns"][0]["payload"]
    assert_true(name, r.ok and ok, json.dumps(r.conversations, indent=2))

def b_ambiguous_zero_score(root):
    write(root, "10_memory/m.haci", """? m alpha
? m beta
m gamma >
m delta >
""")

def c_ambiguous_zero_score(name, r):
    assert_true(name, not r.ok and has_error(r, "OPEN_CONVERSATION") and has_error(r, "RETURN_WITHOUT_OPEN_REQUEST"), str(r.errors))

def b_ambiguous_positive_tie(root):
    write(root, "10_memory/m.haci", """? m alpha red
? m alpha blue
m alpha green >
m alpha yellow >
""")

def c_ambiguous_positive_tie(name, r):
    convs = ask_convs(r)
    ok = (
        not r.ok
        and has_error(r, "OPEN_CONVERSATION")
        and has_error(r, "RETURN_WITHOUT_OPEN_REQUEST")
        and any(has_diag(c, "AMBIGUOUS_RETURN_PAIR") for c in convs)
    )
    assert_true(name, ok, str(r.errors) + json.dumps(r.conversations, indent=2))

def b_mutual_unique_pair(root):
    write(root, "10_memory/m.haci", """? m alpha red
? m alpha blue
m alpha blue >
m alpha red >
""")

def c_mutual_unique_pair(name, r):
    convs = ask_convs(r)
    red = [c for c in convs if "red" in c["start"]["payload"]][0]
    blue = [c for c in convs if "blue" in c["start"]["payload"]][0]
    ok = r.ok and "red" in red["returns"][0]["payload"] and "blue" in blue["returns"][0]["payload"]
    assert_true(name, ok, str(r.errors) + json.dumps(r.conversations, indent=2))

def b_single_no_overlap(root):
    write(root, "10_memory/m.haci", """? m alpha
m zulu >
""")

def c_single_no_overlap(name, r):
    assert_true(name, not r.ok and has_error(r, "OPEN_CONVERSATION") and has_error(r, "RETURN_WITHOUT_OPEN_REQUEST"), str(r.errors))

def b_unmatched_return(root):
    write(root, "10_memory/m.haci", "! m memory >\nm extra result >")

def c_unmatched_return_strict(name, r):
    assert_true(name, not r.ok and has_error(r, "RETURN_WITHOUT_OPEN_REQUEST"), str(r.errors))

def b_heading_boundary(root):
    write(root, "10_memory/m.haci", """? m needle

# New Section
loose note
m needle >
""")

def c_heading_boundary(name, r):
    convs = ask_convs(r)
    assert_true(name, r.ok and convs and len(convs[0]["body"]) == 0, str(r.errors) + json.dumps(r.conversations, indent=2))

def b_blank_boundary(root):
    write(root, "10_memory/m.haci", """? m needle

loose note
m needle >
""")

def c_blank_boundary(name, r):
    convs = ask_convs(r)
    assert_true(name, r.ok and convs and len(convs[0]["body"]) == 0, str(r.errors) + json.dumps(r.conversations, indent=2))

def b_code_fence(root):
    write(root, "10_memory/m.haci", """```python
? x ignored >
```
""")

def c_code_fence(name, r):
    assert_true(name, r.ok and len(r.conversations) == 0, str(r.errors))

def b_cycle(root):
    write(root, "10_memory/m.haci", "? c helper >")
    write(root, "20_code/c.haci", "? m memory >")

def c_cycle(name, r):
    assert_true(name, not r.ok and has_error(r, "DEPENDENCY_CYCLE"), str(r.errors))

def b_objectless_protocol(root):
    write(root, "10_memory/m.haci", "done >")

def c_objectless_protocol(name, r):
    assert_true(name, not r.ok and (has_error(r, "UNDECLARED_OBJECT:done") or has_error(r, "OBJECT_REQUIRED")), str(r.errors))

def b_case_swap(root):
    write(root, "10_memory/m.haci", "! m memory >")
    write(root, "20_code/c.haci", "! c CODE >")

def c_case_swap(name, r):
    m = next(n for n in r.nodes if n.get("object") == "m")
    c = next(n for n in r.nodes if n.get("object") == "c")
    ok = m["owner"] == "human" and c["owner"] == "ai"
    assert_true(name, r.ok and ok, str(r.errors) + json.dumps(r.nodes, indent=2))

CURATED = [
    ("pending question declaration", b_pending_question_decl, c_pending_question_decl, True),
    ("pending no suffix declaration", b_pending_no_suffix_decl, c_pending_no_suffix_decl, True),
    ("committed observe declaration", b_committed_observe_decl, c_committed_observe_decl, True),
    ("committed bang declaration", b_committed_bang_decl, c_committed_bang_decl, True),
    ("pending then commit different", b_pending_then_commit_different, c_pending_then_commit_different, True),
    ("inbound question open", b_inbound_question_open, c_inbound_question_open, True),
    ("inbound observe complete", b_inbound_observe_complete, c_inbound_observe_complete, True),
    ("inbound commit complete", b_inbound_commit_complete, c_inbound_commit_complete, True),
    ("return question open", b_return_question_open, c_return_question_open, True),
    ("return question then answer", b_return_question_then_answer, c_return_question_then_answer, True),
    ("return observe complete", b_return_observe_complete, c_return_observe_complete, True),
    ("clean deep dot", b_clean_deep_dot, c_clean_deep_dot, True),
    ("phantom dot fails", b_phantom_dot, c_phantom_dot, True),
    ("ambiguous alias fails", b_ambiguous_alias, c_ambiguous_alias, False),
    ("canonical alias passes", b_canonical_alias, c_canonical_alias, True),
    ("pair first second", b_pairing_first_second, c_pairing_first_second, True),
    ("ambiguous zero score", b_ambiguous_zero_score, c_ambiguous_zero_score, True),
    ("ambiguous positive tie", b_ambiguous_positive_tie, c_ambiguous_positive_tie, True),
    ("mutual unique pair", b_mutual_unique_pair, c_mutual_unique_pair, True),
    ("single no overlap fails", b_single_no_overlap, c_single_no_overlap, True),
    ("unmatched return strict", b_unmatched_return, c_unmatched_return_strict, True),
    ("heading boundary", b_heading_boundary, c_heading_boundary, True),
    ("blank boundary", b_blank_boundary, c_blank_boundary, True),
    ("code fence", b_code_fence, c_code_fence, True),
    ("cycle detection", b_cycle, c_cycle, False),
    ("objectless protocol", b_objectless_protocol, c_objectless_protocol, True),
    ("case swap", b_case_swap, c_case_swap, False),
]

# -----------------------
# Fuzz/property suite
# -----------------------

OBJECTS = ["m", "c", "n", "cache", "state"]
FOLDERS = {
    "m": "10_memory",
    "c": "20_code",
    "n": "30_network",
    "cache": "10_memory",
    "state": "00_core",
}
WORDS = [
    "alpha", "beta", "gamma", "delta", "first", "second", "status",
    "memory", "code", "network", "parser", "last", "red", "blue", "green",
    "needle", "thread", "model"
]

def build_random_project(root: Path, rng: random.Random, valid_bias=True):
    declared = []
    for obj in OBJECTS:
        if rng.random() < 0.7:
            folder = FOLDERS[obj]
            # File root declarations must be committed; v2.5 correctly treats no suffix as pending.
            write(root, f"{folder}/{obj}.haci", f"! {obj} {obj} >\n")
            declared.append(obj)

    if not declared:
        write(root, "10_memory/m.haci", "! m memory >\n")
        declared.append("m")

    if "m" in declared and rng.random() < 0.25:
        write(root, "10_memory/m/parser/last.haci", "! last last >\n")

    lines = []
    for _ in range(rng.randint(3, 10)):
        obj = rng.choice(OBJECTS if not valid_bias or rng.random() < 0.25 else declared)
        if obj == "m" and rng.random() < 0.10:
            obj = "m.parser.last"
        payload = " ".join(rng.sample(WORDS, rng.randint(1, 3)))
        kind = rng.choice(["ask", "return_obs", "return_q", "return_commit", "dual_obs", "dual_q", "dual_commit", "declare_obs", "declare_q", "declare_pending", "body", "heading", "blank"])
        if kind == "ask":
            lines.append(f"? {obj} {payload}")
        elif kind == "return_obs":
            lines.append(f"{obj} {payload} >")
        elif kind == "return_q":
            lines.append(f"{obj} {payload} ?")
        elif kind == "return_commit":
            lines.append(f"{obj} {payload} !")
        elif kind == "dual_obs":
            lines.append(f"? {obj} {payload} >")
        elif kind == "dual_q":
            lines.append(f"? {obj} {payload} ?")
        elif kind == "dual_commit":
            lines.append(f"? {obj} {payload} !")
        elif kind == "declare_obs":
            lines.append(f"! {obj} {payload} >")
        elif kind == "declare_q":
            lines.append(f"! {obj} {payload} ?")
        elif kind == "declare_pending":
            lines.append(f"! {obj} {payload}")
        elif kind == "body":
            lines.append(payload)
        elif kind == "heading":
            lines.append("# boundary")
        else:
            lines.append("")

    write(root, "90_runtime/runtime.haci", "\n".join(lines) + "\n")

def fuzz_no_crash_and_deterministic(seed: int, count: int = 100):
    rng = random.Random(seed)
    for i in range(count):
        with tempfile.TemporaryDirectory() as tmp:
            build_random_project(Path(tmp), rng, valid_bias=(i % 2 == 0))
            r1 = validate_project(Path(tmp), strict=bool(i % 3 == 0))
            r2 = validate_project(Path(tmp), strict=bool(i % 3 == 0))
            assert_true(f"fuzz {seed}:{i} no crash", True)
            assert_true(f"fuzz {seed}:{i} deterministic", stable_json(r1) == stable_json(r2), "non-deterministic fuzz output")

def fuzz_monotonic_strict(seed: int, count: int = 50):
    rng = random.Random(seed)
    for i in range(count):
        with tempfile.TemporaryDirectory() as tmp:
            build_random_project(Path(tmp), rng, valid_bias=False)
            loose = validate_project(Path(tmp), strict=False)
            strict = validate_project(Path(tmp), strict=True)
            if not loose.ok:
                assert_true(
                    f"strict monotonic {seed}:{i}",
                    len(strict.errors) >= len(loose.errors),
                    f"loose={loose.errors} strict={strict.errors}"
                )
            else:
                assert_true(f"strict monotonic {seed}:{i}", True)

def run_all(order="forward"):
    cases = CURATED if order == "forward" else list(reversed(CURATED))
    for name, builder, checker, strict in cases:
        run_case(f"{order} curated / {name}", builder, checker, strict=strict)

    seeds = [1337, 7331] if order == "forward" else [7331, 1337]
    for seed in seeds:
        fuzz_no_crash_and_deterministic(seed, count=100)
        fuzz_monotonic_strict(seed, count=50)

def main():
    global PASS, FAIL
    try:
        run_all("forward")
        run_all("reverse")
    except Exception:
        FAIL += 1
        RESULTS.append({"name": "uncaught exception", "status": "FAIL", "traceback": traceback.format_exc()})
        raise
    finally:
        report = {
            "suite": "HACI Torture Suite x2 for v2.5",
            "pass": PASS,
            "fail": FAIL,
            "result_count": len(RESULTS),
            "results_hash": hashlib.sha256(json.dumps(RESULTS, sort_keys=True).encode()).hexdigest(),
            "results": RESULTS,
        }
        Path("TORTURE_RESULTS.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ["suite", "pass", "fail", "result_count", "results_hash"]}, indent=2))
    return 0 if FAIL == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
