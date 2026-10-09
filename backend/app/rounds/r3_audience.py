"""Round 3: audience (public signals only). prepare: provider.comments() only for the given (active)
candidates, last 3-5 posts; llm.sensitive.filter_comments BEFORE use; compute cs_comment_share,
generic_comment_share, comments_analyzed into metrics; comment texts are NOT stored on the candidate
(no commenter identity ever). local_signals from metrics.
evaluate kinds: min_engagement, cs_comment_share, local_signal, max_generic_comments.
Audience age / gender / origin are never estimated."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime

from app.compute.metrics import comment_stats, local_signals
from app.events import Emit
from app.llm import sensitive
from app.models import Brief, Candidate, Comment, Criterion, CriterionResult, Post, Run, i18n
from app.rounds.common import (
    llm_actor,
    Outcome,
    actor_of,
    add_sensitive,
    count_modes,
    cs_plural,
    describe_modes,
    fmt_int,
    fmt_pct,
    log,
    newest_first,
    param,
    post_ref,
    posts_of,
    profile_refs,
    tr,
    unknown,
)
from app.sources.base import SourceProvider

ROUND = 3
COMMENT_POSTS = 5     # last N posts whose comments are fetched
COMMENTS_PER_POST = 15

AUDIENCE_NOTE = i18n("odhad z veřejných dat, ne demografie", "estimate from public data, not demographics")


def _norm_url(url: str) -> str:
    u = (url or "").strip().lower().split("?")[0].split("#")[0].rstrip("/")
    return u.removeprefix("https://").removeprefix("http://").removeprefix("www.")


def _url_keys(url: str) -> list[str]:
    """Full normalized URL plus the last path segment (IG shortcode / TikTok video id), so
    ".../p/CODE/" and ".../reel/CODE" from different actors still match."""
    full = _norm_url(url)
    last = full.rsplit("/", 1)[-1] if "/" in full else ""
    return [full] + ([f"id:{last}"] if len(last) >= 5 else [])


def comment_posts(candidate: Candidate) -> list[Post]:
    """The last COMMENT_POSTS posts (newest first) whose comments we read; posts with 0 comments
    are skipped."""
    posts = [p for p in newest_first(posts_of(candidate)) if p.comments != 0]
    return posts[:COMMENT_POSTS]


def needs_comments(candidate: Candidate) -> bool:
    """True only when comments were never requested for this candidate. "Fetched, but nothing came
    back / everything was filtered" is not a reason to fetch (and pay) again."""
    m = candidate.metrics
    if candidate.profile is None or m is None:
        return False
    if m.comments_fetched or m.comments_analyzed > 0:
        return False
    return bool(comment_posts(candidate))


