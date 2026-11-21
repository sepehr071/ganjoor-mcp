"""Ganjoor explore tools: meters and similar poems, recitations, literary devices, words, people, places, museum."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal
from urllib.parse import quote

from pydantic import Field

from .http import ApiError, fetch, fetch_paged
from .registry import tool

MUSEUM = "https://museum.ganjoor.net/items"
RELATION = {0: "parent_of", 1: "sibling", 2: "spouse", 3: "ancestor_of"}
INVERSE = {"parent_of": "child_of", "ancestor_of": "descendant_of"}
Page = Annotated[int, Field(ge=1, le=1000, description="Page number.")]


def _norm(s: str | None) -> str:
    """Lowercase and unify Arabic letters and ZWNJ so a typed query matches the stored Persian."""
    s = (s or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    return " ".join(s.lower().split())


def _cut(s: str | None, n: int) -> str | None:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = " ".join(s.split())
    return None if not s else s if len(s) <= n else s[: n - 1] + "…"


def _couplet(text: str | None) -> str | None:
    """First couplet (two lines) of a poem's plain text."""
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    return " / ".join(lines[:2]) or None


def _page(paging: dict[str, Any]) -> dict[str, Any]:
    return {"total": paging.get("totalCount"), "page": paging.get("currentPage"), "pages": paging.get("totalPages")}


def _seg(value: str) -> str:
    return quote(value.strip().strip("/"), safe="")


async def _meters() -> list[dict[str, Any]]:
    return await fetch("/ganjoor/rhythms", {"sortOnVerseCount": "true"}) or []


def _meter(m: dict[str, Any]) -> dict[str, Any]:
    return {"id": m.get("id"), "name": m.get("name") or m.get("rhythm"), "couplets": m.get("verseCount")}


@tool("Poetic meters")
async def gj_meters(
    query: Annotated[str | None, Field(description="Part of a meter name, e.g. 'رمل' or 'هزج مسدس'.")] = None,
) -> dict[str, Any]:
    """List poetic meters (وزن) with couplet counts, biggest first; filter by name. Feed a name or id to gj_similar."""
    rows = await _meters()
    if query and query.strip():
        q = _norm(query)
        rows = [m for m in rows if q in _norm(m.get("rhythm")) or q in _norm(m.get("name"))]
    cap = 200 if query else 60
    out = {"total": len(rows), "meters": [_meter(m) for m in sorted(rows, key=lambda m: -(m.get("verseCount") or 0))]}
    out["meters"] = out["meters"][:cap]
    if len(rows) > cap:
        out["note"] = f"showing {cap}; narrow with query"
    return out


async def _resolve_meter(meter: str | int) -> dict[str, Any]:
    rows = await _meters()
    key = str(meter).strip()
    if key.isdigit():
        hit = [m for m in rows if m.get("id") == int(key)]
    else:
        q = _norm(key)
        hit = [m for m in rows if _norm(m.get("rhythm")) == q or _norm(m.get("name")) == q]
        hit = hit or [m for m in rows if q and (q in _norm(m.get("rhythm")) or q in _norm(m.get("name")))]
    if not hit:
        raise ApiError(f"No meter matches {key!r}. List them with gj_meters.")
    if len(hit) > 1:
        names = "; ".join(f"{m['id']}: {m.get('name') or m.get('rhythm')}" for m in hit[:5])
        raise ApiError(f"{len(hit)} meters match {key!r} ({names}). Pass the id or a longer name.")
    return hit[0]


