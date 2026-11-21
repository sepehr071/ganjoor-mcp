import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]

CASES = [
    ("gj_meters", {"query": "رمل"}, lambda r: r["meters"]),
    ("gj_similar", {"meter": 12, "rhyme_letters": "ا", "poet_id": 12}, lambda r: r["poems"][0]["couplet"]),
    ("gj_recitations", {"poem_id": 2299, "with_timing": True}, lambda r: r["recitations"][0]["mp3"] and r["timing"]),
    ("gj_literary", {"poem_id": 2132}, lambda r: r["tags"][0]["device"]),
    ("gj_words", {"cat_id": 24, "word": "عشق"}, lambda r: r["count"] > 100),
    ("gj_people", {"query": "رستم"}, lambda r: r["people"]),
    ("gj_places", {"poem_id": 2132}, lambda r: r["places"][0]["lat"]),
    ("gj_museum", {"query": "حافظ"}, lambda r: r["manuscripts"][0]["link"]),
]


@pytest.mark.parametrize("name,args,check", CASES, ids=[c[0] for c in CASES])
async def test_live(client, name, args, check):
    r = await client.call_tool(name, args)
    assert not r.is_error, r.content
    assert check(r.structured_content)
    assert len(r.content[0].text) < 8000
