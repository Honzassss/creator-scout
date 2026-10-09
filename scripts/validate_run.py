#!/usr/bin/env python3
"""Automatic checks A0-A7 from docs/validation-plan.md, read-only, standard library only.

Reads run snapshots from a running backend or from JSON files, plus the fetched items in one or more
cache dirs, and prints a markdown table for the README "Validation" section. Exit code 0 when every
check that ran passed, 1 when any failed or when run snapshots were given but nothing was measured,
2 on a usage error or when a run, file or backend cannot be read. Writes nothing unless --json is given,
and --json writes only under data/validation/ (gitignored).

Output names no account: candidate ids, handles, URLs and ref ids are shown as a platform prefix plus
an 8-char sha1, quotes as length + sha1. --show-text prints them in clear (local debugging only).

  PY=backend/.venv/bin/python   # any python >= 3.10 works, no third-party imports
  $PY scripts/validate_run.py --base http://127.0.0.1:8040 --run r_abc --cache-dir data/cache
  $PY scripts/validate_run.py --base http://127.0.0.1:8040 --all-runs --cache-dir data/cache
  $PY scripts/validate_run.py --file data/live-run/runs --cache-dir data/live-run/cache --self-test
  $PY scripts/validate_run.py --diff before.json after.json     # A4: two snapshots of one run, goal A vs goal B
  $PY scripts/validate_run.py --diff goal_response.json         # A4 from a report_diff / {"report_diffs": [...]}
  $PY scripts/validate_run.py --self-test                       # A0 on a built-in synthetic run

Checks (docs/validation-plan.md section 3):
  A0  self-test: 3 planted defects (fact without source, elimination result without value, altered quote)
  A1  every fact / pass-fail result has a source URL; inferences cite facts; claims cite a quoted source
  A2  quote text is in the fetched item for that URL (generated labels reported apart, not failed)
  A3  every elimination has round, criterion, English reason, source and a failing result with value;
      every candidate with status "eliminated" has an elimination record
  A4  goal switch changes the report (only with --diff); "pass (live fetches not measured)" when the
      two snapshots are different runs or the input is a report_diff
  A5a identity verdict present on every report; "matched" needs a sourced supporting signal
  A5b wrong anchor not matched (only with --wrong-anchor)
  A6  every SourceRef labeled live, cache or mock
  A7  no score / rank / best / sensitive-trait keys; no commenter identity in stored comments
  SM1-SM3  subject-mode fields (confidence per finding, identity verdict line, report_diff); skipped with a
           note while the fields are absent (subject-mode branch not merged).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

MODES = ("live", "cache", "mock")
QUOTE_SCOPE = {"finding:fact", "claim", "elimination"}      # plan A2: "not found" must be 0 here
FORBIDDEN_KEYS = {"score", "overall_score", "rank", "ranking", "best", "risk_level", "risk_score", "trust_score",
                  "gender", "age", "ethnicity", "religion"}
FORBIDDEN_RE = re.compile(r"(^|_)(score|rank|ranking)$|^best(_|$)", re.I)
# Commenter identity in stored comments (normalized cache or raw actor items). Same keys the live-test
# redaction scrubs (scripts/live_tests.py _COMMENT_ID_KEYS), minus the comment's own id / url.
COMMENTER_KEYS = ("ownerUsername", "owner", "ownerProfilePicUrl", "ownerId", "ownerFullName", "username",
                  "full_name", "fullName", "profile_pic_url", "profilePicUrl", "uid", "uniqueId", "avatarThumbnail",
                  "avatarThumb", "nickname", "nickName", "user", "pk", "author", "authorMeta", "author_handle",
                  "commenter", "commenter_handle")
COMMENT_LIST_KEYS = ("latestComments", "comments", "replies", "childComments", "preview_comments", "topComments")
REDACTED_VALUES = {"", "[redacted]", "redacted", "[REDACTED]", "REDACTED"}
TEXT_KEYS = ("caption", "bio", "biography", "text", "title", "snippet", "description", "desc", "display_name",
             "fullName", "full_name", "handle", "username", "location_name", "locationName", "business_category",
             "businessCategoryName", "brand", "outlet", "firstComment")
URL_KEYS = ("url", "post_url", "postUrl", "inputUrl", "webVideoUrl", "link")
# Text our own code writes into SourceRef.quote that is not a quote of the fetched item (dry run, plan section 9):
# discovery labels, private-profile marker, Meta Branded Content line, account region, bare hashtag label.
LABEL_RE = re.compile(r"^(search|hashtag|place|related|manual)(:|$)|^PROFILE_PRIVATE$|\(Meta Branded Content\)$"
                      r"|^region [A-Za-z]{2}$|^#[\w.]+$")

PASS, FAIL, SKIP = "pass", "FAIL", "skipped"
PASS_NO_LIVE = "pass (live fetches not measured)"     # A4 when the "0 live fetches" part could not be measured
MEASURED = ("A1", "A2", "A3", "A5a", "A5b", "A6")      # all skipped on given runs -> "nothing measured", exit 1
VALIDATION_DIR = Path(__file__).resolve().parents[1] / "data" / "validation"    # gitignored (data/)
SHOW_TEXT = False                                      # set by main(--show-text); otherwise ids are hashed


def _h(s: Any) -> str:
    return hashlib.sha1(str(s).encode("utf-8")).hexdigest()[:8]


def hid(cid: Any) -> str:
    """Candidate id ``platform:handle`` -> ``platform:#sha1[:8]`` (the README must not name accounts)."""
    s = str(cid)
    if SHOW_TEXT:
        return s
    return f"{s.split(':', 1)[0]}:#{_h(s)}" if ":" in s else f"#{_h(s)}"


def hhandle(platform: Any, handle: Any) -> str:
    return f"{platform}:{handle}" if SHOW_TEXT else f"{platform}:#{_h(f'{platform}:{handle}')}"


def href(ref_id: Any) -> str:
    """Ref id ``ig:profile:<handle>`` -> ``ig:profile:#sha1[:8]``."""
    s = str(ref_id)
    if SHOW_TEXT:
        return s
    return f"{s.rsplit(':', 1)[0]}:#{_h(s)}" if ":" in s else f"#{_h(s)}"


def hurl(url: Any) -> str:
    u = str(url or "")
    return u if SHOW_TEXT else f"{urllib.parse.urlsplit(u).netloc or '?'}/#{_h(url_key(u))}"


def pstr(path: tuple) -> str:
    """Dotted path with the candidate-id key (the element after "candidates") hashed."""
    out = []
    for i, p in enumerate(path):
        out.append(hid(p) if i and path[i - 1] == "candidates" else str(p))
    return ".".join(out)