@tool("Poems with same meter and rhyme")
async def gj_similar(
    meter: Annotated[
        str | int, Field(description="Meter id or name (part of it is enough if unique), from gj_meters.")
    ],
    rhyme_letters: Annotated[str | None, Field(description="Rhyme letters, e.g. 'ارا' (poem.rhyme_letters).")] = None,
    poet_id: Annotated[int | None, Field(description="Only this poet.")] = None,
    cat_id: Annotated[int | None, Field(description="Only this book/category.")] = None,
    page: Page = 1,
) -> dict[str, Any]:
    """Find poems that share a meter and rhyme, with their first couplet; 10 per page."""
    m = await _resolve_meter(meter)
    rows, paging = await fetch_paged(
        "/ganjoor/poems/similar",
        {
            "metre": m["rhythm"],
            "rhyme": (rhyme_letters or "").strip() or None,
            "poetId": poet_id,
            "catId": cat_id,
            "PageNumber": page,
            "PageSize": 10,
        },
    )
    poems = [
        {
            "id": p.get("id"),
            "title": p.get("fullTitle"),
            "url": p.get("fullUrl"),
            "poet": ((p.get("category") or {}).get("poet") or {}).get("name"),
            "couplet": _couplet(p.get("plainText")),
        }
        for p in rows or []
    ]
    return {"meter": _meter(m)["name"], "rhyme": rhyme_letters, **_page(paging), "poems": poems}


