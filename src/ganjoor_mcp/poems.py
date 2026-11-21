"""Ganjoor poem tools: search (text and meaning), verse lookup, poems with meanings, poets, books, faal, Tajik."""

from __future__ import annotations

import asyncio
import html
import re
from difflib import SequenceMatcher
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .http import API, SEMANTIC, ApiError, fetch, fetch_paged, post
from .registry import tool

PAGE_SIZE = 10
BOOK_PAGE = 30
DEFAULT_COUPLETS = 80
MAX_COUPLETS = 500
POET_CAP = 50

Page = Annotated[int, Field(ge=1, le=1000, description="Page number, 10 results per page.")]
PoemId = Annotated[int, Field(ge=1, description="Poem id (`id` from search or book results).")]

# Opt-in flags of GET /ganjoor/poem: recitations, images, songs and comments are off unless asked for
# (recitations default to on server-side, which adds ~10 KB).
POEM_FLAGS = {
    "catInfo": True,
    "catPoems": False,
    "rhymes": True,
    "recitations": False,
    "images": False,
    "songs": False,
    "comments": False,
    "verseDetails": True,
    "navigation": True,
    "relatedpoems": False,
}

_DIACRITICS = re.compile("[\u064b-\u065f\u0670\u0640]")  # harakat, dagger alef, tatweel
_NOT_WORD = re.compile(r"[^\w\s]")
_DIGITS = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789") | str.maketrans(
    "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9", "0123456789"
)
# Arabic ye and alef maqsura -> Persian ye, Arabic kaf -> Persian kaf, heh with hamza and teh marbuta -> heh, ZWNJ -> space,
# hamza seats (\u0623 \u0625 \u0622 \u0624 \u0626) -> bare letters and lone hamza dropped, so Hafez's \u00ab\u06a9\u0623\u0633\u0627\u064b\u00bb matches a typed \u00ab\u06a9\u0627\u0633\u0627\u00bb
_LETTERS = str.maketrans(
    {
        "\u064a": "\u06cc",
        "\u0649": "\u06cc",
        "\u0643": "\u06a9",
        "\u06c0": "\u0647",
        "\u0629": "\u0647",
        "\u200c": " ",
        "\u0623": "\u0627",
        "\u0625": "\u0627",
        "\u0622": "\u0627",
        "\u0624": "\u0648",
        "\u0626": "\u06cc",
        "\u0621": "",
    }
)


def _norm(s: str | None) -> str:
    """Lowercase text with Arabic/Persian ye and kaf unified, diacritics, ZWNJ and punctuation removed."""
    s = _DIACRITICS.sub("", (s or "").translate(_LETTERS).translate(_DIGITS))
    return " ".join(_NOT_WORD.sub(" ", s).lower().split())


def _cut(s: str | None, n: int) -> str | None:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "..."