@dataclass
class Check:
    id: str
    name: str
    sample: str
    result: str
    status: str
    details: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------------------ loading

def _http_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=60) as resp:     # noqa: S310 (local backend only)
        return json.loads(resp.read().decode("utf-8"))


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text("utf-8"))


def is_run(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("candidates"), dict) and "criteria" in data


def load_runs(files: list[str], base: str | None, run_ids: list[str], all_runs: bool) -> list[dict]:
    runs: list[dict] = []
    for p in files:
        path = Path(p)
        for f in (sorted(path.glob("*.json")) if path.is_dir() else [path]):
            data = _read_json(f)
            if is_run(data):
                runs.append(data)
            else:
                print(f"note: {f} is not a run snapshot, skipped", file=sys.stderr)
    if base:
        base = base.rstrip("/")
        ids = list(run_ids)
        if all_runs:
            ids += [r["run_id"] for r in _http_json(f"{base}/api/runs") if r.get("run_id") not in ids]
        for rid in ids:
            runs.append(_http_json(f"{base}/api/runs/{urllib.parse.quote(rid)}"))
    return runs


# ------------------------------------------------------------------------------------------ helpers

def walk(o: Any, path: tuple = ()) -> Iterator[tuple[tuple, dict]]:
    """(path, dict) for every dict in the tree."""
    if isinstance(o, dict):
        yield path, o
        for k, v in o.items():
            yield from walk(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, path + (i,))


def get_at(o: Any, path: tuple) -> Any:
    for k in path:
        o = o[k]
    return o


def is_ref(d: Any) -> bool:
    """SourceRef shape. ``mode`` is NOT required here, so a ref without a mode is caught by A6."""
    return isinstance(d, dict) and "url" in d and "platform" in d and "fetched_at" in d


def has_url(srcs: Any) -> bool:
    return any(isinstance(s, dict) and re.match(r"https?://", s.get("url") or "") for s in srcs or [])


def en(t: Any) -> str:
    return (t.get("en") or "") if isinstance(t, dict) else (t or "")


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    return re.sub(r"\s+", " ", s).strip()


def norm_quote(q: str) -> str:
    q = norm_text(q)
    q = q.strip("…").strip()
    q = re.sub(r"(\.\.\.)$", "", q).strip()
    q = q.removeprefix("\U0001F4CD").strip()            # local signal quotes: "📍 <location name>"
    return q.lstrip("@").rstrip(".").strip()


def url_key(u: str) -> str:
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = re.split(r"[?#]", u, maxsplit=1)[0]
    return u.rstrip("/")


def run_id(run: dict) -> str:
    return str(run.get("id") or "?")


def candidates(run: dict) -> Iterator[tuple[str, dict]]:
    for cid, c in (run.get("candidates") or {}).items():
        if isinstance(c, dict):
            yield cid, c


def reports(run: dict) -> Iterator[tuple[str, dict, dict]]:
    for cid, c in candidates(run):
        if isinstance(c.get("report"), dict):
            yield cid, c, c["report"]


def ref_context(run: dict, path: tuple) -> str:
    """Where a SourceRef sits: finding:<kind>, claim, elimination, result, collab, news, identity, profile, ..."""
    p = list(path)
    if "elimination" in p:
        return "elimination"
    if "report" in p:
        i = p.index("report")
        sub = p[i + 1] if len(p) > i + 1 else None
        if sub == "findings" and len(p) > i + 2:
            f = get_at(run, tuple(p[: i + 3]))
            return f"finding:{f.get('kind')}" if isinstance(f, dict) else "finding"
        return {"claims": "claim", "collab_timeline": "collab", "news": "news", "identity": "identity",
                "identity_verdict": "identity"}.get(sub, f"report:{sub}")
    if "results" in p:
        return "result"
    for key in ("metrics", "profile", "ref"):
        if key in p:
            return {"ref": "discovery"}.get(key, key)
    return "other"


def _load_dir_json(dirs: list[str]) -> Iterator[tuple[Path, Any]]:
    """Fetched files under the cache dirs. Run snapshots are skipped: they are our output, not fetched
    data, and indexing them would let a quote match itself (give runs with --file)."""
    for d in dirs:
        root = Path(d)
        files = [root] if root.is_file() else sorted(root.rglob("*.json"))
        for f in files:
            try:
                data = _read_json(f)
            except (OSError, ValueError):
                continue
            if not is_run(data):
                yield f, data


def build_index(dirs: list[str]) -> tuple[dict[str, str], int]:
    """(index_from_data over every fetched file in ``dirs``, number of fetched files)."""
    datas = [data for _f, data in _load_dir_json(dirs)]
    return index_from_data(datas), len(datas)


def index_from_data(datas: list[Any]) -> dict[str, str]:
    """url key -> normalized text of every fetched item for that URL (bio, caption, comment text, news
    title / snippet, location name, links, hashtags, mentions). SourceRef.quote values are never indexed."""
    idx: dict[str, list[str]] = {}
    for data in datas:
        for _p, o in walk(data):
            parts = [o[k] for k in TEXT_KEYS if isinstance(o.get(k), str)]
            for k in ("external_urls", "externalUrls"):
                parts += [u for u in o.get(k) or [] if isinstance(u, str)]
            parts += [f"#{h}" for h in o.get("hashtags") or [] if isinstance(h, str)]
            parts += [f"@{h}" for h in o.get("mentions") or [] if isinstance(h, str)]
            if not parts:
                continue
            urls = {o[k] for k in URL_KEYS if isinstance(o.get(k), str)}
            src = o.get("source")
            if isinstance(src, dict) and isinstance(src.get("url"), str):
                urls.add(src["url"])
            text = norm_text(" \n ".join(parts))
            for u in urls:
                idx.setdefault(url_key(u), []).append(text)
    return {k: " \n ".join(v) for k, v in idx.items()}


def _uniq(cands: set) -> str:
    return f"{len(cands)} unique candidate{'' if len(cands) == 1 else 's'}"


# ------------------------------------------------------------------------------------------ A1