def _recitation(r: dict[str, Any], votes: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    v = (votes or {}).get(r.get("id")) or {}
    size = r.get("mp3SizeInBytes")
    return {
        "id": r.get("id"),
        "reciter": r.get("audioArtist"),
        "poem": r.get("poemFullTitle"),
        "poem_id": r.get("poemId"),
        "url": r.get("poemFullUrl"),
        "mp3": r.get("mp3Url"),
        "size_kb": round(size / 1024) if size else None,
        "published": (r.get("publishDate") or "")[:10] or None,
        "up_votes": v.get("upVotes"),
        "score": v.get("totalScores"),
    }


@tool("Recitations")
async def gj_recitations(
    poem_id: Annotated[int | None, Field(description="Recitations of this poem, best first.")] = None,
    cat_id: Annotated[int | None, Field(description="Top recitation of each poem in this book/category.")] = None,
    latest: Annotated[bool, Field(description="Newest published recitations site-wide.")] = False,
    with_timing: Annotated[
        bool, Field(description="With poem_id: add start milliseconds of each verse of the best recitation.")
    ] = False,
    limit: Annotated[int, Field(ge=1, le=30, description="Max recitations for cat_id and latest.")] = 10,
) -> dict[str, Any]:
    """List poem recitations (خوانش) with reciter, mp3 link, size and votes; give exactly one of poem_id, cat_id, latest."""
    if sum([poem_id is not None, cat_id is not None, latest]) != 1:
        raise ApiError("Give exactly one of poem_id, cat_id or latest=true.")
    if latest:
        rows, paging = await fetch_paged("/audio/published", {"PageNumber": 1, "PageSize": limit})
        return {"total": paging.get("totalCount"), "recitations": [_recitation(r) for r in rows or []]}
    if cat_id is not None:
        rows = await fetch(f"/audio/cattop1/{cat_id}", {"includePoemText": "false"}) or []
        return {"total": len(rows), "recitations": [_recitation(r) for r in rows[:limit]]}
    rows = await fetch(f"/ganjoor/poem/{poem_id}/recitations") or []
    scores = await fetch(f"/audio/votes/{poem_id}/scores") if rows else []
    votes = {s["recitationId"]: s for s in scores or []}
    rows = sorted(rows, key=lambda r: (votes.get(r.get("id")) or {}).get("computedOrder") or 999)
    out: dict[str, Any] = {"total": len(rows), "recitations": [_recitation(r, votes) for r in rows[:limit]]}
    if with_timing and rows:
        verses = await fetch(f"/audio/verses/{rows[0]['id']}") or []
        out["timing_for"] = rows[0]["id"]
        out["timing_note"] = "[verse_order, start_ms, text]; order 0 is the title, each verse is one hemistich"
        out["timing"] = [[v.get("verseOrder"), v.get("audioStartMilliseconds"), v.get("verseText")] for v in verses]
    return out


def _where(part: dict[str, Any]) -> dict[str, Any]:
    """Word position of a tag part: hemistich 1 or 2, word number (1-based); absent for whole-couplet parts."""
    return {"misra": part.get("misra"), "word": part.get("wordStart")} if part.get("wordStart") else {}


def _by_key(devices: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    q = _norm(key)
    return next((d for d in devices if q in (_norm(d.get("key")), _norm(d.get("name")))), None)


@tool("Literary devices")
async def gj_literary(
    poem_id: Annotated[int | None, Field(description="Rhetorical devices tagged in this poem, per couplet.")] = None,
    view: Annotated[
        Literal["devices", "concepts", "tags", "stats"] | None,
        Field(
            description="Lookup when no poem_id: devices (the list with definitions), concepts (search `tag`), "
            "tags (couplets tagged with device `tag`), stats (tag counts). Default devices."
        ),
    ] = None,
    tag: Annotated[str | None, Field(description="Device key or name (tags view), or concept search text.")] = None,
    poet_id: Annotated[int | None, Field(description="Limit tags/stats to this poet.")] = None,
    cat_id: Annotated[int | None, Field(description="Limit tags/stats to this book/category.")] = None,
) -> dict[str, Any]:
    """Show rhetorical devices (آرایه: tashbih, esteare...) and concepts tagged in poems; coverage is partial, mostly Hafez."""
    devices = await fetch("/ganjoor/literary/devices") or []
    names = {d["id"]: d.get("name") for d in devices}
    if poem_id is not None:
        slots = {s["id"]: s.get("name") for d in devices for s in d.get("slots") or []}
        rows = await fetch(f"/ganjoor/literary/poem/{poem_id}/tags") or []
        tags = [
            {
                "couplet": t.get("coupletIndex"),
                "device": names.get(t.get("deviceId")),
                "uncertain": t.get("uncertain") or None,
                "note": _cut(t.get("note"), 120),
                "parts": [
                    {
                        "slot": slots.get(p.get("slotId")),
                        "text": p.get("text") or (p.get("concept") or {}).get("name"),
                        **_where(p),
                    }
                    for p in t.get("parts") or []
                ],
            }
            for t in rows[:40]
        ]
        return {"poem_id": poem_id, "total": len(rows), "tags": tags}
    view = view or "devices"
    if view == "devices":
        return {
            "devices": [
                {
                    "id": d["id"],
                    "key": d.get("key"),
                    "name": d.get("name"),
                    "definition": _cut(d.get("definition"), 160),
                    "example": _cut(d.get("example"), 120),
                }
                for d in devices
            ]
        }
    if view == "concepts":
        rows = await fetch("/ganjoor/literary/concepts", {"query": (tag or "").strip() or None, "take": 30}) or []
        return {"concepts": [{"id": c["id"], "name": c.get("name")} for c in rows]}
    if view == "stats":
        s = await fetch("/ganjoor/literary/stats/overview", {"poetId": poet_id, "catId": cat_id}) or {}
        return {
            "tags": s.get("totalTags"),
            "poems": s.get("totalPoems"),
            "devices": [
                {"name": names.get(d.get("deviceId")), "tags": d.get("tagCount"), "poems": d.get("poemCount")}
                for d in s.get("devices") or []
            ],
            "top_concepts": [
                {"name": c.get("name"), "uses": c.get("usageCount")} for c in (s.get("topConcepts") or [])[:10]
            ],
        }
    dev = _by_key(devices, tag) if tag else None
    if tag and not dev:
        raise ApiError(f"No device matches {tag!r}. See view=devices.")
    r = await fetch(
        "/ganjoor/literary/stats/tags",
        {"deviceId": dev and dev["id"], "poetId": poet_id, "catId": cat_id, "skip": 0, "take": 8},
    )
    items = [
        {
            "poem_id": i.get("poemId"),
            "poem": i.get("poemFullTitle"),
            "url": i.get("poemFullUrl"),
            "couplet": i.get("coupletIndex"),
            "text": f"{i.get('hemistich1')} / {i.get('hemistich2')}",
            "device": names.get(i.get("deviceId")),
            "parts": [f"{p.get('slotName')}: {p.get('words')}" for p in i.get("parts") or []],
        }
        for i in (r or {}).get("items") or []
    ]
    return {"total": (r or {}).get("total"), "tags": items}


@tool("Word frequency")
async def gj_words(
    cat_id: Annotated[
        int | None, Field(description="Book/category id (a poet's whole divan: its root cat_id).")
    ] = None,
    poet_id: Annotated[int | None, Field(description="Poet id (all their books together).")] = None,
    word: Annotated[str | None, Field(description="Count this exact word instead of listing top words.")] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="Top words to list.")] = 30,
) -> dict[str, Any]:
    """Count word use in a poet's or book's poems: the most frequent words, or how often one word appears."""
    if (cat_id is None) == (poet_id is None):
        raise ApiError("Give exactly one of cat_id or poet_id.")
    scope = {"catId": cat_id, "poetId": poet_id}
    if word and word.strip():
        w = word.strip()
        hit = await fetch("/ganjoor/wordcounts/bycat/count", {"term": w, **scope})
        if not hit:
            return {"word": w, "count": 0, "note": "word not found (exact spelling, without suffixes)"}
        cid = hit["catId"]
        sums = await fetch(f"/ganjoor/wordsums/{cid}") or {}
        out = {
            "word": hit["word"],
            "count": hit["count"],
            "rank": hit.get("rowNmbrInCat"),
            "cat_id": cid,
            "unique_words": sums.get("uniqueWordCount"),
            "total_words": sums.get("totalWordCount"),
        }
        books = await fetch("/ganjoor/wordcounts/bycat", {"term": w, **scope, "PageNumber": 1, "PageSize": 8})
        if books:
            out["by_book"] = [{"cat_id": b["catId"], "name": b.get("name"), "count": b["count"]} for b in books]
        return out
    cid = cat_id
    if cid is None:
        cid = ((await fetch(f"/ganjoor/poet/{poet_id}")) or {}).get("poet", {}).get("rootCatId")
        if not cid:
            raise ApiError("Poet has no root category.")
    rows, paging = await fetch_paged(f"/ganjoor/wordcounts/{cid}", {"PageNumber": 1, "PageSize": limit})
    sums = await fetch(f"/ganjoor/wordsums/{cid}") or {}
    return {
        "cat_id": cid,
        "unique_words": sums.get("uniqueWordCount") or paging.get("totalCount"),
        "total_words": sums.get("totalWordCount"),
        "words": [{"word": r["word"], "count": r["count"]} for r in rows or []],
    }