async def prepare(run: Run, candidates: list[Candidate], provider: SourceProvider, emit: Emit) -> None:
    todo = [c for c in candidates if c.profile is not None and c.metrics is not None and c.id in run.candidates]
    url_owner: dict[str, str] = {}
    urls: list[str] = []
    for c in todo:
        for p in comment_posts(c):
            keys = _url_keys(p.url)
            if not keys[0] or keys[0] in url_owner:
                continue
            for k in keys:
                url_owner.setdefault(k, c.id)
            urls.append(p.url)
    if not urls:
        return
    comments = await provider.comments(urls, per_post=COMMENTS_PER_POST)
    todo = [c for c in todo if comment_posts(c)]
    batch = count_modes(run, comments)
    mode, suffix = describe_modes(batch)
    n = len(comments)
    await log(run, emit, tr(
        run,
        f"Komentáře: {n} {cs_plural(n, 'komentář', 'komentáře', 'komentářů')} z {len(urls)} {cs_plural(len(urls), 'postu', 'postů', 'postů')} "
        f"pro {len(todo)} {cs_plural(len(todo), 'účet', 'účty', 'účtů')}{suffix}; autoři se neukládají.",
        f"Comments: {n} {'comment' if n == 1 else 'comments'} from {len(urls)} posts for {len(todo)} accounts{suffix}; authors are not stored.",
    ), actor=actor_of(comments, provider.name), mode=mode)

    grouped: dict[str, list[Comment]] = defaultdict(list)
    for cm in comments:
        owner = next((url_owner[k] for k in _url_keys(cm.post_url) if k in url_owner), None)
        if owner:
            grouped[owner].append(cm)

    sem = asyncio.Semaphore(8)

    async def one(c: Candidate) -> int:
        raw = grouped.get(c.id, [])
        # A refetch replaces this round's sensitive count instead of adding to it.
        prev = c.metrics.comments_sensitive if c.metrics else 0
        if prev:
            c.sensitive_filtered = max(0, c.sensitive_filtered - prev)
        dropped = 0
        kept: list[Comment] = []
        if raw:
            async with sem:
                kept, dropped = await sensitive.filter_comments(raw)
            await add_sensitive(run, c, emit, dropped)
        cs_share, gen_share, n_comments = comment_stats(kept)
        # Only aggregates are stored; the comment texts are dropped right here.
        c.metrics = c.metrics.model_copy(update={  # type: ignore[union-attr]
            "cs_comment_share": cs_share,
            "generic_comment_share": gen_share,
            "comments_analyzed": n_comments,
            "comments_fetched": True,
            "comments_sensitive": dropped,
        })
        return dropped

    total = sum(await asyncio.gather(*(one(c) for c in todo)))
    if total:
        await log(run, emit, tr(
            run,
            f"Citlivý filtr: vynecháno {total} {cs_plural(total, 'komentář', 'komentáře', 'komentářů')} (jen počet).",
            f"Sensitive filter: {total} {'comment' if total == 1 else 'comments'} left out (count only).",
        ), actor=llm_actor(run, "sensitive"))


# ---------------------------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------------------------

def _comment_sources(c: Candidate) -> list:
    return [post_ref(p) for p in comment_posts(c)] or profile_refs(c)


def _assess_engagement(criterion: Criterion, c: Candidate) -> Outcome:
    min_rate = float(param(criterion, "min_rate") or 0.0)
    th = i18n(f"aspoň {fmt_pct(min_rate, 'cs', 1)}", f"at least {fmt_pct(min_rate, 'en', 1)}")
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    rate = c.metrics.engagement_rate if c.metrics else None
    if rate is None:
        return unknown("lajky skryté nebo neznámý počet sledujících", "likes hidden or follower count unknown", th, profile_refs(c))
    n = c.metrics.posts_analyzed if c.metrics else 0
    value = i18n(f"medián interakcí {fmt_pct(rate, 'cs', 1)} sledujících na post ({n} postů)",
                 f"median interactions {fmt_pct(rate, 'en', 1)} of followers per post ({n} posts)")
    sources = profile_refs(c) + [post_ref(p) for p in newest_first(posts_of(c))[:3]]
    if rate < min_rate:
        return Outcome("fail", value, th, sources, reason=i18n(
            f"medián interakcí jen {fmt_pct(rate, 'cs', 1)} sledujících na post",
            f"median interactions only {fmt_pct(rate, 'en', 1)} of followers per post"))
    return Outcome("pass", value, th, sources)


def _no_comment_value(c: Candidate) -> tuple[str, str]:
    if c.metrics is None or c.metrics.comments_analyzed == 0:
        if needs_comments(c):
            return "komentáře zatím nestažené", "comments not fetched yet"
        return "žádné komentáře k dispozici", "no comments available"
    return ("málo komentářů s rozpoznatelným jazykem", "too few comments with a detectable language")