def _text(s: str | None) -> str:
    """HTML to plain text."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def _url_path(url: str) -> str:
    """A ganjoor.net address or path as a path like /hafez/ghazal/sh170."""
    path = re.sub(r"^https?://[^/]+", "", url.strip()).split("?")[0].rstrip("/")
    return path if path.startswith("/") else "/" + path


def _poet(p: dict[str, Any] | None) -> dict[str, Any] | None:
    if not p:
        return None
    return {"id": p.get("id"), "name": (p.get("nickname") or p.get("name") or "").strip(), "url": p.get("fullUrl")}


def _head(p: dict[str, Any]) -> dict[str, Any]:
    """Identity of a poem object from a search or page answer."""
    return {
        "id": p.get("id"),
        "title": p.get("title"),
        "full_title": p.get("fullTitle"),
        "url": p.get("fullUrl"),
        "poet": _poet((p.get("category") or {}).get("poet")),
    }


def _pairs(plain: str | None) -> list[list[str]]:
    """plainText lines ('\\r\\n' between hemistichs) as two-line couplets."""
    lines = [x.strip() for x in (plain or "").replace("\r", "").split("\n") if x.strip()]
    return [lines[i : i + 2] for i in range(0, len(lines), 2)]


def _snippet(plain: str | None, query: str) -> str | None:
    """The couplet of a poem text that shares the most words with the query."""
    words = set(_norm(query).split())
    pairs = _pairs(plain)
    if not pairs:
        return None
    best = max(pairs, key=lambda c: len(words & set(_norm(" ".join(c)).split())))
    return _cut(" / ".join(best), 200)


def _couplets(verses: list[dict[str, Any]], meanings: bool) -> list[dict[str, Any]]:
    """Group verses into couplets by coupletIndex (right+left halves; single, centered and paragraph
    verses carry their own index). `h` holds the hemistichs, `m` the meaning when asked for."""
    groups: dict[Any, dict[str, Any]] = {}
    for i, v in enumerate(verses):
        key = v.get("coupletIndex")
        g = groups.setdefault(i if key is None else key, {"h": [], "m": None})
        g["h"].append(v.get("text") or "")
        if meanings and not g["m"] and v.get("coupletSummary"):
            g["m"] = v["coupletSummary"]
    return [{"n": n, **g} for n, g in enumerate(groups.values(), 1)]


def _semantic_couplets(verses: list[dict[str, Any]], limit: int) -> list[str]:
    """First couplets of a semantic hit: 'Right' starts a couplet, other positions end or stand alone."""
    out: list[list[str]] = []
    for v in verses:
        if v.get("position") == "Left" and out and len(out[-1]) == 1:
            out[-1].append(v.get("text") or "")
        else:
            out.append([v.get("text") or ""])
    return [" / ".join(c) for c in out[:limit]]


def _poem_view(p: dict[str, Any], meanings: bool, max_couplets: int | None) -> dict[str, Any]:
    cat = p.get("category") or {}
    sections = p.get("sections") or []
    meters = list(dict.fromkeys(m for s in sections if (m := (s.get("ganjoorMetre") or {}).get("rhythm"))))
    rhymes = list(dict.fromkeys(r for s in sections if (r := s.get("rhymeLetters"))))
    allc = _couplets(p.get("verses") or [], meanings)
    cap = min(max_couplets or DEFAULT_COUPLETS, MAX_COUPLETS)
    shown = allc[:cap]
    book = cat.get("cat") or {}
    out: dict[str, Any] = {
        **_head(p),
        "book": {"id": book.get("id"), "title": book.get("title"), "url": book.get("fullUrl")},
        "meter": " | ".join(meters[:3]),
        "rhyme": " | ".join(rhymes[:3]),
        "summary": p.get("poemSummary"),
        "couplets": [{"n": c["n"], "text": " / ".join(c["h"]), "meaning": c["m"]} for c in shown],
        "source": p.get("sourceName"),
        "prev": _nav(p.get("previous")),
        "next": _nav(p.get("next")),
    }
    if len(allc) > len(shown):
        out["truncated"] = f"Showing {len(shown)} of {len(allc)} couplets; raise max_couplets (up to {MAX_COUPLETS})."
    return out


def _nav(n: dict[str, Any] | None) -> dict[str, Any] | None:
    return {"id": n.get("id"), "title": n.get("title")} if n else None


async def _load_poem(id: int | None, url: str | None) -> dict[str, Any]:
    if (id is None) == (url is None):
        raise ToolError("Give exactly one of id or url.")
    if id is not None:
        return await fetch(f"/ganjoor/poem/{id}", POEM_FLAGS)
    flags = {k: v for k, v in POEM_FLAGS.items() if k != "relatedpoems"}
    return await fetch("/ganjoor/poem", {**flags, "url": _url_path(url or "")})


# --- search -----------------------------------------------------------------------------------------------


@tool("Search poems by words")
async def gj_search(
    query: Annotated[str, Field(min_length=1, description="Persian words as written in the poem, e.g. 'دل من'.")],
    poet_id: Annotated[int | None, Field(ge=1, description="Only this poet (id from gj_poets).")] = None,
    cat_id: Annotated[int | None, Field(ge=1, description="Only this book or section (cat_id).")] = None,
    page: Page = 1,
) -> dict[str, Any]:
    """Full-text search of poems by the words they contain, with the matching couplet.

    All words must appear in the poem. Use gj_semantic_search to search by meaning instead.
    """
    term = _norm(query)
    if not term:
        raise ToolError("The query has no searchable words.")
    r, paging = await fetch_paged(
        "/ganjoor/poems/search",
        {"term": term, "poetId": poet_id, "catId": cat_id, "PageNumber": page, "PageSize": PAGE_SIZE},
    )
    items = r or []
    return {
        "total": paging.get("totalCount", len(items)),
        "page": paging.get("currentPage", page),
        "pages": paging.get("totalPages", 1),
        "results": [{**_head(p), "snippet": _snippet(p.get("plainText"), term)} for p in items],
    }


@tool("Search poems by meaning")
async def gj_semantic_search(
    query: Annotated[str, Field(min_length=1, description="What the poem is about, in Persian or English.")],
    top_k: Annotated[int, Field(ge=1, le=20, description="How many poems to return.")] = 5,
) -> dict[str, Any]:
    """Find poems by meaning or theme (embedding search), with score, summary and first couplets.

    Falls back to full-text search when the semantic index is down.
    """
    body = {"query": query, "topK": top_k, "disableScopeDetection": False}
    try:
        try:
            r = await post(SEMANTIC, body)
        except ApiError:
            r = await post(f"{API}/ganjoor/search/semantic", body)
    except ApiError as e:
        out = await gj_search(query)
        out["note"] = f"Semantic search is unavailable ({e}); these are full-text matches."
        return out
    r = r or {}
    return {
        "detected_poet": r.get("detectedPoetName"),
        "detected_category": r.get("detectedCategoryName"),
        "results": [
            {
                "id": h.get("poemId"),
                "full_title": h.get("fullTitle"),
                "url": h.get("fullUrl"),
                "score": round(h.get("score") or 0, 3),
                "summary": _cut(h.get("poemSummary"), 300),
                "couplets": _semantic_couplets(h.get("verses") or [], 2),
            }
            for h in (r.get("results") or [])[:top_k]
        ],
    }


@tool("Find the poem of a quoted line")
async def gj_find_verse(
    text: Annotated[str, Field(min_length=3, description="A line or couplet quoted from memory, in Persian.")],
) -> dict[str, Any]:
    """Locate which poem and couplet a quoted line comes from, with the couplet's meaning.

    Spelling differences (ye/kaf, ZWNJ, diacritics, punctuation) are ignored.
    """
    q = _norm(text)
    words = q.split()
    if not words:
        raise ToolError("The text has no searchable words.")
    terms = [q] + ([" ".join(words[: max(2, len(words) // 2)])] if len(words) > 3 else [])
    items: list[dict[str, Any]] = []
    for t in terms:
        items = await fetch("/ganjoor/poems/search", {"term": t, "PageNumber": 1, "PageSize": PAGE_SIZE}) or []
        if items:
            break
    if not items:
        return {"found": False, "note": "No poem contains these words. Try gj_semantic_search or fewer words."}
    # A famous line is often quoted (tazmin) by later poets; among equal matches prefer the earliest poet (no one
    # quotes a later poet), then the poem where the line sits earliest. Hafez's ghazal 1 beats Jami and Saghar.
    ranked = sorted(items, key=lambda p: _rank(q, p), reverse=True)
    best = ranked[0]
    poem = await fetch(f"/ganjoor/poem/{best['id']}", {**POEM_FLAGS, "catInfo": False})
    couplets = _couplets(poem.get("verses") or [], True)
    top = max(couplets, key=lambda c: _match(q, c["h"]), default=None)
    if not top:
        return {"found": False, "note": "The matching poem has no verse data."}
    score = _match(q, top["h"])
    also = [_head(p) for p in ranked[1:6] if _rank(q, p)[0] >= 0.9]
    return {
        "found": score >= 0.6,
        "match": round(score, 2),
        "poem": _head(best),
        "couplet": top["n"],
        "hemistichs": top["h"],
        "meaning": top["m"],
        "also_in": also or None,
    }


def _rank(q: str, p: dict[str, Any]) -> tuple[float, int, int]:
    """(best match, minus the poet's death year, minus the couplet position of that match) for one search hit."""
    scores = [_match(q, c) for c in _pairs(p.get("plainText"))]
    if not scores:
        return (0.0, 0, 0)
    top = max(scores)
    died = ((p.get("category") or {}).get("poet") or {}).get("deathYearInLHijri") or 9999
    return (round(top, 2), -died, -scores.index(top))


def _match(q: str, hemistichs: list[str]) -> float:
    """1.0 when the query sits inside the couplet, else the best similarity to a hemistich or the couplet."""
    parts = [_norm(h) for h in hemistichs]
    whole = " ".join(parts)
    if q and q in whole:
        return 1.0
    return max(SequenceMatcher(None, q, x).ratio() for x in [*parts, whole] if x)


# --- poems ------------------------------------------------------------------------------------------------


@tool("Read a poem")
async def gj_poem(
    id: Annotated[int | None, Field(ge=1, description="Poem id.")] = None,
    url: Annotated[str | None, Field(description="Or the ganjoor.net path, e.g. /hafez/ghazal/sh170.")] = None,
    meanings: Annotated[bool, Field(description="Include the plain-Persian meaning of each couplet.")] = True,
    max_couplets: Annotated[
        int | None, Field(ge=1, le=MAX_COUPLETS, description="Couplets to return (80 default).")
    ] = None,
) -> dict[str, Any]:
    """Read a poem: text by couplet with meanings, summary, meter, rhyme, source and previous/next poem.

    Meanings starting with «هوش مصنوعی:» are AI-written. Give id or url.
    """
    return _poem_view(await _load_poem(id, url), meanings, max_couplets)


Part = Literal["recitations", "images", "songs", "related", "quoted", "comments"]


@tool("Poem recitations, replies and comments")
async def gj_poem_extras(
    id: PoemId,
    parts: Annotated[
        list[Part] | None,
        Field(
            description="Which extras: recitations, images, songs, related, quoted, comments. Default recitations+related."
        ),
    ] = None,
) -> dict[str, Any]:
    """Recitations with mp3 links, manuscript images, songs, related poems, quoting poems and reader comments.

    Each part is trimmed (about 10 items).
    """
    want = list(dict.fromkeys(parts or ["recitations", "related"]))
    calls = {
        "recitations": (f"/ganjoor/poem/{id}/recitations", None),
        "images": (f"/ganjoor/poem/{id}/images", None),
        "songs": (f"/ganjoor/poem/{id}/songs", None),
        "related": (f"/ganjoor/section/{id}/0/related", {"skip": 0, "itemsCount": 10}),
        "quoted": (f"/ganjoor/poem/{id}/quoteds", {"skip": 0, "itemsCount": 10, "published": True}),
        "comments": (f"/ganjoor/poem/{id}/comments", None),
    }
    answers = await asyncio.gather(*(fetch(*calls[w]) for w in want))
    return {"id": id, **{w: _EXTRA[w](a or []) for w, a in zip(want, answers, strict=True)}}


def _recitations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "reciter": x.get("audioArtist"),
            "title": x.get("audioTitle"),
            "mp3": x.get("mp3Url"),
            "size_kb": round((x.get("mp3SizeInBytes") or 0) / 1024) or None,
            "timing_xml": x.get("xmlUrl"),
        }
        for x in items[:10]
    ]


