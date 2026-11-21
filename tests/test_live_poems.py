import pytest

from ganjoor_mcp import poems

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_search():
    r = await poems.gj_search("دل من", poet_id=2)
    assert r["total"] > 0 and r["results"][0]["snippet"]


async def test_semantic_search():
    r = await poems.gj_semantic_search("شب و تنهایی", 3)
    assert r["results"] and r["results"][0]["id"]  # also true for the text fallback


async def test_find_verse():
    r = await poems.gj_find_verse("زاهد خلوت\u200cنشین، دوش به مِیخانه شد")
    assert r["found"] and r["poem"]["id"] == 2299 and r["couplet"] == 1


async def test_poem():
    r = await poems.gj_poem(id=2299, max_couplets=3)
    assert r["poet"]["name"] == "حافظ" and r["meter"] and r["couplets"][0]["meaning"]
    assert (await poems.gj_poem(url="/hafez/ghazal/sh170"))["id"] == 2299


async def test_poem_extras():
    r = await poems.gj_poem_extras(2299)
    assert r["recitations"][0]["mp3"].endswith(".mp3")


async def test_poets_and_poet():
    assert (await poems.gj_poets("حافظ"))["poets"][0]["id"] == 2
    assert (await poems.gj_poet(id=2))["books"]


async def test_book():
    r = await poems.gj_book(24)
    assert r["poem_count"] > 400 and r["poems"][0]["id"]


async def test_faal():
    assert (await poems.gj_faal())["couplets"]


async def test_tajik():
    assert (await poems.gj_tajik(query="ошиқ"))["results"]