def a1_sources(runs: list[dict]) -> Check:
    n, bad, cands = Counter(), [], set()
    for run in runs:
        rid = run_id(run)
        for cid, c in candidates(run):
            for r in c.get("results") or []:
                if r.get("status") in ("pass", "fail"):
                    n["criterion results"] += 1
                    cands.add(cid)
                    if not has_url(r.get("sources")):
                        bad.append(f"{rid}:{hid(cid)}:result:{r.get('criterion_id')}")
        for cid, _c, rep in reports(run):
            cands.add(cid)
            pc = hid(cid)
            findings = rep.get("findings") or []
            facts = {f.get("id") for f in findings if f.get("kind") == "fact"}
            ids = {f.get("id") for f in findings} | {e.get("id") for e in rep.get("collab_timeline") or []}
            for f in findings:
                kind = f.get("kind")
                n[{"fact": "facts", "inference": "inferences"}.get(kind, "gaps")] += 1
                if kind == "fact" and not has_url(f.get("sources")):
                    bad.append(f"{rid}:{pc}:{f.get('id')}:no_source")
                if kind == "inference" and (not f.get("based_on") or not set(f["based_on"]) <= facts):
                    bad.append(f"{rid}:{pc}:{f.get('id')}:based_on")
            for cl in rep.get("claims") or []:
                n["claims"] += 1
                src = cl.get("claim_source") or {}
                if not has_url([src]) or not (src.get("quote") or "").strip():
                    bad.append(f"{rid}:{pc}:{cl.get('id')}:claim_source")
                if not set(cl.get("evidence") or []) <= ids:
                    bad.append(f"{rid}:{pc}:{cl.get('id')}:evidence")
    sample = ", ".join(f"{v} {k}" for k, v in sorted(n.items())) or "nothing to check"
    if n:
        sample += f" ({_uniq(cands)})"
    return Check("A1", "Every fact has a source URL", sample, f"{len(bad)} missing or broken",
                 PASS if not bad and n else (SKIP if not n else FAIL), {"failed": bad})


# ------------------------------------------------------------------------------------------ A2

def classify_quote(url: str, quote: str, idx: dict[str, str]) -> str:
    q = norm_quote(quote)
    text = idx.get(url_key(url))
    if not q:
        return "label_not_quote"
    if text is not None and q in text:
        return "found"
    if text is not None and q.casefold() in text.casefold():
        return "found_case_differs"
    if q.casefold() in urllib.parse.unquote(url or "").casefold():
        return "found_in_url"
    if LABEL_RE.search(q):
        return "label_not_quote"
    if text is None:
        return "unresolved"
    return "not_found"


def collect_quotes(runs: list[dict]) -> dict[tuple[str, str], dict[str, set[str]]]:
    """(url, quote) -> {"contexts": where the ref sits, "ref_ids": SourceRef ids}."""
    pairs: dict[tuple[str, str], dict[str, set[str]]] = {}
    for run in runs:
        for path, d in walk(run):
            if is_ref(d) and isinstance(d.get("quote"), str) and d["quote"].strip():
                e = pairs.setdefault((d.get("url") or "", d["quote"]), {"contexts": set(), "ref_ids": set()})
                e["contexts"].add(ref_context(run, path))
                e["ref_ids"].add(str(d.get("id") or "?"))
    return pairs


def _quote_entry(url: str, quote: str, ctx: set[str], ref_ids: set[str]) -> dict:
    """A not-found quote for the output: ref ids, length and sha1, never the text unless --show-text."""
    e = {"ref_ids": sorted(href(r) for r in ref_ids)[:5], "url": hurl(url), "quote_len": len(quote),
         "quote_sha1": _h(quote), "contexts": sorted(ctx), "scoped": bool(ctx & QUOTE_SCOPE)}
    if SHOW_TEXT:
        e["quote"] = quote[:80]
    return e


def a2_quotes(runs: list[dict], idx: dict[str, str], n_files: int) -> Check:
    pairs = collect_quotes(runs)
    if not n_files:
        return Check("A2", "Quoted text is in the fetched item", f"{len(pairs)} unique quotes",
                     "no --cache-dir given", SKIP)
    cls, not_found, unresolved, scoped_unresolved = Counter(), [], set(), 0
    for (url, quote), e in pairs.items():
        c = classify_quote(url, quote, idx)
        cls[c] += 1
        if c == "not_found":
            not_found.append(_quote_entry(url, quote, e["contexts"], e["ref_ids"]))
        elif c == "unresolved":
            unresolved.add(hurl(url))
            scoped_unresolved += bool(e["contexts"] & QUOTE_SCOPE)
    scoped = [x for x in not_found if x["scoped"]]
    resolved = cls["found"] + cls["found_case_differs"] + cls["found_in_url"]
    order = ("found", "found_case_differs", "found_in_url", "label_not_quote", "unresolved", "not_found")
    result = ", ".join(f"{cls[k]} {k.replace('_', ' ')}" for k in order if cls[k])
    result += (f"; on facts, claims and eliminations: {len(scoped)} not found, "
               f"{scoped_unresolved} unresolved (URL not in the fetched files)")
    if scoped:
        status = FAIL
    elif not pairs:
        status = SKIP
    elif resolved == 0:
        status, result = SKIP, f"0 quotes resolved, check --cache-dir ({result})"
    else:
        status = PASS
    return Check("A2", "Quoted text is in the fetched item",
                 f"{len(pairs)} unique (URL, quote) pairs, {n_files} fetched files", result, status,
                 {"classes": dict(cls), "resolved": resolved, "scoped_unresolved": scoped_unresolved,
                  "failed": scoped, "not_found_other": [x for x in not_found if not x["scoped"]],
                  "unresolved_urls": sorted(unresolved)[:50]})


# ------------------------------------------------------------------------------------------ A3

def a3_eliminations(runs: list[dict]) -> Check:
    n, bad, cands = 0, [], set()
    for run in runs:
        rid = run_id(run)
        for cid, c in candidates(run):
            e = c.get("elimination")
            if not e:
                if c.get("status") == "eliminated":           # eliminated with no record of why
                    n += 1
                    cands.add(cid)
                    bad.append(f"{rid}:{hid(cid)}:no_elimination_record")
                continue
            n += 1
            cands.add(cid)
            r = next((x for x in c.get("results") or [] if x.get("criterion_id") == e.get("criterion_id")), None)
            problems = [name for name, ok in (
                ("round", e.get("round") in (1, 2, 3, 4)),
                ("criterion", bool(e.get("criterion_id"))),
                ("reason_en", bool(en(e.get("reason")).strip())),
                ("source", has_url(e.get("sources"))),
                ("result", r is not None),
                ("result_fail", bool(r) and r.get("status") == "fail"),   # unknown never eliminates
                ("value", bool(r) and bool(str(r.get("value") or "").strip())),
                ("threshold", bool(r) and bool(str(r.get("threshold") or "").strip())),
            ) if not ok]
            if problems:
                bad.append(f"{rid}:{hid(cid)}:{'+'.join(problems)}")
    return Check("A3", "Every elimination has round, criterion, value and source",
                 f"{n} eliminations ({_uniq(cands)})" if n else "0 eliminations",
                 f"{len(bad)} incomplete", PASS if n and not bad else (SKIP if not n else FAIL), {"failed": bad})