def _images(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "thumbnail": x.get("thumbnailImageUrl"),
            "page": x.get("targetPageUrl"),
            "caption": _cut(x.get("altText"), 160),
        }
        for x in items[:10]
    ]


def _songs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "track": x.get("trackName"),
            "artist": x.get("artistName"),
            "album": x.get("albumName"),
            "url": x.get("trackUrl"),
        }
        for x in items[:10]
    ]


def _related(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "poem_id": x.get("targetPoemId"),
            "full_title": x.get("fullTitle"),
            "url": x.get("fullUrl"),
            "excerpt": _cut(_text(x.get("htmlExcerpt")), 160),
        }
        for x in items[:10]
    ]


def _quoted(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "poem_id": x.get("relatedPoemId"),
            "poet": x.get("cachedRelatedPoemPoetName"),
            "full_title": x.get("cachedRelatedPoemFullTitle"),
            "url": x.get("cachedRelatedPoemFullUrl"),
            "this_poem_comes_first": x.get("isPriorToRelated"),
            "couplet": _cut(" / ".join(c for c in (x.get("coupletVerse1"), x.get("coupletVerse2")) if c), 160),
            "related_couplet": _cut(
                " / ".join(c for c in (x.get("relatedCoupletVerse1"), x.get("relatedCoupletVerse2")) if c), 160
            ),
            "note": _cut(x.get("note"), 160),
        }
        for x in items[:10]
    ]


