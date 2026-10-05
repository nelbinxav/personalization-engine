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

### Unattended runs (`app/worker/`)

A job must finish with nobody watching, so every path out of a row task leaves
the row counted or back in the queue.

- **arq only retries on `Retry`.** A plain exception fails the arq job and
  strands the row at "running" with a job that never closes. Rate limits
  (`chain.RateLimited`, a source result with `meta.rate_limited`) therefore
  raise `Retry` with a growing delay; anything unexpected is caught and marks
  the row failed.
- **A limit pauses the job, and the worker restarts it.** A spent plan window
  (`UsageLimitReached`) or a row still rate-limited on its last try sets the
  job to `rate_limited` with a `resume_at`. The `resume_due_jobs` cron re-queues
  the unfinished rows when that time passes. `blocked_auth` is different: a
  credential problem needs a person, so it never resumes by itself.
- **Rows are queued under a fixed arq id** (`bookkeeping.enqueue_row`) and
  claimed before they run (`claim_row`), so resuming a job whose old tasks have
  not drained cannot run or count a row twice. This relies on `keep_result = 0`.
- **Concurrency is the Settings value**, enforced in `limiter.py` and re-read
  while jobs run. arq's `max_jobs` is only the ceiling.

The frontend's `JobWatcher` (in the app layout) raises a notice, and a browser
notification when allowed, as jobs finish or pause.

### The chain (`app/ai/chain.py`)

Two calls per row for a slot template: stage 1, then stage 4 (angles, fit and
the slot line in one call, `ai.combined_final`, on by default). The three-call
chain below still runs for a template with no `{{personalization}}` slot (the
copy is chosen from fit, so a full-body message cannot be written before fit is
known), when stage 1 is off, or when there is no active stage 4 prompt. Set
`ai.combined_final` false and reactivate the old stage 1 prompt to roll back.
The code, not the model, checks the claims (`app/ai/grounding.py`): each fact
against its source text, each angle and the fit evidence against a dossier item
(fit also needs a `tech_uses` item), and the written line for invented digits,
banned wording and naming its source. A failed check drops the angle, denies
fit or discards the line; none of them costs a call. The slot window sent to the
model is only the lines around `{{personalization}}`, not the template.

### Compact research (`ai.compact_research`, off by default)