# ------------------------------------------------------------------------------------------ A5

def _signals_sourced(signals: list) -> bool:
    return any(isinstance(s, dict) and s.get("supports", True) and has_url([s.get("source") or {}])
               for s in signals or [])


def a5_identity(runs: list[dict]) -> Check:
    """A5a: every report carries an identity verdict; "matched" / "confirmed" / "likely" need a sourced signal."""
    n, bad, cands = Counter(), [], set()
    for run in runs:
        rid = run_id(run)
        for cid, _c, rep in reports(run):
            n["reports"] += 1
            cands.add(cid)
            pc = hid(cid)
            ident = [m for m in rep.get("identity") or [] if isinstance(m, dict)]
            verdict = rep.get("identity_verdict") if isinstance(rep.get("identity_verdict"), dict) else None
            if not ident and not (verdict and verdict.get("status")):
                bad.append(f"{rid}:{pc}:no_identity_verdict")
            for m in ident:
                n[f"entries {m.get('status')}"] += 1
                who = hhandle(m.get("platform"), m.get("handle"))
                if m.get("status") not in ("matched", "uncertain", "rejected"):
                    bad.append(f"{rid}:{pc}:{who}:bad_status")
                if m.get("status") == "matched" and not _signals_sourced(m.get("signals")):
                    bad.append(f"{rid}:{pc}:{who}:matched_without_source")
            if verdict:
                n[f"verdict {verdict.get('status')}"] += 1
                if verdict.get("status") in ("confirmed", "likely") and not _signals_sourced(verdict.get("supporting")):
                    bad.append(f"{rid}:{pc}:verdict_{verdict.get('status')}_without_source")
    sample = f"{n['reports']} reports ({_uniq(cands)})" if n["reports"] else "0 reports"
    counts = ", ".join(f"{v} {k}" for k, v in sorted(n.items()) if k != "reports")
    result = f"{len(bad)} missing or unsupported" + (f" ({counts})" if counts else "")
    return Check("A5a", "Identity verdict present", sample, result,
                 PASS if n["reports"] and not bad else (SKIP if not n["reports"] else FAIL), {"failed": bad})


def _wrong_anchor_ok(rep: dict) -> tuple[bool, str]:
    """(rejected the wrong anchor?, short label). With a verdict line: uncertain / not_found and the anchor
    mismatch named. With only the identity list: non-empty, nothing matched, at least one entry uncertain
    or rejected, and at least one signal that speaks against the match (supports: False)."""
    ident = [m for m in rep.get("identity") or [] if isinstance(m, dict)]
    verdict = rep.get("identity_verdict") if isinstance(rep.get("identity_verdict"), dict) else None
    if verdict:
        named = bool(verdict.get("contradicting")) or "anchor" in en(verdict.get("text")).lower()
        return verdict.get("status") in ("uncertain", "not_found") and named, f"verdict {verdict.get('status')}"
    if not ident:
        return False, "empty identity list"
    matched = any(m.get("status") == "matched" for m in ident)
    doubted = any(m.get("status") in ("uncertain", "rejected") for m in ident)
    against = any(isinstance(s, dict) and s.get("supports") is False for m in ident for s in m.get("signals") or [])
    label = "matched" if matched else ("no signal against" if not against else "not matched")
    return (not matched and doubted and against), label


def a5b_wrong_anchor(wrong_anchor: list[dict]) -> Check:
    name = "Wrong anchor not matched"
    if not wrong_anchor:
        return Check("A5b", name, "-", "no wrong-anchor run given", SKIP)
    bad, wa = [], []
    for run in wrong_anchor:
        reps = list(reports(run))
        if not reps:                                   # a wrong-anchor run must produce a report to judge
            bad.append(f"{run_id(run)}:no_report")
            continue
        for cid, _c, rep in reps:
            ok, label = _wrong_anchor_ok(rep)
            wa.append(f"{run_id(run)}:{hid(cid)}:{label}" + ("" if ok else ":WRONG_ANCHOR_ACCEPTED"))
            if not ok:
                bad.append(wa[-1])
    return Check("A5b", name, f"{len(wrong_anchor)} wrong-anchor run(s), {len(wa)} report(s)",
                 f"{len(wa) - sum(1 for x in wa if x.endswith('ACCEPTED'))} of {len(wa)} reports reject the anchor"
                 + (f"; {len(bad)} failing" if bad else ""),
                 PASS if wa and not bad else FAIL, {"failed": bad, "wrong_anchor": wa})


# ------------------------------------------------------------------------------------------ A6

def a6_labels(runs: list[dict]) -> Check:
    modes, bad, mock_platforms, unique = Counter(), [], set(), set()
    for run in runs:
        for path, d in walk(run):
            if is_ref(d):
                m = d.get("mode")
                modes[m if m in MODES else "unlabeled"] += 1
                unique.add((d.get("id"), url_key(d.get("url") or "")))
                if m not in MODES:
                    bad.append(f"{run_id(run)}:{pstr(path)}")
                if m == "mock":
                    mock_platforms.add(d.get("platform"))
    total = sum(modes.values())
    result = ", ".join(f"{modes[k]} {k}" for k in (*MODES, "unlabeled") if modes[k] or k in MODES)
    if mock_platforms:
        result += f" (mock on: {', '.join(sorted(map(str, mock_platforms)))})"
    return Check("A6", "Every source labeled live, cache or mock",
                 f"{total} source reference occurrences ({len(unique)} unique by id and URL)", result,
                 PASS if total and not bad else (SKIP if not total else FAIL),
                 {"failed": bad[:200], "modes": dict(modes), "unique_refs": len(unique),
                  "mock_platforms": sorted(map(str, mock_platforms))})


# ------------------------------------------------------------------------------------------ A7

def _redacted(v: Any) -> bool:
    if v is None or (isinstance(v, str) and v.strip() in REDACTED_VALUES):
        return True
    if isinstance(v, dict):
        return all(_redacted(x) for x in v.values())
    if isinstance(v, list):
        return all(_redacted(x) for x in v)
    return False


def forbidden_keys(data: Any, where: str) -> list[str]:
    return [f"{where}:{pstr(p)}.{k}" for p, d in walk(data) for k in d
            if isinstance(k, str) and (k in FORBIDDEN_KEYS or FORBIDDEN_RE.search(k))]