def _comments(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "author": x.get("authorName"),
            "date": (x.get("commentDate") or "")[:10] or None,
            "couplet": x["coupletIndex"] + 1 if (x.get("coupletIndex") or -1) >= 0 else None,
            "text": _cut(_text(x.get("htmlComment")), 300),
        }
        for x in items[:10]
    ]


_EXTRA = {
    "recitations": _recitations,
    "images": _images,
    "songs": _songs,
    "related": _related,
    "quoted": _quoted,
    "comments": _comments,
}


@tool("Hafez faal or random poem")
async def gj_faal(
    random: Annotated[bool, Field(description="True for a random poem (any poet) instead of a Hafez faal.")] = False,
    poet_id: Annotated[int | None, Field(ge=1, description="With random: only this poet (2 is Hafez).")] = None,
) -> dict[str, Any]:
    """Draw a Hafez faal (a random ghazal of Hafez) or, with random=True, a random poem, read with meanings.

    Same output as gj_poem.
    """
    r = await fetch("/ganjoor/poem/random", {"poetId": poet_id}) if random else await fetch("/ganjoor/hafez/faal")
    return _poem_view(await _load_poem(r["id"], None), True, None)


# --- poets and books --------------------------------------------------------------------------------------


def _life(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "born": p.get("birthYearInLHijri") if p.get("validBirthDate") else None,
        "died": p.get("deathYearInLHijri") if p.get("validDeathDate") else None,
        "birth_place": p.get("birthPlace"),
        "death_place": p.get("deathPlace"),
    }


