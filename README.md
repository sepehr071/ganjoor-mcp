<!-- mcp-name: io.github.sepehr071/ganjoor-mcp -->

<div align="center">

# ganjoor-mcp: Ganjoor (گنجور) Persian poetry MCP server for AI agents

**ganjoor-mcp is an unofficial, read-only MCP server that lets an AI agent read, search and explain classical Persian poetry on Ganjoor (گنجور, ganjoor.net), the open library of 240+ poets and 139,000 poems.**<br>
Its 18 tools search poems by words or by meaning, find the poem a quoted line comes from, read a poem with the plain-Persian meaning of every couplet, browse poets and books, and explore meters, rhymes, recitations, rhetorical devices, word use, people, places and manuscript scans.<br>
No API key or account is needed; it works in Claude, Cursor, Copilot and any other MCP client.

[![PyPI](https://img.shields.io/pypi/v/ganjoor-mcp?color=2563eb)](https://pypi.org/project/ganjoor-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/ganjoor-mcp)](https://pypi.org/project/ganjoor-mcp/)
[![CI](https://github.com/sepehr071/ganjoor-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sepehr071/ganjoor-mcp/actions/workflows/ci.yml)
[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-c2410c)](https://github.com/sepehr071/ganjoor-mcp/blob/main/LICENSE)

[For AI agents](#for-ai-agents) · [Quick start](#quick-start) · [Tools](#tools) · [Limits](#limits) · [فارسی](#فارسی)

</div>

---

## For AI agents

- **What:** unofficial MCP server (model context protocol) for ganjoor.net: full-text and semantic poem search, quoted-line lookup, poems with couplet meanings and summaries, poets, books, Hafez faal, meters and rhymes, recitations with verse timing, literary devices, word frequency, people and family trees, places, museum manuscripts, Tajik Cyrillic text.
- **Install:** `uvx ganjoor-mcp` or `claude mcp add ganjoor -- uvx ganjoor-mcp`. Transport: stdio. Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python 3.10+).
- **Auth:** none. Optional `GANJOOR_MCP_PROXY` (HTTP proxy URL, or a comma-separated list); system proxy settings are ignored.
- **Access:** read-only. It cannot log in, comment, vote or upload. Works from any country.
- **Tools:** 18, all prefixed `gj_`. Typical sequences: `gj_semantic_search` or `gj_search` -> `gj_poem`; `gj_find_verse`; `gj_poets` -> `gj_poet` -> `gj_book` -> `gj_poem` -> `gj_poem_extras`; `gj_meters` -> `gj_similar`; `gj_faal`.
- **Use when:** the user quotes a Persian couplet, asks what a poem means, wants a poem on a theme, asks about a poet, a meter, a recitation or a manuscript, or wants a Hafez faal.
- **Output:** compact JSON. Poem text is Persian and verbatim; numbers are ASCII. Meanings that start with «هوش مصنوعی:» are AI-written (Ganjoor regenerated them with Claude Opus 5.5 in November 2026); others are written by people.

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). No API key or account.

Claude Code:

```bash
claude mcp add ganjoor -- uvx ganjoor-mcp
```

Claude Desktop, Cursor, VS Code and other clients:

```json
{
  "mcpServers": {
    "ganjoor": { "command": "uvx", "args": ["ganjoor-mcp"] }
  }
}
```

Example prompts:

- "Which poem is «الا یا ایها الساقی ادر کاسا و ناولها» from, and what does it mean?"
- "Find Persian poems about the passing of time and seizing the moment."
- "Give me a Hafez faal and explain it."
- <span dir="rtl">غزل‌هایی هم‌وزن و هم‌قافیهٔ این غزل سعدی پیدا کن.</span>
- <span dir="rtl">خوانش‌های غزل اول حافظ را با لینک صوتی بیاور.</span>

Real answer (21 Nov 2026): `gj_find_verse(text="الا یا ایها الساقی ادر کاسا و ناولها")` returned Hafez, ghazal 1, couplet 1, and listed five later poems that quote the line (Jami, Helali and others) under `also_in`.

## Tools

| Tool | What it returns |
|---|---|
| `gj_search` | Poems containing all the given words, with the matching couplet |
| `gj_semantic_search` | Poems close in meaning to a theme or question, with score, summary and opening couplets |
| `gj_find_verse` | The poem and couplet a quoted line comes from, with its meaning and other poems quoting it |
| `gj_poem` | A poem by id or ganjoor.net path: couplets with meanings, summary, meter, rhyme, source, previous/next |
| `gj_poem_extras` | A poem's recitations, images, songs, related and quoting poems, comments |
| `gj_poets` | Poets with ids, years and eras, filtered by name or century |
| `gj_poet` | A poet's biography and books |
| `gj_book` | A book or section: sub-sections and poems, paged |
| `gj_faal` | A Hafez faal, or a random poem (optionally of one poet), with meanings |
| `gj_tajik` | Poems in Tajik Cyrillic script: search, or one poem |
| `gj_meters` | Poetic meters with couplet counts |
| `gj_similar` | Poems sharing a meter and rhyme, with their first couplet |
| `gj_recitations` | Recitations of a poem or book, or the newest, with mp3 links, votes and verse timing |
| `gj_literary` | Rhetorical devices and literary tags of a poem, or lookups and stats |
| `gj_words` | Word frequency in a poet's work or a book, or the count of one word |
| `gj_people` | People and characters: info, relations, family trees, a book's cast |
| `gj_places` | Places named in poems, with coordinates |
| `gj_museum` | Manuscript and artifact scans from the Ganjoor museum |

## Limits

- Semantic search runs on a separate Ganjoor service (ganjgah.ir) that is sometimes down; the tool then tries api.ganjoor.net and falls back to word search, saying so in `note`.
- Word search is an AND match on normalized text: all words must appear. Quote the line or use fewer words.
- Recitations carry no duration (only file size); verse timing is per hemistich for the best-voted recitation.
- Literary-device tags cover only part of the corpus (mostly Hafez so far). Relation types `sibling` and `spouse` in `gj_people` are inferred, not documented by the API.
- Long sections (Shahnameh, Masnavi) return 80 couplets by default; raise `max_couplets` up to 500.

## فارسی

<div dir="rtl">

**ganjoor-mcp** یک سرور MCP غیررسمی و فقط‌خواندنی برای گنجور (ganjoor.net) است. با آن یک عامل هوش مصنوعی می‌تواند شعرها را با واژه یا با معنا جست‌وجو کند، شعرِ یک بیتِ از حفظ‌خوانده را پیدا کند، شعر را با معنی ساده‌ی هر بیت بخواند، میان شاعران و کتاب‌ها بگردد، فال حافظ بگیرد و وزن‌ها، قافیه‌ها، خوانش‌ها، آرایه‌های ادبی، بسامد واژه‌ها، شخصیت‌ها، مکان‌ها و نسخه‌های خطی موزه را ببیند. بدون حساب کاربری و کلید API کار می‌کند. نصب در Claude Code:

</div>

```bash
claude mcp add ganjoor -- uvx ganjoor-mcp
```

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest -q          # offline tests on recorded fixtures
uv run python -m pytest -m live -q  # live calls to api.ganjoor.net and ganjgah.ir
```

Releases: bump the version in `pyproject.toml` and `server.json`, run `uv lock`, then push a `v*` tag; GitHub Actions publishes to PyPI.

## Disclaimer

Unofficial and not affiliated with or endorsed by Ganjoor. It is read-only and uses the public API of ganjoor.net, which can change without notice. The poems are in the public domain; the compilation, meanings, summaries, recitations and scans are the work of Ganjoor and its contributors: please credit [ganjoor.net](https://ganjoor.net) when you use them, and consider [supporting Ganjoor](https://ganjoor.net/donate).

## Author

Built and maintained by **Sepehr Radmard** (سپهر رادمرد). [LinkedIn](https://www.linkedin.com/in/sepehr-radmard) · [GitHub](https://github.com/sepehr071) · more servers in [iran-mcp](https://github.com/sepehr071/iran-mcp).

## مجوز استفاده (License)

<a href="https://www.linkedin.com/in/sepehr-radmard"><img src="https://raw.githubusercontent.com/sepehr071/iran-mcp/main/assets/license-banner.png" alt="استفادهٔ شخصی و غیرتجاری رایگان است؛ برای استفادهٔ تجاری با سپهر رادمرد تماس بگیرید. Free for personal and non-commercial use; commercial use needs a license." width="100%"></a>

**استفادهٔ شخصی و غیرتجاری رایگان است.** استفاده در شرکت، محصول پولی یا پروژهٔ مشتری به مجوز تجاری نیاز دارد؛ از راه [لینکدین](https://www.linkedin.com/in/sepehr-radmard) یا [گیت&zwnj;هاب](https://github.com/sepehr071) با سپهر رادمرد تماس بگیرید. متن کامل: [PolyForm Noncommercial 1.0.0](https://github.com/sepehr071/ganjoor-mcp/blob/main/LICENSE).

Free for personal and non-commercial use under the [PolyForm Noncommercial License 1.0.0](https://github.com/sepehr071/ganjoor-mcp/blob/main/LICENSE). Using it in a company, a paid product or a client project needs a commercial license: contact Sepehr Radmard on [LinkedIn](https://www.linkedin.com/in/sepehr-radmard) or [GitHub](https://github.com/sepehr071).