def comment_dicts(data: Any) -> Iterator[tuple[tuple, dict]]:
    """Stored comments: normalized cache files (meta.method == comments), lists under comment keys in raw
    actor items, and Comment-shaped dicts (post_url + text) anywhere."""
    seen: set[int] = set()

    def once(p: tuple, c: dict) -> Iterator[tuple[tuple, dict]]:
        if id(c) not in seen:
            seen.add(id(c))
            yield p, c
    if isinstance(data, dict) and (data.get("meta") or {}).get("method") == "comments":
        for i, it in enumerate(data.get("items") or []):
            if isinstance(it, dict):
                yield from once(("items", i), it)
    for p, o in walk(data):
        if "post_url" in o and "text" in o:
            yield from once(p, o)
        for key in COMMENT_LIST_KEYS:
            if isinstance(o.get(key), list):
                for i, c in enumerate(o[key]):
                    if isinstance(c, dict):
                        yield from once(p + (key, i), c)


def commenter_hits(data: Any, where: str) -> list[str]:
    hits = set()
    for p, c in comment_dicts(data):
        for k in COMMENTER_KEYS:
            if k in c and not _redacted(c[k]):
                hits.add(f"{where}:{pstr(p)}.{k}")
    return sorted(hits)


def a7_hard_lines(runs: list[dict], cache_dirs: list[str]) -> Check:
    score, ident, n_files, n_comments = [], [], 0, 0
    for run in runs:
        score += forbidden_keys(run, run_id(run))
        ident += commenter_hits(run, run_id(run))
    for f, data in _load_dir_json(cache_dirs):
        n_files += 1
        if isinstance(data, dict) and "meta" in data and "items" in data:   # our normalized cache files
            score += forbidden_keys(data, f.name)
        n_comments += sum(1 for _ in comment_dicts(data))
        ident += commenter_hits(data, f.name)
    result = f"{len(score)} score or trait keys, {len(ident)} commenter identity values"
    measured = n_files or any(True for run in runs for _ in candidates(run))   # empty runs measure nothing
    return Check("A7", "No score fields, no commenter identities stored",
                 f"{len(runs)} run snapshots, {n_files} fetched files, {n_comments} stored comments", result,
                 FAIL if score or ident else (PASS if measured else SKIP),
                 {"failed": (score + ident)[:200], "score_keys": score[:100], "commenter_identity": ident[:100]})


# ------------------------------------------------------------------------------------------ A4

def _by_id(items: list, key: str = "id") -> dict:
    return {x.get(key): x for x in items or [] if isinstance(x, dict)}


def candidate_diff(a: dict, b: dict) -> dict:
    ra, rb = a.get("report") or {}, b.get("report") or {}
    fa, fb = _by_id(ra.get("findings")), _by_id(rb.get("findings"))
    changed_text = [i for i in fa.keys() & fb.keys()
                    if (fa[i].get("kind"), en(fa[i].get("text"))) != (fb[i].get("kind"), en(fb[i].get("text")))]
    tiers = [i for i in fa.keys() & fb.keys() if fa[i].get("tier") != fb[i].get("tier")]
    qa = {en(q) for q in ra.get("questions") or []}
    qb = {en(q) for q in rb.get("questions") or []}
    ca, cb = _by_id(ra.get("claims")), _by_id(rb.get("claims"))
    claims = [i for i in ca.keys() | cb.keys() if (ca.get(i) or {}).get("status") != (cb.get(i) or {}).get("status")]
    ea, eb = _by_id(ra.get("collab_timeline")), _by_id(rb.get("collab_timeline"))
    comp = [i for i in ea.keys() & eb.keys() if ea[i].get("is_competitor") != eb[i].get("is_competitor")]
    sa = {r.get("criterion_id"): r.get("status") for r in a.get("results") or []}
    sb = {r.get("criterion_id"): r.get("status") for r in b.get("results") or []}
    results = [k for k in sa.keys() | sb.keys() if sa.get(k) != sb.get(k)]
    return {"findings_added": sorted(fb.keys() - fa.keys()), "findings_removed": sorted(fa.keys() - fb.keys()),
            "findings_changed": sorted(changed_text), "tiers_changed": sorted(tiers),
            "facts_changed_text": sorted(i for i in changed_text if fb[i].get("kind") == "fact"),
            "questions_added": len(qb - qa), "questions_removed": len(qa - qb),
            "claim_statuses_changed": sorted(claims), "competitor_flags_changed": sorted(comp),
            "criterion_results_changed": sorted(results)}


def _app_diff_ids(d: dict) -> set:
    return set(d.get("added") or []) | set(d.get("removed") or [])


def a4_from_snapshots(before: dict, after: dict) -> Check:
    per, mism = {}, []
    totals = Counter()
    for cid in sorted(before.get("candidates", {}).keys() & after.get("candidates", {}).keys()):
        a, b = before["candidates"][cid], after["candidates"][cid]
        d = candidate_diff(a, b)
        f_n = len(d["findings_added"]) + len(d["findings_removed"]) + len(d["findings_changed"]) + len(d["tiers_changed"])
        q_n = d["questions_added"] + d["questions_removed"]
        totals["findings"] += f_n
        totals["questions"] += q_n
        totals["claim statuses"] += len(d["claim_statuses_changed"])
        totals["competitor flags"] += len(d["competitor_flags_changed"])
        totals["criterion results"] += len(d["criterion_results_changed"])
        totals["facts changed text"] += len(d["facts_changed_text"])
        if any(v for v in d.values()):
            per[hid(cid)] = d
        app = (b.get("report") or {}).get("last_diff")
        if isinstance(app, dict):
            mine = set(d["findings_added"]) | set(d["findings_removed"])
            mine |= {i for i in (_by_id((b.get("report") or {}).get("claims")).keys()
                                 ^ _by_id((a.get("report") or {}).get("claims")).keys())}
            if _app_diff_ids(app) != mine:
                mism.append({"candidate": hid(cid), "app": sorted(_app_diff_ids(app)), "script": sorted(mine)})
    alive = lambda r: {k for k, c in r.get("candidates", {}).items() if c.get("status") != "eliminated"}
    funnel = len(alive(before) ^ alive(after))
    same_run = before.get("id") == after.get("id")
    log_a, log_b = before.get("log") or [], after.get("log") or []
    live = [x for x in log_b[len(log_a):] if isinstance(x, dict) and x.get("mode") == "live"] if same_run else []
    ok = (totals["findings"] or totals["questions"]) and totals["criterion results"] and not live
    result = (f"differ: {totals['findings']} findings, {totals['questions']} questions, "
              f"{totals['claim statuses']} claim statuses, {totals['competitor flags']} competitor flags, "
              f"{totals['criterion results']} criterion results; funnel {funnel}; "
              + (f"live fetches during switch {len(live)}" if same_run else "different run ids, live fetches not compared")
              + (f"; app diff mismatches {len(mism)}" if mism else ""))
    n_reports = sum(1 for c in after.get("candidates", {}).values() if c.get("report"))
    return Check("A4", "Switching the goal changes the report",
                 f"{len(before.get('candidates', {}).keys() & after.get('candidates', {}).keys())} candidates, "
                 f"{n_reports} reports, 2 snapshots", result,
                 FAIL if not ok else (PASS if same_run else PASS_NO_LIVE),
                 {"per_candidate": per, "app_diff_mismatches": mism, "facts_changed_text": totals["facts changed text"],
                  "live_fetches": len(live), "funnel_changed": funnel})