def _person(p: dict[str, Any], desc: int = 200) -> dict[str, Any]:
    born, died = p.get("birthYearInLHijri"), p.get("deathYearInLHijri")
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "aliases": p.get("aliases"),
        "description": _cut(p.get("description"), desc),
        "born_ah": born if p.get("validBirthDate") and born else None,
        "died_ah": died if p.get("validDeathDate") and died else None,
        "wiki": p.get("wikiUrl"),
    }


def _kin(subject_is_first: bool, type_: int) -> str:
    rel = RELATION.get(type_, f"relation_{type_}")
    return rel if subject_is_first else INVERSE.get(rel, rel)


@tool("People and characters")
async def gj_people(
    query: Annotated[str | None, Field(description="Search characters by name or alias (e.g. 'رستم').")] = None,
    id: Annotated[int | None, Field(description="Person id from a search.")] = None,
    view: Annotated[
        Literal["info", "relations", "familytree"],
        Field(description="For id: info, relations (kin and ties with evidence), familytree."),
    ] = "info",
    cat_id: Annotated[
        int | None, Field(description="Instead: the main characters and links of a book (e.g. 33).")
    ] = None,
) -> dict[str, Any]:
    """Look up people and characters of epic poems (Shahnameh...): search, relations, family tree, or a book's cast."""
    if id is not None:
        if view == "info":
            return _person(await fetch(f"/people/{id}") or {}, 600)
        if view == "relations":
            r = await fetch(f"/people/{id}/relations", {"evidenceLimit": 1}) or {}
            rels = r.get("relations") or []
            aff = r.get("affiliations") or []

            def edge(x: dict[str, Any], rel: str) -> dict[str, Any]:
                ev = (x.get("evidence") or [{}])[0]
                return {
                    "other_id": x.get("otherPersonId"),
                    "other": x.get("otherPersonName"),
                    "relation": rel,
                    "note": _cut(x.get("note"), 160),
                    "evidence": x.get("evidenceCount"),
                    "couplet": _cut(ev.get("coupletText"), 140),
                    "poem_id": ev.get("poemId"),
                }

            return {
                "person": _person(r.get("person") or {}, 200),
                "relations": [edge(x, _kin(x.get("subjectIsPerson1"), x.get("relationType"))) for x in rels[:25]],
                "ties": [edge(x, f"tie_{x.get('affiliationType')}") for x in aff[:15]],
                "total": {"relations": len(rels), "ties": len(aff)},
            }
        t = await fetch(f"/people/{id}/familytree") or {}
        names = {p["id"]: p.get("name") for p in t.get("persons") or []}
        rels = t.get("relations") or []
        return {
            "root": names.get(t.get("rootId")),
            "people": len(names),
            "edges": [
                [names.get(x["person1Id"]), _kin(True, x["relationType"]), names.get(x["person2Id"])] for x in rels[:60]
            ],
            "books": [{"cat_id": b["id"], "title": b.get("title")} for b in t.get("books") or []],
            "note": f"{len(rels)} edges, first 60 shown" if len(rels) > 60 else None,
        }
    if cat_id is not None:
        g = await fetch(f"/ganjoor/cat/{cat_id}/persongraph") or {}
        nodes = sorted(g.get("nodes") or [], key=lambda n: -(n.get("importance") or 0))[:30]
        ids = {n["id"] for n in nodes}
        edges = [e for e in g.get("edges") or [] if e["person1Id"] in ids and e["person2Id"] in ids][:50]
        return {
            "people": len(g.get("nodes") or []),
            "links": len(g.get("edges") or []),
            "main": [{"id": n["id"], "name": n.get("name")} for n in nodes],
            "edges": [
                [
                    e.get("person1Name"),
                    _kin(True, e["typeValue"]) if e.get("category") == "Relation" else "tie",
                    e.get("person2Name"),
                ]
                for e in edges
            ],
        }
    if not query or not query.strip():
        raise ApiError("Give query, id or cat_id.")
    q = _norm(query)
    rows = [p for p in await fetch("/people") or [] if q in _norm(p.get("name")) or q in _norm(p.get("aliases"))]
    rows.sort(key=lambda p: -(p.get("importance") or 0))
    return {"total": len(rows), "people": [_person(p, 120) for p in rows[:20]]}