@tool("List poets")
async def gj_poets(
    query: Annotated[str | None, Field(description="Part of the poet's name or nickname, e.g. 'حافظ'.")] = None,
    era: Annotated[str | None, Field(description="Century name like 'هشتم' (Hijri century, e.g. 'قرن هشتم').")] = None,
) -> dict[str, Any]:
    """List poets with ids, nicknames, life years (Hijri) and birthplace, filtered by name or century.

    Without a query only the first 50 are shown.
    """
    if era:
        e = _norm(era)
        poets = [
            p for c in await fetch("/ganjoor/centuries") or [] if e and e in _norm(c.get("name")) for p in c["poets"]
        ]
    else:
        poets = await fetch("/ganjoor/poets") or []
    if query:
        q = _norm(query)
        poets = [p for p in poets if q in _norm(f"{p.get('name')} {p.get('nickname')}")]
    cap = POET_CAP * 2 if query else POET_CAP
    out: dict[str, Any] = {
        "total": len(poets),
        "poets": [
            {"id": p["id"], "name": p.get("name"), "nickname": p.get("nickname"), "url": p.get("fullUrl"), **_life(p)}
            for p in poets[:cap]
        ],
    }
    if len(poets) > cap:
        out["truncated"] = f"Showing {cap} of {len(poets)}; narrow with query or era."
    return out