def extract_report_diffs(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("report_diffs"), list):
            return [d for d in data["report_diffs"] if isinstance(d, dict)]
        if "added" in data and "removed" in data:
            return [data]
        if is_run(data):
            return [r["last_diff"] for _c, _x, r in reports(data) if isinstance(r.get("last_diff"), dict)]
    return []


def _n(v: Any) -> int:
    return len(v) if isinstance(v, list) else int(v or 0)


def a4_from_report_diff(diffs: list[dict]) -> Check:
    t = Counter()
    for d in diffs:
        t["findings"] += sum(_n(d.get(k)) for k in ("added", "removed", "moved_up", "moved_down"))
        t["questions"] += _n(d.get("questions_added")) + _n(d.get("questions_removed"))
        t["claim statuses"] += _n(d.get("claims_changed"))
        t["criterion results"] += _n(d.get("checks_changed"))
    ok = diffs and (t["findings"] or t["questions"]) and t["criterion results"]
    return Check("A4", "Switching the goal changes the report", f"{len(diffs)} report_diff(s)",
                 f"differ: {t['findings']} findings, {t['questions']} questions, {t['claim statuses']} claim statuses, "
                 f"{t['criterion results']} criterion results; live fetches not measurable from a report_diff",
                 PASS_NO_LIVE if ok else FAIL, {"totals": dict(t)})


def a4_goal(paths: list[str]) -> Check:
    if len(paths) == 2:
        a, b = _read_json(Path(paths[0])), _read_json(Path(paths[1]))
        if is_run(a) and is_run(b):
            return a4_from_snapshots(a, b)
        return a4_from_report_diff(extract_report_diffs(b) or extract_report_diffs(a))
    return a4_from_report_diff(extract_report_diffs(_read_json(Path(paths[0]))))


# ------------------------------------------------------------------------------------------ subject mode

def subject_checks(runs: list[dict]) -> list[Check]:
    note = "field absent (subject-mode branch not merged)"
    reps = [(run_id(run), cid, rep) for run in runs for cid, _c, rep in reports(run)]
    out = []

    findings = [(r, c, f) for r, c, rep in reps for f in rep.get("findings") or []]
    if any(f.get("confidence") is not None for _r, _c, f in findings):
        bad = [f"{r}:{hid(c)}:{f.get('id')}" for r, c, f in findings
               if f.get("confidence") not in ("high", "medium", "low") or not en(f.get("confidence_basis")).strip()]
        out.append(Check("SM1", "Confidence on every finding", f"{len(findings)} findings",
                         f"{len(bad)} without confidence or basis", PASS if not bad else FAIL, {"failed": bad}))
    else:
        out.append(Check("SM1", "Confidence on every finding", f"{len(findings)} findings", note, SKIP))

    if any(isinstance(rep.get("identity_verdict"), dict) for _r, _c, rep in reps):
        bad = []
        for r, c, rep in reps:
            v = rep.get("identity_verdict")
            if not isinstance(v, dict) or v.get("status") not in ("confirmed", "likely", "uncertain", "not_found") \
                    or not en(v.get("text")).strip():
                bad.append(f"{r}:{hid(c)}")
        out.append(Check("SM2", "Identity verdict line on every report", f"{len(reps)} reports",
                         f"{len(bad)} without a verdict line", PASS if not bad else FAIL, {"failed": bad}))
    else:
        out.append(Check("SM2", "Identity verdict line on every report", f"{len(reps)} reports", note, SKIP))

    diffs = [(r, c, rep, rep["last_diff"]) for r, c, rep in reps if isinstance(rep.get("last_diff"), dict)]
    if diffs:
        bad = []
        for r, c, rep, d in diffs:
            current = set(_by_id(rep.get("findings"))) | set(_by_id(rep.get("claims")))
            shown = set(d.get("added") or []) | set(d.get("moved_up") or []) | set(d.get("moved_down") or [])
            if not shown <= current or set(d.get("removed") or []) & current or not en(d.get("summary")).strip():
                bad.append(f"{r}:{hid(c)}")
        out.append(Check("SM3", "Report diff consistent with the report", f"{len(diffs)} report diffs",
                         f"{len(bad)} inconsistent", PASS if not bad else FAIL, {"failed": bad}))
    else:
        out.append(Check("SM3", "Report diff consistent with the report", f"{len(reps)} reports",
                         "no report_diff present (no goal switch, or " + note + ")", SKIP))
    return out


# ------------------------------------------------------------------------------------------ A0

