# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Commands

```bash
# Whole stack
docker compose up -d --build
docker compose logs -f worker
docker compose exec api python scripts/create_operator.py ops@bighammer.ai

# Backend, locally
cd backend
python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
uvicorn app.main:app --reload            # needs mongo + redis
arq app.worker.main.WorkerSettings

# Frontend, locally
cd frontend && npm install && npm run dev
npx next build                            # also type-checks
```

## Architecture

Research prospects from a CSV or Google Sheet, then generate personalized
outreach with a three-stage Claude chain. Two phases, each a queued job:
**scrape** gathers context, **personalize** writes the message.

**Stack:** FastAPI + MongoDB (motor) + Redis/arq on the backend; Next.js 16 App
Router + Tailwind on the frontend; Docker Compose for everything.

Two deliberate divergences from the sibling `gc-website` / `gc-website-backend`
repos, both load-bearing:

| | Sibling repos | Here | Why |
|---|---|---|---|
| Queue | in-process APScheduler | Redis + arq | Needs per-row retries and restart survival |
| Next.js output | `export` to Cloudflare Pages | `standalone` in Docker | Needs auth and a server |

Also: pydantic **v2** + pydantic-settings (the backend sibling is on v1).

### Request flow

```
CSV / Sheet -> /uploads/preview/*  -> staging doc (1h TTL) + suggested mapping
            -> /uploads/commit     -> Upload + one Prospect per row
            -> POST /jobs          -> one arq task PER ROW
                 scrape_prospect      -> app/sources/registry.run_sources
                 personalize_prospect -> app/ai/chain.run_chain
            -> GET /exports/{id}   -> streamed CSV
```

One arq job **per row**, never per upload. That is what gives free per-row
retry and stops a 500-row sheet dying at row 498. Progress is tracked by atomic
`$inc` on the parent job doc in `app/worker/bookkeeping.py`.

### The three-stage chain (`app/ai/chain.py`)

1. **Dossier** - raw scraped text to structured facts, each tagged with its source.
2. **Angle** - dossier + what we sell to 1-2 angles, each *citing* a fact.
3. **Draft** - angle + template to the message.

Stage 2's forced citation is the anti-hallucination guard. An angle that cannot
quote a scraped fact is dropped and the row is flagged `thin_context` rather
than shipping an invented compliment to a real prospect. **Do not "fix" a
thin_context row by loosening that check** - it is the feature.

### Two things that will bite you

**1. `ANTHROPIC_API_KEY` silently beats the OAuth profile.** The SDK credential
chain puts the env var first; even `""` wins its slot. A key set while in OAuth
mode means every request bills that key's org with no error. `app/ai/client.py`
refuses to run in that state and the worker refuses to start. Never add
`ANTHROPIC_API_KEY` to docker-compose or `.env` unless you mean API-key mode.
The API-key fallback is stored encrypted in the `settings` collection instead.

**2. Prompt caching depends on the prompt body staying prospect-free.** Each
stage's system prompt carries a `cache_control` breakpoint; per-prospect data
goes in the user turn. Putting `{{identity.*}}`, `{{raw.*}}`, `{{research}}`,
`{{dossier}}` or `{{angles}}` in a prompt *body* makes the prefix vary per row
and silently kills the cache. `_split_stable()` detects this and surfaces a
warning. Relatedly, the channel template is injected into the stage-3 prompt
**unrendered**, placeholders intact, for the same reason - `render()` is
single-pass so they survive, and the model fills them from the user turn.

### Layout

```
backend/app/
  api/v1/endpoints/   auth uploads jobs prompts templates preview settings exports
  ingest/             csv_loader, gsheet_loader, mapping (column auto-detection)
  sources/            base (the Source protocol), website, rss, news, linkedin, registry
  ai/                 client (credentials/OAuth), chain, schemas, defaults, pricing
  worker/             main (arq WorkerSettings), tasks, bookkeeping
  export/             csv_writer (streaming)
frontend/app/(app)/   uploads, jobs, prompts, templates, settings
```

### Adding a scraping source

Write a class with `key`, `label`, `target(identity)` and `fetch(...)` in
`app/sources/`, then add it to `registry.ALL_SOURCES`. Nothing else changes -
the settings UI, job launcher and CSV exporter all read that registry. Raise
`SkipSource` when the prospect lacks the input (an absence, not a failure) and
`SourceError` when the fetch genuinely failed.

### LinkedIn provider

Proxycurl was sued by LinkedIn in Jan 2026 and shut down 4 Jul 2026. Treat the
vendor as a moving part. `app/sources/linkedin.py` is the only file that knows
which one is in use; `settings.linkedin_provider` selects it. Only Apify is
implemented.

## Conventions

- Document ids are uuid4 hex strings, not ObjectIds (`models/common.new_id`).
- Prompts and templates are **append-only**. Saving creates a new version and
  activates it; nothing is edited in place, so an old export can always be
  traced to the prompt that produced it.
- Collection access goes through `app/db/mongo.py` accessors, never raw names.
- `prospects.raw` is the original sheet row, untouched, so exports always
  reproduce the source columns first and in order.
- Model defaults to `claude-opus-5` with adaptive thinking. No `budget_tokens`,
  no assistant prefill, no `temperature` - all three 400 on Opus 5.

## Tests

`cd backend && pytest`. Covers column mapping, CSV parsing, chain rendering and
constraint checks, and CSV export shaping - the places where a silent bug
corrupts output. There is no coverage of the network paths (scrapers, Claude).
