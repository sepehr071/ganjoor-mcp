import json

import httpx
import pytest
from conftest import FIXTURES

pytestmark = pytest.mark.anyio

A = "/api"
TOOLS = [
    "gj_meters",
    "gj_similar",
    "gj_recitations",
    "gj_literary",
    "gj_words",
    "gj_people",
    "gj_places",
    "gj_museum",
]
METER = "مفاعیلن مفاعیلن فعولن (هزج مسدس محذوف یا وزن دوبیتی)"


def fx(name):
    """Route handler serving explore/<name>.json: its `data`, plus the `paging-headers` header when saved."""
    saved = json.loads((FIXTURES / "explore" / f"{name}.json").read_text(encoding="utf-8"))
    headers = {"paging-headers": json.dumps(saved["paging"])} if saved["paging"] else {}
    return lambda request: httpx.Response(200, json=saved["data"], headers=headers)


async def call(client, name, **args):
    r = await client.call_tool(name, args)
    assert not r.is_error, r.content
    return r.structured_content


async def test_tools_registered_read_only(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in TOOLS:
        t = tools[name]
        assert t.annotations.read_only_hint is True and t.title, name
        assert t.description.splitlines()[0].endswith("."), name


async def test_meters_sorted_capped_and_filtered(client, api):
    api[f"{A}/ganjoor/rhythms"] = fx("rhythms")
    r = await call(client, "gj_meters")
    assert r["total"] == 12 and r["meters"][0]["id"] == 23 and r["meters"][0]["couplets"] > 100000
    assert api.calls[0].url.params["sortOnVerseCount"] == "true"
    r = await call(client, "gj_meters", query="هزج  مسدس")
    assert [m["id"] for m in r["meters"]] == [12, 13]  # sorted by couplet count


async def test_similar_resolves_meter_and_pages(client, api):
    api[f"{A}/ganjoor/rhythms"] = fx("rhythms")
    api[f"{A}/ganjoor/poems/similar"] = fx("similar")
    r = await call(client, "gj_similar", meter="هزج مسدس محذوف", rhyme_letters="ا", poet_id=12, page=2)
    q = api.calls[-1].url.params
    assert q["metre"] == METER and q["rhyme"] == "ا" and q["poetId"] == "12" and q["PageNumber"] == "2"
    assert r["total"] == 1444 and r["poems"][0]["poet"] and " / " in r["poems"][0]["couplet"]
    await call(client, "gj_similar", meter=12)
    assert api.calls[-1].url.params["metre"] == METER


async def test_similar_unknown_meter_is_error(client, api):
    api[f"{A}/ganjoor/rhythms"] = fx("rhythms")
    r = await client.call_tool("gj_similar", {"meter": "نامعلوم"})
    assert r.is_error


async def test_recitations_for_poem_with_votes_and_timing(client, api):
    api[f"{A}/ganjoor/poem/2299/recitations"] = fx("poem_recitations")
    api[f"{A}/audio/votes/2299/scores"] = fx("votes")
    api[f"{A}/audio/verses/3323"] = fx("verses")
    r = await call(client, "gj_recitations", poem_id=2299, with_timing=True)
    first = r["recitations"][0]
    assert first["mp3"].startswith("https://i.ganjoor.net/") and first["up_votes"] == 8 and first["reciter"]
    assert r["timing_for"] == 3323 and r["timing"][2][1] == 5286


async def test_recitations_cat_latest_and_argument_check(client, api):
    api[f"{A}/audio/cattop1/24"] = fx("cattop1")
    api[f"{A}/audio/published"] = fx("published")
    r = await call(client, "gj_recitations", cat_id=24, limit=2)
    assert r["total"] == 4 and len(r["recitations"]) == 2
    assert api.calls[-1].url.params["includePoemText"] == "false"
    r = await call(client, "gj_recitations", latest=True, limit=2)
    assert r["total"] == 31232 and api.calls[-1].url.params["PageSize"] == "2"
    assert (await client.call_tool("gj_recitations", {})).is_error


async def test_literary_poem_tags_use_device_and_slot_names(client, api):
    api[f"{A}/ganjoor/literary/devices"] = fx("devices")
    api[f"{A}/ganjoor/literary/poem/2132/tags"] = fx("lit_poem_tags")
    r = await call(client, "gj_literary", poem_id=2132)
    t = r["tags"][0]
    assert t["device"] and all(p["slot"] for p in t["parts"])
    assert any(p.get("text") for p in t["parts"])


async def test_literary_views(client, api):
    api[f"{A}/ganjoor/literary/devices"] = fx("devices")
    api[f"{A}/ganjoor/literary/stats/tags"] = fx("lit_stats_tags")
    api[f"{A}/ganjoor/literary/stats/overview"] = fx("lit_overview")
    api[f"{A}/ganjoor/literary/concepts"] = fx("concepts")
    d = await call(client, "gj_literary")
    assert d["devices"][0]["key"] == "tashbih" and d["devices"][0]["definition"]
    r = await call(client, "gj_literary", view="tags", tag="tashbih")
    assert api.calls[-1].url.params["deviceId"] == "1" and r["tags"][0]["parts"][0].startswith("مشبّه:")
    r = await call(client, "gj_literary", view="stats")
    assert r["tags"] > 0 and r["devices"][0]["name"]
    r = await call(client, "gj_literary", view="concepts", tag="باغ")
    assert r["concepts"][0]["name"] == "باغ"
    assert (await client.call_tool("gj_literary", {"view": "tags", "tag": "nope"})).is_error


async def test_words_top_and_single(client, api):
    api[f"{A}/ganjoor/poet/2"] = fx("poet")
    api[f"{A}/ganjoor/wordcounts/9"] = fx("wordcounts")
    api[f"{A}/ganjoor/wordsums/9"] = fx("wordsums")
    r = await call(client, "gj_words", poet_id=2, limit=4)
    assert r["cat_id"] == 9 and r["total_words"] == 81806 and r["words"][0]["count"] > r["words"][1]["count"]
    assert api.calls[0].url.path.endswith("/poet/2") and api.calls[1].url.params["PageSize"] == "4"
    api[f"{A}/ganjoor/wordcounts/bycat/count"] = fx("word_count")
    api[f"{A}/ganjoor/wordcounts/bycat"] = fx("word_bycat")
    r = await call(client, "gj_words", poet_id=2, word="عشق")
    assert r["count"] == 251 and r["by_book"][0]["name"] == "غزلیات" and r["total_words"] == 81806


async def test_words_missing_word_and_bad_args(client, api):
    api[f"{A}/ganjoor/wordcounts/bycat/count"] = lambda request: httpx.Response(200, content=b"null")
    r = await call(client, "gj_words", cat_id=24, word="zzz")
    assert r["count"] == 0
    assert (await client.call_tool("gj_words", {})).is_error


async def test_people_search_relations_tree_and_book(client, api):
    api[f"{A}/people"] = fx("people")
    r = await call(client, "gj_people", query="رستم")
    assert r["total"] == 2 and r["people"][0]["name"] == "رستم"
    api[f"{A}/people/1/relations"] = fx("relations")
    r = await call(client, "gj_people", id=1, view="relations")
    assert api.calls[-1].url.params["evidenceLimit"] == "1"
    assert r["relations"][0]["relation"] == "parent_of" and r["relations"][0]["couplet"]
    api[f"{A}/people/1/familytree"] = fx("familytree")
    r = await call(client, "gj_people", id=1, view="familytree")
    assert r["root"] == "کیومرث" and r["edges"][0] == ["کیومرث", "parent_of", "سیامک"]
    api[f"{A}/ganjoor/cat/33/persongraph"] = fx("persongraph")
    r = await call(client, "gj_people", cat_id=33)
    assert r["people"] == 6 and r["main"] and "nodes" not in r


async def test_places_poem_cat_and_search(client, api):
    api[f"{A}/ganjoor/poem/2132/geotag"] = fx("poem_geotag")
    r = await call(client, "gj_places", poem_id=2132)
    assert r["places"][0]["lat"] and r["places"][0]["name"]
    api[f"{A}/ganjoor/cat/24/geotag"] = fx("cat_geotag")
    r = await call(client, "gj_places", cat_id=24)
    assert api.calls[-1].url.params["onlyWithLocation"] == "true"
    assert r["places"][0]["poems"][0]["url"].startswith("/hafez/")
    api[f"{A}/locations"] = fx("locations")
    r = await call(client, "gj_places", query="شیراز")
    assert r["total"] == 3 and {p["name"] for p in r["places"]} >= {"شیراز"}
    assert (await client.call_tool("gj_places", {})).is_error


async def test_museum_search_detail_and_item(client, api):
    api[f"{A}/artifacts/search"] = fx("art_search")
    r = await call(client, "gj_museum", query="حافظ")
    assert api.calls[-1].url.params["term"] == "حافظ" and r["total"] == 84
    m = r["manuscripts"][0]
    assert m["link"] == f"https://museum.ganjoor.net/items/{m['slug']}" and m["pages"] and m["cover"]
    api[f"{A}/artifacts/nowras"] = fx("art_detail")
    r = await call(client, "gj_museum", slug="nowras")
    assert r["pages"] == 344 and len(r["images"]) == 3 and r["contents"][0]["page"] == "p0021"
    assert "<br" not in r["description"]
    api[f"{A}/artifacts/nowras/p0002"] = fx("art_item")
    r = await call(client, "gj_museum", slug="nowras", item="p0002")
    assert r["of"] == 344 and r["next"] == "p0003" and r["link"].endswith("/nowras/p0002")


async def test_upstream_404_is_a_tool_error(client, api):
    r = await client.call_tool("gj_museum", {"slug": "nope"})
    assert r.is_error