def synthetic_fixture() -> tuple[dict, list[dict]]:
    """A tiny made-up run (no real people) and the fetched cache file it was built from."""
    t = "2026-10-09T00:00:00Z"
    bio = "Pečeme kváskový chleba každé ráno v Brně, Veveří 12. Spolupráce: hello@example.test"
    cap = "Nový kváskový croissant je tady, přijďte ochutnat na Veveří! #brnofood"

    def ref(rid, url, quote, mode="live"):
        return {"id": rid, "url": url, "platform": "instagram", "actor": "apify/test", "fetched_at": t,
                "mode": mode, "quote": quote}
    p_url, post_url = "https://www.instagram.com/example_baker/", "https://www.instagram.com/p/EXAMPLE1/"
    e_url = "https://www.instagram.com/example_small/"
    e_bio = "Malý účet o jídle v Brně a okolí, recepty a tipy na kavárny"
    fin = {
        "id": "instagram:example_baker", "status": "finalist", "elimination": None,
        "ref": {"handle": "example_baker", "platform": "instagram", "found_via": ["search:pekárna brno"],
                "source": ref("disc:1", p_url, "search:pekárna brno")},
        "results": [{"criterion_id": "followers_range", "status": "pass", "value": "12 000 sledujících",
                     "threshold": "5–50 tis.", "sources": [ref("ig:profile:example_baker", p_url, bio)]}],
        "report": {
            "candidate_id": "instagram:example_baker",
            "findings": [
                {"id": "f:followers", "kind": "fact", "text": {"cs": "12 000", "en": "12,000 followers"},
                 "sources": [ref("ig:profile:example_baker", p_url, bio)], "based_on": [], "section": "profile"},
                {"id": "f:post", "kind": "fact", "text": {"cs": "croissant", "en": "Posts about croissants"},
                 "sources": [ref("ig:post:EXAMPLE1", post_url, cap)], "based_on": [], "section": "content"},
                {"id": "i:local", "kind": "inference", "text": {"cs": "lokální", "en": "Likely local"},
                 "sources": [], "based_on": ["f:followers", "f:post"], "section": "profile"},
                {"id": "g:audience", "kind": "gap", "text": {"cs": "publikum", "en": "Audience not public"},
                 "sources": [], "based_on": [], "section": "engagement"}],
            "claims": [], "collab_timeline": [], "news": [],
            "identity": [{"handle": "example_baker", "platform": "tiktok", "status": "matched",
                          "signals": [{"signal": "bio links", "supports": True,
                                       "source": ref("ig:profile:example_baker", p_url, "Veveří 12")}]}],
            "questions": [{"cs": "?", "en": "Do you bake on weekends?"}], "outreach_draft": None,
            "not_checked": [], "skeptic_notes": [], "sensitive_filtered": 0}}
    elim = {
        "id": "instagram:example_small", "status": "eliminated",
        "ref": {"handle": "example_small", "platform": "instagram", "found_via": ["hashtag:brnofood"],
                "source": ref("disc:2", post_url, "#brnofood")},
        "results": [{"criterion_id": "followers_range", "status": "fail", "value": "800 sledujících",
                     "threshold": "5–50 tis.", "sources": [ref("ig:profile:example_small", e_url, e_bio)]}],
        "elimination": {"round": 1, "criterion_id": "followers_range",
                        "reason": {"cs": "Kolo 1: 800", "en": "Round 1: only 800 followers"},
                        "sources": [ref("ig:profile:example_small", e_url, e_bio)]},
        "report": None}
    run = {"id": "r_selftest", "criteria": {"brief": {"business_type": "bakery"}, "criteria": []},
           "candidates": {fin["id"]: fin, elim["id"]: elim}, "rounds": [], "log": [],
           "mode_summary": {"live": 1, "cache": 0, "mock": 0}}
    cache = [{"meta": {"provider": "apify", "method": "profiles", "fetched_at": t},
              "items": [{"handle": "example_baker", "platform": "instagram", "url": p_url, "bio": bio,
                         "latest_posts": [{"id": "ig:post:EXAMPLE1", "url": post_url, "caption": cap,
                                           "hashtags": ["brnofood"], "source": ref("ig:post:EXAMPLE1", post_url, None)}],
                         "source": ref("ig:profile:example_baker", p_url, None)},
                        {"handle": "example_small", "platform": "instagram", "url": e_url, "bio": e_bio,
                         "latest_posts": [], "source": ref("ig:profile:example_small", e_url, None)}]}]
    return run, cache


def plant_defects(run: dict, idx: dict[str, str]) -> tuple[dict, dict] | None:
    """Copy of ``run`` with 3 defects, or None when the run lacks a fact, an elimination or a found quote."""
    planted = copy.deepcopy(run)
    quote_path = None
    for path, d in walk(planted):          # defect 3 target: a found quote on a fact, claim or elimination
        if (is_ref(d) and len(d.get("quote") or "") > 20 and ref_context(planted, path) in QUOTE_SCOPE
                and not LABEL_RE.search(norm_quote(d["quote"]))
                and classify_quote(d["url"], d["quote"], idx) == "found"):
            quote_path = path
            break
    victim = next((c for _cid, c in candidates(planted) if c.get("elimination") and any(
        r.get("criterion_id") == c["elimination"].get("criterion_id") and r.get("status") == "fail"
        for r in c.get("results") or [])), None)
    fact = None
    for _cid, _c, rep in reports(planted):
        for i, f in enumerate(rep.get("findings") or []):
            if f.get("kind") == "fact" and has_url(f.get("sources")):
                p = ("candidates", _cid, "report", "findings", i)
                if quote_path is None or quote_path[: len(p)] != p:
                    fact = f
                    break
        if fact:
            break
    if quote_path is None or victim is None or fact is None:
        return None
    ref = get_at(planted, quote_path)
    q = ref["quote"].rstrip("…").rstrip()
    ref["quote"] = q[:-6] + "XXXXXX"                                     # defect 3: altered quote
    fact["sources"] = []                                                 # defect 1: fact without a source
    next(r for r in victim["results"] if r.get("criterion_id") == victim["elimination"]["criterion_id"])["value"] = ""
    return planted, {"fact": fact.get("id"), "elimination": hid(victim.get("id")),
                     "quote_at": pstr(quote_path)}                     # defect 2: failing result with empty value


def selftest(runs: list[dict], idx: dict[str, str]) -> Check:
    base, used_idx, planted = None, idx, None
    for run in runs:
        got = plant_defects(run, idx)
        if got:
            base, (planted, where) = run, got
            break
    if base is None:
        base, cache = synthetic_fixture()
        used_idx = index_from_data(cache)                  # the same index builder as --cache-dir
        planted, where = plant_defects(base, used_idx)  # type: ignore[misc]
    def scoped_nf(r):
        return len(a2_quotes([r], used_idx, 1).details.get("failed", []))
    found = {
        "fact without source": len(a1_sources([planted]).details["failed"]) > len(a1_sources([base]).details["failed"]),
        "elimination result without value":
            len(a3_eliminations([planted]).details["failed"]) > len(a3_eliminations([base]).details["failed"]),
        "altered quote": scoped_nf(planted) > scoped_nf(base),
    }
    n = sum(found.values())
    return Check("A0", "Checker finds planted defects", f"3 planted defects in a copy of {run_id(base)}",
                 f"{n} of 3 found", PASS if n == 3 else FAIL,
                 {"found": found, "planted": where, "base_run": run_id(base),
                  "missed": [k for k, v in found.items() if not v]})


# ------------------------------------------------------------------------------------------ output

def table(checks: list[Check]) -> str:
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    rows = ["| Check | Sample size | Result | Pass/fail |", "|---|---|---|---|"]
    rows += [f"| {c.id} {esc(c.name)} | {esc(c.sample)} | {esc(c.result)} | {c.status} |" for c in checks]
    return "\n".join(rows)


