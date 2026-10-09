"""Round 2: content. prepare: llm.topics.classify(latest_posts) per candidate (one call each, cached by
post ids), store counts in metrics.topic_counts (recompute reuses them; classify every candidate that
has a profile, not only active ones, so a goal change needs no new LLM call).
Per-post labels are kept on the candidate too when the model has a ``topic_labels`` field (then
topic_share can cite the matching posts); otherwise the profile is cited.
evaluate kinds (code only): topic_share (sum topic_counts[t] for t in params.topics / classified
posts, value like "2 z 24 postů o jídle"), formats, post_frequency, max_commercial_share."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.compute.metrics import UNCLASSIFIED, classified_total, commercial_posts, topic_counts
from app.events import Emit
from app.llm import topics as topics_mod
from app.models import Brief, Candidate, Criterion, CriterionResult, Run, i18n
from app.rounds.common import (
    llm_actor,
    FORMAT_CS,
    FORMAT_EN,
    TOPIC_CS_LOC,
    TOPIC_EN,
    Outcome,
    cs_plural,
    cs_posts_gen,
    fmt_num,
    fmt_pct,
    join_cs,
    join_en,
    log,
    logger,
    param,
    post_ref,
    posts_of,
    profile_refs,
    tr,
    unknown,
)
from app.sources.base import SourceProvider

ROUND = 2


def has_topic_labels_field() -> bool:
    return "topic_labels" in Candidate.model_fields


def get_topic_labels(candidate: Candidate) -> dict[str, str]:
    labels = getattr(candidate, "topic_labels", None)
    return dict(labels) if isinstance(labels, dict) else {}


def needs_topics(candidate: Candidate) -> bool:
    if candidate.profile is None or candidate.metrics is None:
        return False
    return bool(candidate.profile.latest_posts) and not candidate.metrics.topic_counts


async def _classify(posts) -> dict[str, str]:
    try:
        return await topics_mod.classify(posts)
    except Exception:
        logger.exception("topics.classify failed; using keyword fallback")
        try:
            return topics_mod.fallback_classify(posts)
        except Exception:
            logger.exception("topics.fallback_classify failed")
            return {}


async def prepare(run: Run, candidates: list[Candidate], provider: SourceProvider, emit: Emit) -> None:
    # Every candidate with a profile, not only the active ones: a goal change then needs no LLM call.
    todo = [c for c in run.candidates.values() if needs_topics(c)]
    if not todo:
        return
    sem = asyncio.Semaphore(6)

    async def one(c: Candidate) -> bool:
        async with sem:
            labels = await _classify(list(c.profile.latest_posts))  # type: ignore[union-attr]
        post_ids = {p.id for p in c.profile.latest_posts}  # type: ignore[union-attr]
        labels = {pid: t for pid, t in labels.items() if pid in post_ids}
        if not labels:
            return False
        c.metrics = c.metrics.model_copy(update={"topic_counts": topic_counts(labels)})  # type: ignore[union-attr]
        if has_topic_labels_field():
            setattr(c, "topic_labels", labels)
        return True

    done = sum(await asyncio.gather(*(one(c) for c in todo)))
    mode = run.llm_modes.get("topics")
    how = {"llm": ("model", "model"), "fallback": ("záložní pravidla", "fallback rules"),
           "mixed": ("model i záložní pravidla", "model and fallback rules")}.get(mode or "", ("", ""))
    suffix_cs = f" ({how[0]})" if how[0] else ""
    suffix_en = f" ({how[1]})" if how[1] else ""
    await log(run, emit, tr(
        run,
        f"Témata: {done} {cs_plural(done, 'účet zatříděn', 'účty zatříděny', 'účtů zatříděno')}{suffix_cs}.",
        f"Topics: {done} {'account' if done == 1 else 'accounts'} classified{suffix_en}.",
    ), actor=llm_actor(run, "topics"))


# ---------------------------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------------------------

def _topic_phrase(topics: list[str]) -> dict[str, str]:
    return i18n(join_cs([TOPIC_CS_LOC.get(t, t) for t in topics]), join_en([TOPIC_EN.get(t, t) for t in topics]))


def _assess_topics(criterion: Criterion, c: Candidate) -> Outcome:
    # Supporting topics (local tips) never carry the share alone: a food goal needs food posts.
    topics = topics_mod.counted_topics([t for t in (param(criterion, "topics") or []) if isinstance(t, str)])
    min_share = float(param(criterion, "min_share") or 0.0)
    th = i18n(f"aspoň {fmt_pct(min_share, 'cs')} postů", f"at least {fmt_pct(min_share, 'en')} of posts")
    counts = c.metrics.topic_counts if c.metrics else {}
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    if not c.profile.latest_posts:
        return unknown("posty nejsou k dispozici", "posts not available", th, profile_refs(c))
    if not counts:
        return unknown("témata zatím nejsou zatříděná", "topics not classified yet", th, profile_refs(c))
    total = classified_total(counts)
    unclassified = counts.get(UNCLASSIFIED, 0)
    k = sum(counts.get(t, 0) for t in topics)
    phrase = _topic_phrase(topics)
    unc_cs = f" ({unclassified} {cs_plural(unclassified, 'post nezařazen', 'posty nezařazeny', 'postů nezařazeno')})" if unclassified else ""
    unc_en = f" ({unclassified} {'post' if unclassified == 1 else 'posts'} unclassified)" if unclassified else ""
    if total < 3:
        if c.sensitive_filtered >= 3 and c.sensitive_filtered > len(c.profile.latest_posts):
            # Most of the account's texts were left out by the sensitive filter: what is left cannot
            # show the topic (the reason never says which kind of content was left out).
            return Outcome("fail", i18n(f"jen {total} {cs_plural(total, 'post zařazen', 'posty zařazeny', 'postů zařazeno')}{unc_cs}",
                                        f"only {total} {'post' if total == 1 else 'posts'} classified{unc_en}"),
                           th, profile_refs(c), reason=i18n(
                               f"většinu textů účtu ({c.sensitive_filtered}) vynechal filtr citlivého obsahu, ze zbytku nejde doložit "
                               f"obsah o {phrase['cs']}",
                               f"the sensitive-content filter left out most of the account's texts ({c.sensitive_filtered}), "
                               f"too little is left to show content about {phrase['en']}"))
        # The no-key fallback recognised too few posts: not a fail (unknown never eliminates).
        return unknown(f"jen {total} {cs_plural(total, 'post zařazen', 'posty zařazeny', 'postů zařazeno')}{unc_cs}",
                       f"only {total} {'post' if total == 1 else 'posts'} classified{unc_en}", th, profile_refs(c))
    value = i18n(f"{k} z {total} {cs_posts_gen(total)} o {phrase['cs']}{unc_cs}",
                 f"{k} of {total} posts about {phrase['en']}{unc_en}")
    labels = get_topic_labels(c)
    posts = {p.id: p for p in posts_of(c)}
    matching = [posts[pid] for pid, t in labels.items() if t in topics and pid in posts]
    sources = [post_ref(p) for p in matching[:5]] or profile_refs(c)
    share = k / total if total else 0.0
    if share < min_share:
        if k == 0:
            reason = i18n(f"žádný z {total} {cs_posts_gen(total)} není o {phrase['cs']}",
                          f"none of {total} posts is about {phrase['en']}")
        else:
            reason = i18n(f"jen {k} z {total} {cs_posts_gen(total)} {cs_plural(k, 'je', 'jsou', 'je')} o {phrase['cs']}",
                          f"only {k} of {total} posts {'is' if k == 1 else 'are'} about {phrase['en']}")
        fail_sources = (profile_refs(c) + sources[:3]) if matching else profile_refs(c)
        return Outcome("fail", value, th, fail_sources, reason=reason)
    return Outcome("pass", value, th, sources)


def _assess_formats(criterion: Criterion, c: Candidate) -> Outcome:
    formats = [f for f in (param(criterion, "formats") or []) if isinstance(f, str)]
    min_share = float(param(criterion, "min_share") or 0.0)
    th = i18n(f"aspoň {fmt_pct(min_share, 'cs')} postů", f"at least {fmt_pct(min_share, 'en')} of posts")
    posts = posts_of(c)
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    if not posts:
        return unknown("posty nejsou k dispozici", "posts not available", th, profile_refs(c))
    n = len(posts)
    matching = [p for p in posts if p.media_type in formats]
    k = len(matching)
    names_cs = "/".join(FORMAT_CS.get(f, f) for f in formats) or "?"
    names_en = "/".join(FORMAT_EN.get(f, f) for f in formats) or "?"
    value = i18n(f"{k} z {n} {cs_posts_gen(n)}: {names_cs}", f"{k} of {n} posts: {names_en}")
    sources = [post_ref(p) for p in matching[:5]] or profile_refs(c)
    if k / n < min_share:
        reason = (i18n(f"žádný z {n} {cs_posts_gen(n)} není ve formátu {names_cs}", f"none of {n} posts is in format {names_en}")
                  if k == 0 else
                  i18n(f"jen {k} z {n} {cs_posts_gen(n)} ve formátu {names_cs}", f"only {k} of {n} posts in format {names_en}"))
        return Outcome("fail", value, th, sources, reason=reason)
    return Outcome("pass", value, th, sources)


def _cs_per_week(x: float) -> str:
    if abs(x - round(x)) < 0.05:
        n = int(round(x))
        return f"{n} {cs_plural(n, 'post', 'posty', 'postů')} týdně"
    return f"{fmt_num(x, 'cs')} postu týdně"


def _en_per_week(x: float) -> str:
    return f"{fmt_num(x, 'en')} {'post' if abs(x - 1) < 0.05 else 'posts'} per week"


def _assess_frequency(criterion: Criterion, c: Candidate) -> Outcome:
    min_pw = float(param(criterion, "min_per_week") or 0.0)
    th = i18n(f"aspoň {_cs_per_week(min_pw)}", f"at least {_en_per_week(min_pw)}")
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    ppw = c.metrics.posts_per_week if c.metrics else None
    if ppw is None:
        return unknown("málo postů pro výpočet", "too few posts to compute", th, profile_refs(c))
    n = c.metrics.posts_analyzed if c.metrics else 0
    value = i18n(_cs_per_week(ppw) + (f" (posledních {n} {cs_posts_gen(n)})" if n else ""),
                 _en_per_week(ppw) + (f" (last {n} posts)" if n else ""))
    if ppw < min_pw:
        return Outcome("fail", value, th, profile_refs(c), reason=i18n(f"jen {_cs_per_week(ppw)}", f"only {_en_per_week(ppw)}"))
    return Outcome("pass", value, th, profile_refs(c))


def _assess_commercial(criterion: Criterion, c: Candidate) -> Outcome:
    max_share = float(param(criterion, "max_share") if param(criterion, "max_share") is not None else 1.0)
    th = i18n(f"nejvýš {fmt_pct(max_share, 'cs')} komerčních postů", f"at most {fmt_pct(max_share, 'en')} commercial posts")
    posts = posts_of(c)
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    if not posts:
        return unknown("posty nejsou k dispozici", "posts not available", th, profile_refs(c))
    n = len(posts)
    com = commercial_posts(posts)
    k = len(com)
    share = k / n
    # the window is named: the report's commercial-saturation fact counts ALL fetched posts
    value = i18n(f"{k} z posledních {n} {cs_posts_gen(n)} komerčních ({fmt_pct(share, 'cs')})",
                 f"{k} of the last {n} posts commercial ({fmt_pct(share, 'en')})")
    sources = [post_ref(p) for p in com[:5]] or profile_refs(c)
    if share > max_share:
        return Outcome("fail", value, th, sources, reason=i18n(
            f"{k} z {n} {cs_posts_gen(n)} je komerčních (štítek spolupráce, #reklama nebo slevový kód)",
            f"{k} of {n} posts are commercial (partnership label, ad hashtag or discount code)"))
    return Outcome("pass", value, th, sources)


def assess(criterion: Criterion, candidate: Candidate, brief: Brief, now: datetime) -> Outcome:
    kind = criterion.kind
    if kind == "topic_share":
        return _assess_topics(criterion, candidate)
    if kind == "formats":
        return _assess_formats(criterion, candidate)
    if kind == "post_frequency":
        return _assess_frequency(criterion, candidate)
    if kind == "max_commercial_share":
        return _assess_commercial(criterion, candidate)
    raise ValueError(f"criterion kind {kind!r} is not a round-2 kind")


def evaluate(criterion: Criterion, candidate: Candidate, brief: Brief, now: datetime) -> CriterionResult:
    return assess(criterion, candidate, brief, now).result(criterion.id, brief.lang)
