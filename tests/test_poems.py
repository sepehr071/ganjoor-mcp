import httpx
import pytest
from conftest import fixture

from ganjoor_mcp import poems

pytestmark = pytest.mark.anyio

A = "/api/ganjoor"
TOOLS = {
    "gj_search",
    "gj_semantic_search",
    "gj_find_verse",
    "gj_poem",
    "gj_poem_extras",
    "gj_poets",
    "gj_poet",
    "gj_book",
    "gj_faal",
    "gj_tajik",
}


def fx(name: str):
    return fixture(f"poems/{name}")


async def call(client, name, args=None):
    r = await client.call_tool(name, args or {})
    return r.structured_content


def test_norm_unifies_letters_and_drops_marks():
    assert poems._norm("زاهدِ خلوت\u200cنشین، دوش به مِیخانه شد") == "زاهد خلوت نشین دوش به میخانه شد"
    assert poems._norm("علي كتاب ١٢ ۳") == "علی کتاب 12 3"


def test_couplets_group_halves_and_paragraphs():
    c = poems._couplets(fx("poem_2299.json")["verses"], meanings=True)
    assert [x["n"] for x in c] == [1, 2, 3] and len(c[0]["h"]) == 2 and c[0]["m"]
    prose = poems._couplets(fx("poem_prose.json")["verses"], meanings=False)
    assert prose[0]["h"] and len(prose[0]["h"]) == 1 and prose[0]["m"] is None