def details_text(checks: list[Check], limit: int = 10) -> str:
    out = []
    for c in checks:
        failed = c.details.get("failed") or []
        if c.status == FAIL and failed:
            out.append(f"{c.id} failures ({len(failed)}, first {min(limit, len(failed))}):")
            out += [f"  - {json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else x}" for x in failed[:limit]]
        if c.id == "A0" and c.details.get("missed"):
            out.append(f"A0 missed: {', '.join(c.details['missed'])}")
        if c.id == "A2" and c.details.get("not_found_other"):
            out.append(f"A2 not found outside facts, claims and eliminations: {len(c.details['not_found_other'])} "
                       f"(reported, not a fail): "
                       + "; ".join(f"{x['contexts']} {','.join(x['ref_ids'])} len {x['quote_len']} sha1 {x['quote_sha1']}"
                                   + (f" {x['quote'][:50]!r}" if 'quote' in x else "")
                                   for x in c.details["not_found_other"][:limit]))
    return "\n".join(out)


def replay_notes(runs: list[dict]) -> list[str]:
    """Runs that only replay another given run from cache (all sources cache, every candidate also in the
    other run). Their candidates are counted twice in every sample size."""
    notes = []
    info = []
    for run in runs:
        modes = {d.get("mode") for _p, d in walk(run) if is_ref(d)}
        info.append((run, set(run.get("candidates") or {}), modes))
    for j, (b, cb, mb) in enumerate(info):
        if not cb or mb != {"cache"}:
            continue
        for i, (a, ca, ma) in enumerate(info):
            if a is b or not cb <= ca or (ma == {"cache"} and i > j):
                continue
            notes.append(f"{run_id(b)} looks like a cache replay of {run_id(a)} ({len(cb)} of {len(cb)} candidates "
                         f"overlap, all sources cache): sample sizes count these candidates twice. "
                         f"Leave it out of the README table.")
            break
    return notes


def _json_path(raw: str) -> Path:
    """--json target, always under data/validation/ (gitignored): a bare name goes there, any other
    path must resolve inside it."""
    p = Path(raw)
    if not p.is_absolute() and len(p.parts) == 1:
        p = VALIDATION_DIR / p
    p = p.resolve()
    root = VALIDATION_DIR.resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"--json must write under {VALIDATION_DIR} (gitignored), got {raw}")
    return p


def main(argv: list[str] | None = None) -> int:
    global SHOW_TEXT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="backend base URL, e.g. http://127.0.0.1:8040")
    ap.add_argument("--run", action="append", default=[], help="run id to fetch from --base (repeatable)")
    ap.add_argument("--all-runs", action="store_true", help="fetch every run listed by GET /api/runs")
    ap.add_argument("--file", action="append", default=[], help="run snapshot JSON, or a dir of them (repeatable)")
    ap.add_argument("--cache-dir", action="append", default=[],
                    help="dir of fetched items: data/cache, data/live-run/cache, data/live-tests (repeatable)")
    ap.add_argument("--diff", nargs="+", metavar="JSON", help="A4: two run snapshots (before, after) or a report_diff")
    ap.add_argument("--wrong-anchor", action="append", default=[], help="A5: run snapshot made with a wrong anchor")
    ap.add_argument("--self-test", action="store_true", help="A0: plant 3 defects and require all 3 found")
    ap.add_argument("--json", nargs="?", const="validate_run.json", metavar="NAME",
                    help="also write the full results (masked failing ids) under data/validation/ "
                         "(default name validate_run.json)")
    ap.add_argument("--show-text", action="store_true",
                    help="print handles, URLs and quote text in clear (local debugging; never for the README)")
    a = ap.parse_args(argv)
    SHOW_TEXT = bool(a.show_text)
    if (a.run or a.all_runs) and not a.base:
        ap.error("--run / --all-runs need --base")
    if a.diff and len(a.diff) > 2:
        ap.error("--diff takes one report_diff file or two run snapshots")
    json_out = None
    if a.json:
        try:
            json_out = _json_path(a.json)
        except ValueError as e:
            ap.error(str(e))

    try:
        runs = load_runs(a.file, a.base, a.run, a.all_runs)
        wrong = load_runs(a.wrong_anchor, None, [], False)
    except (OSError, ValueError, KeyError, urllib.error.URLError) as e:
        print(f"error: cannot load runs: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if not runs and not a.diff and not a.self_test and not wrong:
        ap.error("nothing to check: give --file, --base with --run / --all-runs, --diff or --self-test")
    idx, n_files = build_index(a.cache_dir)

    checks: list[Check] = []
    if a.self_test:
        checks.append(selftest(runs, idx))
    if runs or wrong:
        checks += [a1_sources(runs), a2_quotes(runs, idx, n_files), a3_eliminations(runs)]
    if a.diff:
        try:
            checks.append(a4_goal(a.diff))
        except (OSError, ValueError) as e:
            print(f"error: cannot read --diff input: {type(e).__name__}: {e}", file=sys.stderr)
            return 2
    elif runs:
        checks.append(Check("A4", "Switching the goal changes the report", "-", "not run (needs --diff)", SKIP))
    if runs or wrong:
        checks += [a5_identity(runs), a5b_wrong_anchor(wrong), a6_labels(runs), a7_hard_lines(runs, a.cache_dir)]
        checks += subject_checks(runs)
    nothing = bool(runs or wrong) and all(c.status == SKIP for c in checks if c.id in MEASURED)

    print(table(checks))
    if runs:
        modes = Counter()
        for run in runs:
            modes.update({k: v for k, v in (run.get("mode_summary") or {}).items() if isinstance(v, int)})
        uniq = {cid for run in runs for cid, _c in candidates(run)}
        print(f"\nRuns: {', '.join(run_id(r) for r in runs)} ({len(uniq)} unique candidates). Run mode summary: "
              + ", ".join(f"{k} {modes[k]}" for k in MODES) + "."
              + (f" Fetched items: {n_files} files in {', '.join(a.cache_dir)}." if a.cache_dir else ""))
        for note in replay_notes(runs):
            print(f"Note: {note}")
        a6 = next((c for c in checks if c.id == "A6"), None)
        if a6 and a6.details.get("modes") and set(a6.details["modes"]) <= {"mock"}:
            print("All sources are mock: this tests the checker only, it is not validation.")
    a4 = next((c for c in checks if c.id == "A4"), None)
    if a4 and a4.status == PASS_NO_LIVE:
        print("\nA4: the plan's '0 live fetches during the switch' was not measured; say so in the README.")
    if nothing:
        print("\nnothing measured: A1, A2, A3, A5a, A5b and A6 were all skipped on the given runs")
    extra = details_text(checks)
    if extra:
        print("\n" + extra)
    if json_out:
        try:
            json_out.parent.mkdir(parents=True, exist_ok=True)
            json_out.write_text(json.dumps([c.__dict__ for c in checks], ensure_ascii=False, indent=1, default=list))
        except OSError as e:
            print(f"error: cannot write {json_out}: {e}", file=sys.stderr)
            return 2
    return 1 if nothing or any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