One switch in Settings (`ai.compact_research`, with `ai.compact_chars_per_source`
= 3000 and the campaign's `ai.relevance_terms`) for two token savings:

- **Research:** each source is cut to about 3000 characters by keeping its
  highest-scoring paragraphs, in their original order (`research_select.py`),
  instead of the first 6000 characters. Scores come from the campaign's terms,
  names of the person and company, dates, events, named things and sentence
  length; cookie, legal and menu text is scored down. Recent posts are never cut.
  No terms means generic signals only. The campaign vocabulary lives in
  Settings, never in code.
- **Stage 1 signal:** stage 1 labels items `funding`, `award`, `earnings`,
  `partnership`, `customer_stack` or `certification` (`DossierStrictOut`, with
  a note appended to the stage 1 prompt). They stay in the dossier, but
  `strict_signal` sets `has_signal` false when they are all there is, so the
  row stops before stage 4. `tech_*`, `repost`, `own_post`, `podcast` and
  `event` are unchanged. A `contact_issue` still stops the row first, and a
  literal `""`/"none" in it no longer counts as one.

Off, a row runs exactly as before. When on, each row logs one `compact_research`
line (sizes, stage 1 tokens, whether stage 4 ran, total tokens; never the text).

### Line-only output (`ai.personalization_output_mode`, temporary)

`"full_message"` (default) is everything above. `"personalized_line"` runs
stage 1, then one stage 4 call (`LINE_PROMPT` in `line_prompt.py`, `LineOut`)
that writes only the line for a template that lives in the sending platform.
No template, subject, greeting or ask-first copy is read or written: a row with
nothing to say gets a blank line, never generic copy. The same angle, fit and
re-ask rules apply, plus code checks that every number is in a research source
and every proper noun is in the dossier (failing those after the re-ask blanks
the line). The CSV then has a `personalized_line` column and no
subject/message/copy_used columns. Read per row; no restart. Each row logs a
`personalization_output` line (counts and tokens only).

**Mixed batches and measurement.** A CSV row is exported by the `output_mode`
stored on it, never by the current setting; an upload holding both kinds gets
both column sets. With line mode or compact research on, each row stores
`personalization.metrics` (tokens per stage, whether stage 1 stopped or stage 4
ran, retry count, grounding failure, sufficiency, fit; counts and flags only).
`python scripts/summarize_test.py` compares line mode with compact research OFF
(A) against ON (B); the deciding figure is tokens per successful line. In line
mode a name in the line is supported by the prospect's details, then the
dossier, then the original research text; a number must be in the research.

### The three-stage chain

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

**Slot templates.** A template containing `{{personalization}}` is approved
copy. The model returns only that slot (`SlotOut`); `fill_slot()` places it and
renders `identity.*`/`raw.*` plus the sending-tool merge tags the app can fill
(`{{firstName|there}}`, `{{lastName}}`, `{{companyName|your company}}`; the
`|fallback` applies when the field is empty). Any other `{{...}}`, such as
`{{sendingAccountFirstName}}`, is left for the sending platform. A leading
`Subject:` line fixes the subject. The length limit applies to the whole email,
so the slot gets whatever the fixed copy leaves. A `thin_context` row on a slot
template still gets a draft: `generic_draft()`, the approved copy with the slot
line removed. It claims nothing about the prospect, so it does not weaken the
citation guard, and the row stays flagged. If the active stage-3 prompt
never places `{{template}}`, the chain appends the template and constraints to
it so the model never writes blind.

**Ask first, do not assume.** Being on the list is not evidence that a prospect
has the problem we solve (for the Databricks campaign: that they run
Databricks). Stage 2 returns `fit_established` with the dossier item that shows
it; without that item it counts as false. A template can carry a second piece
of approved copy, `fallback_body` ("Ask-first copy"), which asks whether they
have the problem instead of assuming it and pushing the call to action.
`copy_for()` gives that copy to every row where fit was not established,
including `thin_context` rows, and the export's `copy_used` and `fit_evidence`
columns say which a row got and why. Keep assumptions out of the ask-first
copy; that is its whole purpose.

### Subscription mode (`claude_code`)

The third credential mode runs each stage through the operator's own Claude
subscription by calling the **unmodified** Claude Code binary (`claude -p`,
tools off, `--json-schema`) in `app/ai/claude_code.py`. The operator signs in
themselves with `docker compose exec -it worker claude auth login`; the
credential lives in the `claude_code_profile` volume and the app never reads
it. **Do not replace this with an in-app Claude.ai OAuth flow or read the stored
token** - Anthropic forbids third-party apps from holding subscription
credentials, and running the unmodified binary is what keeps this permitted.
A plan usage limit raises `UsageLimitReached`, which pauses the job until the
reset time Claude Code reported (`parse_reset_time`; every 30 minutes when it
did not say) and then restarts it. Its message says "wait", not "reconnect".

### Layout

```
backend/app/
  api/v1/endpoints/   auth uploads jobs prompts templates preview settings exports
  ingest/             csv_loader, gsheet_loader, mapping (column auto-detection)
  sources/            base (the Source protocol), website, rss, news, exa (search, podcasts),
                      linkedin, linkedin_account, mcp_http, registry
  ai/                 client (credentials/OAuth), chain, grounding, claude_code,
                      openai_stage, schemas, defaults, pricing
  worker/             main (arq WorkerSettings), tasks, bookkeeping, limiter
  export/             csv_writer (streaming)
frontend/app/(app)/   overview, uploads, uploads/[id], uploads/new, jobs, jobs/[id],
                      prompts, templates, settings
frontend/components/  ui/ (design system + toast), launch-job (shared job launcher),
                      job-watcher (finish/pause notifications)
frontend/lib/         api, types, workflow (next-step logic, readiness checks, formatting)
deploy/               TAILSCALE.md (hosting guide), LINKEDIN.md (LinkedIn account setup),
                      backup.sh
```

### Frontend workflow

Each upload's page (`uploads/[id]`) is the hub: Import -> Research ->
Personalize -> Download, with the next step preselected by
`workflow.nextAction()`. `LaunchJob` is the only place jobs are queued, and
`useReadiness().blockersFor()` blocks a launch that would fail every row (no
Claude, empty offer text, no active template for the channel). Two frontend
copies of backend rules must stay in sync: `mappingProblems()` mirrors
`ingest/mapping.validate_mapping`, and the prompts page's `PER_ROW` regex
mirrors `chain._VOLATILE_TOKEN`. Colours are HSL tokens in `globals.css`
with light and dark sets; `info` (blue) means in progress and `warning`
(amber) means needs a look, so keep them apart in hue.

### Deployment

- The app is **one address**: with `NEXT_PUBLIC_API_URL=/` (the default) the
  browser calls `/api/v1/*` on the Next server, which forwards it to the api
  container (`rewrites` in `next.config.js`, target `API_INTERNAL_URL`). One
  tunnel covers everything and there is no CORS. The forward's timeout is
  raised to 5 minutes because prompt previews outlast the 30s default.
- `NEXT_PUBLIC_API_URL` is a **build arg**: Next.js inlines it into the bundle.
  Changing it means rebuilding the frontend; setting it at runtime does nothing.
- Login is throttled per account (10 failures per 15 minutes, in Redis), not
  per IP: behind a tunnel every request comes from the same address.
- `deploy/share.sh` shares the local stack through a temporary Cloudflare
  Quick Tunnel for testing.
- The api and frontend ports publish on `${BIND_ADDRESS:-127.0.0.1}`. Docker
  ports bypass the host firewall, so never default them to `0.0.0.0`; a
  Tailscale serve or tunnel on the host proxies to loopback instead.
- Backups need the database **and** `.env`: provider keys are encrypted with
  `APP_SECRET_KEY`.

### Adding a scraping source

Write a class with `key`, `label`, `target(identity)` and `fetch(...)` in
`app/sources/`, then add it to `registry.ALL_SOURCES`. Nothing else changes -
the settings UI, job launcher and CSV exporter all read that registry. Raise
`SkipSource` when the prospect lacks the input (an absence, not a failure) and
`SourceError` when the fetch genuinely failed.

### Source priority

`registry.ALL_SOURCES` is in priority order, and that order is the product
decision: the prospect's own LinkedIn post from the last two weeks, then
podcasts and interviews, their LinkedIn profile, the company's LinkedIn page,
news, and last the company website and RSS. `chain.format_research` shows
research to the model in that order and the stage-2 prompt ranks angles by it.

Research is a **funnel** (`registry.run_funnel`), not a sweep: it stops at the
first thing worth opening with. (1) The prospect's LinkedIn, one read with no
scrolling: a post in the window ends it, and the profile from the same read is
kept. (2) Podcasts, searched while the row waits its turn on LinkedIn: one
found ends it. (3) News, website and RSS together. (4) The company's LinkedIn
page only when all of that found nothing. So a row's research holds only the
step that delivered, plus the failures above it. A row holds a concurrency slot
only around the fetches that do work, never while it waits for LinkedIn, which
is why many rows show "running" during a LinkedIn job. A recent post by
the prospect about their work is a valid opener even with no link to the offer;
whether they have the problem is decided separately (`fit_established`).

What the model reads is trimmed, not what is stored: `format_research` strips
link targets and images and caps each source at `ai.research_chars_per_source`
(6000; recent posts are exempt), while the row and the export keep the full
text. A row with no usable research skips Claude entirely. Measured on 10 rows
with thinking effort low/medium/medium: about 30,000 tokens a row down to about
20,000.

Stage 1 also returns `has_signal`: when it found nothing related to the offer
and nothing the prospect said themselves, stage 2 is skipped and the row is
`thin_context` with stage 1's reason. Stage 1 dominates a row's tokens (about
two thirds, measured per stage in `personalization.usage_by_stage`), because it
is the one that reads the research. Stage 2 always receives the Settings offer
text: it is appended when the prompt does not place `{{offer_context}}`.

Podcasts and the news fallback use Exa's hosted MCP search, which needs no key
(`app/sources/exa.py`, through the small MCP client in `mcp_http.py`).

### LinkedIn provider

Proxycurl was sued by LinkedIn in Jan 2026 and shut down 4 Jul 2026. Treat the
vendor as a moving part. `app/sources/linkedin.py` is the only file that knows
which one is in use; `settings.linkedin_provider` selects it. Two are
implemented:

- `apify`: profiles and company pages, no account, cannot read posts.
- `account`: a signed-in LinkedIn account driven by the `linkedin` compose
  service (linkedin-mcp-server, the Agent Reach route; `linkedin_account.py`,
  `deploy/LINKEDIN.md`). The only way to get recent posts. Automated access
  breaks LinkedIn's terms and can get the account restricted, so reads are
  serialized, spread at an hourly rate (`settings.linkedin_reads_per_hour`,
  default 20, with a randomised gap) and capped per day
  (`settings.linkedin_daily_limit`). Rows wait for their read outside the row
  slots, which is why arq's `max_jobs` is far above the concurrency cap. A row
  normally costs one read (the person); the company page is the funnel's last
  resort. A spent cap pauses the scrape job until
  the next day. The account is connected from Settings: the api drops a flag
  in the shared `linkedin_control` volume and `deploy/linkedin-run.sh` (the
  service's entrypoint) swaps the server for its login browser, then back.
  **Do not remove or loosen that pacing to speed a job up.** The
  service returns raw page text, so the two-week filter reads LinkedIn's own age
  stamps (`split_posts`); if LinkedIn changes them, that is the function to fix.

## Conventions

- Document ids are uuid4 hex strings, not ObjectIds (`models/common.new_id`).
- Prompts and templates are **append-only**. Saving creates a new version and
  activates it; nothing is edited in place, so an old export can always be
  traced to the prompt that produced it.
- Collection access goes through `app/db/mongo.py` accessors, never raw names.
- `prospects.raw` is the original sheet row, untouched, so exports always
  reproduce the source columns first and in order.
- Model defaults to `claude-sonnet-5-5` with adaptive thinking. No
  `budget_tokens`, no assistant prefill, no `temperature`, no
  `thinking: disabled` and no forced `tool_choice` - each is a 400 on it.
- Each stage can run on its own model (`ai.stage_models`, set in Settings).
  A `gpt-` model goes through `app/ai/openai_stage.py` (OpenAI Responses API,
  same strict schema) and is always billed to the OpenAI key in Settings, even
  when Claude runs on the subscription. The intended split is a cheap model
  for stage 1, which reads the most and judges the least, and Claude for the
  angle and the message.

## Tests

`cd backend && pytest`. Covers column mapping, CSV parsing, chain rendering and
constraint checks, copy selection, limit-reset parsing, retry pacing, the
concurrency limiter and CSV export shaping - the places where a silent bug
corrupts output. There is no coverage of the network paths (scrapers, Claude).