async def test_tools_registered_read_only_and_described(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert TOOLS <= set(tools)
    for n in TOOLS:
        t = tools[n]
        assert t.annotations.read_only_hint is True, n
        assert t.title and t.description.splitlines()[0].endswith("."), n


async def test_search_snippet_filters_and_paging(client, api):
    def handler(request):
        return httpx.Response(
            200, json=fx("search.json"), headers={"paging-headers": '{"totalCount":6,"currentPage":2,"totalPages":2}'}
        )

    api[f"{A}/poems/search"] = handler
    r = await call(client, "gj_search", {"query": "زاهدِ خلوت\u200cنشین، دوش", "poet_id": 2, "page": 2})
    assert (r["total"], r["page"], r["pages"]) == (6, 2, 2)
    first = r["results"][0]
    assert first["id"] and first["url"].startswith("/") and first["poet"]["name"]
    assert "/" in first["snippet"] and "plainText" not in first
    q = api.calls[0].url.params
    assert q["term"] == "زاهد خلوت نشین دوش" and q["poetId"] == "2" and q["PageNumber"] == "2"
    assert "catId" not in q


async def test_semantic_search_results(client, api):
    api[f"{A}/search/semantic"] = fx("semantic.json")
    r = await call(client, "gj_semantic_search", {"query": "شب و تنهایی", "top_k": 2})
    assert api.calls[0].method == "POST" and api.calls[0].url.host == "ganjgah.ir"
    hit = r["results"][0]
    assert hit["id"] == 120740 and hit["score"] == 0.606 and len(hit["couplets"]) == 2
    assert " / " in hit["couplets"][0] and len(hit["summary"]) <= 303


async def test_semantic_retries_other_host_then_falls_back_to_text(client, api):
    def only_api_host(request):
        if request.url.host == "api.ganjoor.net":
            return httpx.Response(200, json=fx("semantic.json"))
        return httpx.Response(503, text="index not loaded")

    api[f"{A}/search/semantic"] = only_api_host
    r = await call(client, "gj_semantic_search", {"query": "شب"})
    assert r["results"][0]["id"] == 120740 and "note" not in r

    api[f"{A}/search/semantic"] = lambda request: httpx.Response(503, text="down")
    api[f"{A}/poems/search"] = fx("search.json")
    r = await call(client, "gj_semantic_search", {"query": "ماه"})  # a new query, the first answer is cached
    assert "unavailable" in r["note"] and r["results"][0]["snippet"]


async def test_find_verse_picks_couplet_and_meaning(client, api):
    api[f"{A}/poems/search"] = fx("search.json")
    api[f"{A}/poem/2299"] = fx("poem_2299.json")
    r = await call(client, "gj_find_verse", {"text": "صوفیِ مجلس که دی جام و قدح می\u200cشکست"})
    assert r["found"] is True and r["poem"]["id"] == 2299 and r["couplet"] == 2
    assert len(r["hemistichs"]) == 2 and r["meaning"]
    assert api.calls[0].url.params["term"] == "صوفی مجلس که دی جام و قدح می شکست"


def test_find_verse_rank_prefers_source_over_later_quotes():
    line = "الا یا ایها الساقی ادر کاسا و ناولها"

    def hit(text, died):
        return {"plainText": text, "category": {"poet": {"deathYearInLHijri": died}}}

    hafez = hit("اَلا یا اَیُّهَا السّاقی اَدِر کَأساً وَ ناوِلْها\r\nکه عشق آسان نمود اول ولی افتاد مشکل\u200cها", 792)
    later_open = hit("الا یا ایها الساقی ادر کاسا و ناولها\r\nمصراع دوم", 1290)
    later_close = hit("مصراع یک\r\nمصراع دو\r\nچو افتد مشکلی جامی\r\nالا یا ایها الساقی ادر کاسا و ناولها", 898)
    ranked = sorted([later_close, later_open, hafez], key=lambda p: poems._rank(poems._norm(line), p), reverse=True)
    assert ranked[0] is hafez and poems._rank(poems._norm(line), hafez)[0] == 1.0


async def test_find_verse_nothing_found(client, api):
    api[f"{A}/poems/search"] = []
    r = await call(client, "gj_find_verse", {"text": "هیچ بیتی اینجا نیست"})
    assert r["found"] is False


async def test_poem_by_id_sends_explicit_flags(client, api):
    api[f"{A}/poem/2299"] = fx("poem_2299.json")
    r = await call(client, "gj_poem", {"id": 2299})
    q = api.calls[0].url.params
    assert q["verseDetails"] == "true" and q["recitations"] == "false" and q["comments"] == "false"
    assert r["id"] == 2299 and r["poet"]["name"] == "حافظ" and r["book"]["title"] == "غزلیات"
    assert r["meter"].startswith("مفتعلن") and r["rhyme"] == "انهشد" and r["summary"]
    assert r["couplets"][0]["n"] == 1 and " / " in r["couplets"][0]["text"] and r["couplets"][0]["meaning"]
    assert r["prev"]["id"] == 2298 and r["next"]["id"] == 2300 and "truncated" not in r


async def test_poem_by_url_no_meanings_and_cap(client, api):
    api[f"{A}/poem"] = fx("poem_2299.json")
    r = await call(
        client, "gj_poem", {"url": "https://ganjoor.net/hafez/ghazal/sh170/", "meanings": False, "max_couplets": 2}
    )
    assert api.calls[0].url.params["url"] == "/hafez/ghazal/sh170"
    assert len(r["couplets"]) == 2 and all("meaning" not in c for c in r["couplets"])
    assert "Showing 2 of 3" in r["truncated"]


async def test_poem_prose_paragraphs(client, api):
    api[f"{A}/poem/41294"] = fx("poem_prose.json")
    r = await call(client, "gj_poem", {"id": 41294})
    assert r["couplets"][0]["text"] and " / " not in r["couplets"][0]["text"]


async def test_poem_needs_exactly_one_of_id_url(client, api):
    r = await client.call_tool("gj_poem", {})
    assert r.is_error and "id or url" in r.content[0].text
    r = await client.call_tool("gj_poem", {"id": 1, "url": "/x"})
    assert r.is_error


async def test_poem_http_error_is_reported(client, api):
    r = await client.call_tool("gj_poem", {"id": 999999999})
    assert r.is_error and "404" in r.content[0].text


async def test_poem_extras_default_and_trimmed(client, api):
    api[f"{A}/poem/2299/recitations"] = fx("recitations.json")
    api[f"{A}/section/2299/0/related"] = fx("related.json")
    r = await call(client, "gj_poem_extras", {"id": 2299})
    assert set(r) == {"id", "recitations", "related"}
    assert r["recitations"][0]["mp3"].endswith(".mp3") and r["recitations"][0]["reciter"]
    assert r["related"][0]["poem_id"] == 125448 and "<" not in r["related"][0]["excerpt"]


async def test_poem_extras_quoted_and_comments(client, api):
    # quoteds is empty for the sample poem, so this row is hand-made from the swagger fields
    api[f"{A}/poem/2299/quoteds"] = [
        {
            "relatedPoemId": 7,
            "cachedRelatedPoemPoetName": "سلمان ساوجی",
            "cachedRelatedPoemFullTitle": "سلمان ساوجی » شمارهٔ ۲",
            "cachedRelatedPoemFullUrl": "/salman/x/sh2",
            "isPriorToRelated": False,
            "coupletVerse1": "الف",
            "coupletVerse2": "ب",
            "relatedCoupletVerse1": "ج",
            "note": "تضمین",
        }
    ]
    api[f"{A}/poem/2299/comments"] = fx("comments.json")
    r = await call(client, "gj_poem_extras", {"id": 2299, "parts": ["quoted", "comments"]})
    assert r["quoted"][0]["couplet"] == "الف / ب" and r["quoted"][0]["related_couplet"] == "ج"
    assert r["comments"][0]["author"] and all(len(c["text"]) <= 303 for c in r["comments"])
    assert "<" not in r["comments"][0]["text"] and r["comments"][0]["date"][:2] == "20"


async def test_poets_filter_and_era(client, api):
    api[f"{A}/poets"] = fx("poets.json")
    r = await call(client, "gj_poets", {"query": "حافظ"})
    assert r["total"] == 1 and r["poets"][0]["id"] == 2 and r["poets"][0]["born"] == 726
    assert (await call(client, "gj_poets"))["total"] == 3
    api[f"{A}/centuries"] = fx("centuries.json")
    r = await call(client, "gj_poets", {"era": "قرن هشتم", "query": "یمین"})
    assert [p["id"] for p in r["poets"]] == [106]


async def test_poet_by_id_and_url(client, api):
    api[f"{A}/poet/2"] = fx("poet_2.json")
    api[f"{A}/poet"] = fx("poet_2.json")
    r = await call(client, "gj_poet", {"id": 2})
    assert r["nickname"] == "حافظ" and len(r["bio"]) <= 803 and r["books"][0]["cat_id"] == 24
    assert r["book_count"] == len(r["books"])
    await call(client, "gj_poet", {"url": "/hafez"})
    assert api.calls[-1].url.params["url"] == "/hafez"


async def test_book_pages_poems(client, api):
    api[f"{A}/cat/24"] = fx("cat_24.json")
    r = await call(client, "gj_book", {"cat_id": 24})
    assert r["title"] == "غزلیات" and r["poem_count"] == 5 and r["pages"] == 1
    assert r["poems"][0]["first_couplet"] and r["parents"][0]["cat_id"] == 9
    assert api.calls[0].url.params["poems"] == "true"
    assert (await call(client, "gj_book", {"cat_id": 24, "page": 2}))["poems"] == []


async def test_faal_and_random(client, api):
    api[f"{A}/hafez/faal"] = {"id": 2299}
    api[f"{A}/poem/random"] = {"id": 2299}
    api[f"{A}/poem/2299"] = fx("poem_2299.json")
    r = await call(client, "gj_faal")
    assert r["id"] == 2299 and r["couplets"][0]["meaning"]
    await call(client, "gj_faal", {"random": True, "poet_id": 2})
    assert api.calls[2].url.path.endswith("/poem/random") and api.calls[2].url.params["poetId"] == "2"


async def test_tajik_search_and_page(client, api):
    api[f"{A}/tajik/search"] = fx("tajik_search.json")
    r = await call(client, "gj_tajik", {"query": "ошиқ"})
    assert r["results"][0]["snippet"] and r["results"][0]["poet"]["name"] == r["results"][0]["poet"]["name"].strip()
    api[f"{A}/pageurl"] = "/hafez/ghazal/sh170"
    api[f"{A}/tajik/page"] = fx("tajik_page.json")
    r = await call(client, "gj_tajik", {"poem_id": 2299})
    assert (
        r["id"] == 2299
        and r["text"][0].startswith("Зоҳид")
        and api.calls[-1].url.params["url"] == "/hafez/ghazal/sh170"
    )
    bad = await client.call_tool("gj_tajik", {})
    assert bad.is_error