def _loc(loc: dict[str, Any]) -> dict[str, Any]:
    return {"id": loc.get("id"), "name": loc.get("name"), "lat": loc.get("latitude"), "lon": loc.get("longitude")}


@tool("Places in poems")
async def gj_places(
    poem_id: Annotated[int | None, Field(description="Places named in this poem, with the couplet.")] = None,
    cat_id: Annotated[
        int | None, Field(description="Places named across a book/category, with a few poems each.")
    ] = None,
    query: Annotated[str | None, Field(description="Search the place list by name (e.g. 'شیراز').")] = None,
) -> dict[str, Any]:
    """Find geotagged places (locations with latitude and longitude) named in poems, a book, or by name."""
    if poem_id is not None:
        rows = await fetch(f"/ganjoor/poem/{poem_id}/geotag") or []
        return {
            "total": len(rows),
            "places": [
                {
                    **_loc(r.get("location") or {}),
                    "couplet": r.get("coupletIndex"),
                    "text": _cut(r.get("coupletText"), 160),
                }
                for r in rows[:30]
            ],
        }
    if cat_id is not None:
        rows = await fetch(f"/ganjoor/cat/{cat_id}/geotag", {"onlyWithLocation": "true"}) or []
        groups: dict[int, dict[str, Any]] = {}
        for r in rows:
            loc = r.get("location") or {}
            g = groups.setdefault(loc.get("id"), {**_loc(loc), "mentions": 0, "poems": []})
            g["mentions"] += 1
            p = r.get("poem") or {}
            if len(g["poems"]) < 3 and p.get("id") not in [x["id"] for x in g["poems"]]:
                g["poems"].append({"id": p.get("id"), "title": p.get("fullTitle"), "url": p.get("fullUrl")})
        top = sorted(groups.values(), key=lambda g: -g["mentions"])
        return {"total": len(top), "places": top[:25]}
    if not query or not query.strip():
        raise ApiError("Give poem_id, cat_id or query.")
    q = _norm(query)
    rows = [loc for loc in await fetch("/locations") or [] if q in _norm(loc.get("name"))]
    return {"total": len(rows), "places": [_loc(loc) for loc in rows[:30]]}