def _cats(children: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [{"cat_id": c.get("id"), "title": c.get("title"), "url": c.get("fullUrl")} for c in children or []]


@tool("Poet biography and books")
async def gj_poet(
    id: Annotated[int | None, Field(ge=1, description="Poet id.")] = None,
    url: Annotated[str | None, Field(description="Or the poet path, e.g. /hafez.")] = None,
) -> dict[str, Any]:
    """A poet's biography (shortened) and the top-level books to open with gj_book.

    Give id or url.
    """
    if (id is None) == (url is None):
        raise ToolError("Give exactly one of id or url.")
    r = (
        await fetch(f"/ganjoor/poet/{id}", {"catPoems": False})
        if id is not None
        else await fetch("/ganjoor/poet", {"url": _url_path(url or ""), "catPoems": False})
    )
    p, cat = r["poet"], r.get("cat") or {}
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "nickname": p.get("nickname"),
        "url": p.get("fullUrl"),
        **_life(p),
        "bio": _cut(p.get("description"), 800),
        "root_cat_id": p.get("rootCatId"),
        "book_count": len(cat.get("children") or []),
        "books": _cats(cat.get("children")),
    }


@tool("Browse a book")
async def gj_book(
    cat_id: Annotated[int, Field(ge=1, description="Book or section id (cat_id from gj_poet or a poem's book).")],
    page: Annotated[int, Field(ge=1, le=1000, description="Page of poems, 30 per page.")] = 1,
) -> dict[str, Any]:
    """Sub-books and the poems of one book or section, each with its first couplet, paged by 30.

    Open a poem with gj_poem.
    """
    r = await fetch(f"/ganjoor/cat/{cat_id}", {"poems": True, "mainSections": False})
    cat = r["cat"]
    poems = cat.get("poems") or []
    start = (page - 1) * BOOK_PAGE
    return {
        "cat_id": cat.get("id"),
        "title": cat.get("title"),
        "url": cat.get("fullUrl"),
        "poet": _poet(r.get("poet")),
        "description": _cut(cat.get("description"), 400),
        "parents": _cats(cat.get("ancestors")),
        "sub_books": _cats(cat.get("children")),
        "poem_count": len(poems),
        "page": page,
        "pages": max(1, -(-len(poems) // BOOK_PAGE)),
        "poems": [
            {"id": x.get("id"), "title": x.get("title"), "first_couplet": x.get("excerpt")}
            for x in poems[start : start + BOOK_PAGE]
        ],
    }


# --- Tajik ------------------------------------------------------------------------------------------------


@tool("Tajik Cyrillic poems")
async def gj_tajik(
    query: Annotated[str | None, Field(description="Search words in Tajik Cyrillic, e.g. 'ошиқ'.")] = None,
    poem_id: Annotated[int | None, Field(ge=1, description="Or a poem id, to read it in Cyrillic.")] = None,
    page: Page = 1,
) -> dict[str, Any]:
    """Search or read poems in Tajik Cyrillic transliteration (titles Cyrillic, poet names Persian).

    Give query to search, or poem_id to read one poem.
    """
    if (query is None) == (poem_id is None):
        raise ToolError("Give exactly one of query or poem_id.")
    if query is not None:
        r, paging = await fetch_paged(
            "/ganjoor/tajik/search", {"term": query.strip(), "PageNumber": page, "PageSize": PAGE_SIZE}
        )
        return {
            "total": paging.get("totalCount", len(r or [])),
            "page": paging.get("currentPage", page),
            "pages": paging.get("totalPages", 1),
            "results": [{**_head(p), "snippet": _snippet(p.get("plainText"), query)} for p in r or []],
        }
    path = await fetch("/ganjoor/pageurl", {"id": poem_id})
    if not path:
        raise ToolError("No poem has that id.")
    poem = (await fetch("/ganjoor/tajik/page", {"url": path, "catPoems": False}) or {}).get("poem") or {}
    lines = _pairs(poem.get("plainText"))
    return {
        **_head(poem),
        "title": (poem.get("title") or "").strip(),
        "text": [" / ".join(c) for c in lines[:DEFAULT_COUPLETS]],
        **(
            {"truncated": f"Showing {DEFAULT_COUPLETS} of {len(lines)} lines."} if len(lines) > DEFAULT_COUPLETS else {}
        ),
    }