def _assess_cs_comments(criterion: Criterion, c: Candidate) -> Outcome:
    min_share = float(param(criterion, "min_share") or 0.0)
    th = i18n(f"aspoň {fmt_pct(min_share, 'cs')} komentářů česky", f"at least {fmt_pct(min_share, 'en')} of comments in Czech")
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    share = c.metrics.cs_comment_share if c.metrics else None
    if share is None:
        cs, en = _no_comment_value(c)
        return unknown(cs, en, th, _comment_sources(c))
    n = c.metrics.comments_analyzed  # type: ignore[union-attr]
    value = i18n(f"{fmt_pct(share, 'cs')} komentářů česky ({fmt_int(n, 'cs')} analyzováno)",
                 f"{fmt_pct(share, 'en')} of comments in Czech ({fmt_int(n, 'en')} analyzed)")
    if share < min_share:
        return Outcome("fail", value, th, _comment_sources(c), reason=i18n(
            f"jen {fmt_pct(share, 'cs')} komentářů je česky",
            f"only {fmt_pct(share, 'en')} of comments are in Czech"))
    return Outcome("pass", value, th, _comment_sources(c))


def _assess_local(criterion: Criterion, c: Candidate, brief: Brief) -> Outcome:
    city = param(criterion, "city") or brief.city
    min_count = int(param(criterion, "min_count") or 1)
    th = i18n(f"aspoň {min_count} {cs_plural(min_count, 'lokální signál', 'lokální signály', 'lokálních signálů')}"
              f"{f' ({city})' if city else ''}",
              f"at least {min_count} local {'signal' if min_count == 1 else 'signals'}{f' ({city})' if city else ''}")
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    if not city:
        return unknown("město není zadané", "no city given", th, profile_refs(c))
    signals = local_signals(c.profile, posts_of(c), city)
    k = len(signals)
    if k == 0:
        value = i18n(f"žádný lokální signál ({city})", f"no local signal ({city})")
    else:
        value = i18n(f"{k} {cs_plural(k, 'lokální signál', 'lokální signály', 'lokálních signálů')} ({city})",
                     f"{k} local {'signal' if k == 1 else 'signals'} ({city})")
    if k < min_count:
        return Outcome("fail", value, th, signals or profile_refs(c), reason=i18n(
            f"{'žádný' if k == 0 else f'jen {k}'} lokální signál pro {city} (místo u postu, popisek, hashtag, bio)",
            f"{'no' if k == 0 else f'only {k}'} local signal for {city} (post location, caption, hashtag, bio)"))
    return Outcome("pass", value, th, signals[:5])


def _assess_generic(criterion: Criterion, c: Candidate) -> Outcome:
    max_share_raw = param(criterion, "max_share")
    max_share = float(max_share_raw if max_share_raw is not None else 1.0)
    th = i18n(f"nejvýš {fmt_pct(max_share, 'cs')}", f"at most {fmt_pct(max_share, 'en')}")
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    share = c.metrics.generic_comment_share if c.metrics else None
    if share is None:
        cs, en = _no_comment_value(c)
        return unknown(cs, en, th, _comment_sources(c))
    value = i18n(f"{fmt_pct(share, 'cs')} komentářů jen emoji nebo obecná fráze",
                 f"{fmt_pct(share, 'en')} of comments emoji-only or generic phrases")
    if share > max_share:
        return Outcome("fail", value, th, _comment_sources(c), reason=i18n(
            f"{fmt_pct(share, 'cs')} komentářů je jen emoji nebo obecné fráze",
            f"{fmt_pct(share, 'en')} of comments are emoji-only or generic phrases"))
    return Outcome("pass", value, th, _comment_sources(c))


def assess(criterion: Criterion, candidate: Candidate, brief: Brief, now: datetime) -> Outcome:
    kind = criterion.kind
    if kind == "min_engagement":
        return _assess_engagement(criterion, candidate)
    if kind == "cs_comment_share":
        return _assess_cs_comments(criterion, candidate)
    if kind == "local_signal":
        return _assess_local(criterion, candidate, brief)
    if kind == "max_generic_comments":
        return _assess_generic(criterion, candidate)
    raise ValueError(f"criterion kind {kind!r} is not a round-3 kind")


def evaluate(criterion: Criterion, candidate: Candidate, brief: Brief, now: datetime) -> CriterionResult:
    return assess(criterion, candidate, brief, now).result(criterion.id, brief.lang)