def _image(img: dict[str, Any] | None) -> str | None:
    return (img or {}).get("externalNormalSizeImageUrl")


def _artifact(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "slug": a.get("friendlyUrl"),
        "title": a.get("name"),
        "description": _cut(a.get("description"), 200),
        "pages": a.get("itemCount"),
        "cover": _image(a.get("coverImage")),
        "link": f"{MUSEUM}/{a.get('friendlyUrl')}",
    }


@tool("Museum manuscripts")
async def gj_museum(
    query: Annotated[
        str | None, Field(description="Search manuscripts by title or poet; empty lists the newest.")
    ] = None,
    slug: Annotated[str | None, Field(description="Manuscript slug from a search, e.g. 'nowras'.")] = None,
    item: Annotated[str | None, Field(description="With slug: one page slug, e.g. 'p0001'.")] = None,
    page: Page = 1,
) -> dict[str, Any]:
    """Browse Ganjoor museum manuscripts and scans (گنجینه): search, one manuscript's details, or one page image."""
    if slug and item:
        r = await fetch(f"/artifacts/{_seg(slug)}/{_seg(item)}") or {}
        it = r.get("item") or {}
        return {
            "manuscript": r.get("parentName"),
            "page": it.get("name"),
            "order": it.get("order"),
            "of": r.get("parentItemCount"),
            "description": _cut(it.get("description"), 300),
            "images": [_image(i) for i in (it.get("images") or [])[:3]],
            "next": r.get("nextItemFriendlyUrl"),
            "previous": r.get("previousItemFriendlyUrl"),
            "link": f"{MUSEUM}/{_seg(slug)}/{_seg(item)}",
        }
    if slug:
        a = await fetch(f"/artifacts/{_seg(slug)}") or {}
        facts = {
            t.get("name"): "; ".join(v.get("value") or "" for v in t.get("values") or [])
            for t in a.get("artifactTags") or []
            if t.get("name")
        }
        items = a.get("items") or []
        contents = a.get("contents") or []
        return {
            **_artifact(a),
            "facts": {k: v for k, v in facts.items() if v and len(v) <= 100},  # long values are the notes block
            "images": [_image(i.get("images", [None])[0]) for i in items[:3] if i.get("images")],
            "contents": [{"title": _cut(c.get("title"), 100), "page": c.get("itemFriendlyUrl")} for c in contents[:12]],
            "contents_total": len(contents),
        }
    if query and query.strip():
        rows, paging = await fetch_paged(
            "/artifacts/search", {"term": query.strip(), "PageNumber": page, "PageSize": 10}
        )
    else:
        rows, paging = await fetch_paged("/artifacts", {"PageNumber": page, "PageSize": 10})
    return {**_page(paging), "manuscripts": [_artifact(a) for a in rows or []]}
