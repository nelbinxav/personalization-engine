# SESSION HANDOVER

Written 3 October 2026 (IST). Covers one long working session on 2 to 3 October 2026 between the operator (Nelbin) and an AI coding assistant, in the repository at `/Users/machintosh/Projects/gc_projects/personalised-engine`.

Labels used throughout: **CONFIRMED** (checked in code, the running system or a source), **PROPOSED** (suggested, not built or not agreed), **ASSUMPTION**, **UNVERIFIED** (stated from a source or memory but not tested).

Read `CLAUDE.md` in the repository first. It is the architecture reference and lists rules that must not be loosened. A shorter handoff written by a parallel session, `SESSION_HANDOFF_2026_10_03_UNATTENDED_RUNS_MERGED.md`, sits next to this file and agrees with it.

---

## 1. Overall Objective

Build and run an **AI personalisation engine** for Big Hammer's outbound outreach. A list of prospects goes in as a CSV or Google Sheet; the engine researches each prospect (LinkedIn posts, podcasts, LinkedIn profile, company page, news, website), then writes a personalised opening line into an approved message template for a chosen channel (cold email, LinkedIn, WhatsApp; "cold calendar" is wanted but not built). The output is a CSV whose columns are used as merge fields in the sending tools: **Instantly** for cold email (confirmed in use), HeyReach for LinkedIn and Tantra for cold email were named in the brief.

Why: the brief's position is that referencing a prospect's recent LinkedIn post at the start of a cold email is the strongest possible opener, and few do it because LinkedIn is hard to scrape. The engine has to do this at volume (500 leads now; 1,000 and 10,000 were discussed), unattended, at the lowest token cost, without inventing facts about real people.

The immediate goal is a **500-lead Big Hammer run** for the "Reduce your Databricks Costs up to 75%" masterclass campaign (webinar Thursday 15 October 2026, 12 PM ET), then Instantly campaigns built from the output.

---

## 2. Projects / Workstreams

### 2.1 Unattended ("walk-away") job running
- **Purpose:** start a job and leave; it must finish by itself.
- **State:** built, committed, running locally. CONFIRMED by 92 unit tests and a stubbed end-to-end self-test against a throwaway database.
- **Completed:** rate-limited rows retry with growing delay (30s, 1m, 2m, 4m; 5 tries); a Claude plan limit or persistent rate limit pauses the job as `rate_limited` with a `resume_at` and a per-minute cron restarts it; unexpected errors mark the row failed instead of stranding it; rows are queued under fixed ids and claimed, so nothing runs twice; "Rows in parallel" setting is now real and live-adjustable; in-app notice plus browser notification when a job finishes or pauses.
- **In progress:** nothing.
- **Remaining:** UNVERIFIED in real conditions: no real Claude plan limit has been hit; the browser pop-up was never clicked through in a real browser; personalisation has not run at 10 in parallel (measurements were at 4).

### 2.2 Richard's feedback ("ask first, do not assume")
- **Purpose:** stop messages assuming the prospect uses Databricks.
- **State:** built and live.
- **Completed:** stage 2 returns `fit_established` plus the quoted dossier item; templates have a second copy field, `fallback_body` ("Ask-first copy"); rows without evidence get the ask-first copy; export columns `copy_used` and `fit_evidence`; new prompt versions; ask-first copy drafted for all three channels and activated.
- **Remaining:** the ask-first copy was written by the assistant and **has not been signed off** by the operator, Adi or Richard.

### 2.3 Research sources (Agent Reach work)
- **Purpose:** better research, above all recent LinkedIn posts.
- **State:** podcasts and news working and tested live; LinkedIn account route built and now signed in; never run on a real lead.
- **Completed:** source priority order; podcasts source and news fallback through Exa's free MCP search; LinkedIn posts / profile / company page through a signed-in LinkedIn account (the tool Agent Reach uses); 10-day post filter; pacing and daily cap; Settings card to connect the account; custom sign-in viewer with paste.
- **Remaining:** first real LinkedIn run; X, Facebook, Instagram not built; Apify no-login posts route PROPOSED, not built.

### 2.4 Token and cost reduction
- **Purpose:** cut Claude token use per lead (operator's instruction: "do the maximum").
- **State:** about 30,000 tokens per lead reduced to about 16,400, measured on the same 10 real rows.
- **Completed:** research trimming, lower thinking effort, skip Claude for rows with no research, switch to Claude Sonnet 5.5, early exit after stage 1, 12-item dossier cap, leaner website fetch, per-stage model and effort settings, GPT-6 Luna support (inactive, needs an OpenAI key).
- **Remaining:** PROPOSED and unanswered: sending 10 leads in one request (estimated 25 to 30% saving, with accuracy risks); a lighter Claude model for stage 1; measuring GPT-6 Luna on stage 1.

### 2.5 Hosting and access
- **Purpose:** a link the team can open, free, permanent.
- **State:** live at `https://engine.lakehousemasterclass.com`, served from the operator's Mac through a Cloudflare named tunnel, kept up by a LaunchAgent.
- **Completed:** see section 5 (Hosting).
- **Remaining:** true cloud hosting (not dependent on the Mac) is undecided; strong password and per-teammate accounts; the Cloudflare API token pasted in chat should be rolled.

### 2.6 Usage visibility and outcome labels
- **Purpose:** see plan limits and token use in the app; know which rows to send.
- **State:** built and live.
- **Completed:** Overview "Claude usage" panel (plan windows as Claude Code reports them, tokens today / 7 days / per lead / by stage); job page shows tokens and limit pauses; each row is now `personalised`, `generic` or `hold`; a contact check that holds a row when the person has died, left, or the company is gone; `personal_line` export column.

### 2.7 Outreach context document
- **Purpose:** a Word file to hand to the Big Hammer codebase / whoever writes templates and Instantly campaigns.
- **State:** done. `docs/Personalization-Engine-Outreach-Context.docx` (about 6,500 words), also copied to `~/Downloads`.
- **Remaining:** it records the state on 2 October and says LinkedIn is not connected; that line is now stale (LinkedIn has since been signed in).

### 2.8 The 500-lead Big Hammer run
- **Purpose:** first production run.
- **State:** not started. The 500-lead sheet has **not been uploaded**.
- **Remaining:** see sections 15 and 18.

### 2.9 Instantly campaigns
- **Purpose:** send the cold emails.
- **State:** advice given, nothing built. "Send to Instantly" through its API is PROPOSED and unanswered.

---

## 3. Important Context

### People
- **Nelbin Joseph**: the operator and the person in this session. Git user "Nelbin Joseph", email marketing@bighammer.ai. Often dictates by voice, so some messages are garbled ("SpinDX" = spintax, "RAPOR" = wrapper, "railwire" = Railway).
- **Adi**: sets the brief and makes the decisions (LinkedIn route, hosting, subscription versus API, models). Named in a sibling project's Azure notes as adi@growthclub.org. Suggested "free hosting like a random site or free link via GitHub".
- **Richard**: reviewed the email templates on 30 September 2026; his feedback is in section 4 and 6.
- **Aquila**: built an earlier version. The operator said to skip that; the meeting notes mentioning it predate the current engine.
- **Patrick** (Patrick.motozdigital@gmail.com): owner of a Cloudflare account that holds `acceleratemasterclass.com`. The operator's browser was signed in to it during the first Cloudflare authorisation.
- **Srinath Reddy**: Big Hammer's founder, hosts the masterclass, named in the template copy.

### Companies, tools, platforms
- **Big Hammer** (`bighammer.ai`): the client/product. An autonomous AI data-engineering platform; the campaign sells Databricks cost reduction (up to 75%).
- **Growth Club** (GitHub org `GrowthClub-org`), **Tantra** (`usetantra.com`): the agency side and its outreach product. Ticket **T-059 AI personalization**.
- **Claude subscription**: a Claude **Max** plan, organisation "boards@fintechcircle.com's Organization", signed in inside the worker container through the unmodified Claude Code binary.
- **Instantly**: cold email sending tool in use. **HeyReach** (LinkedIn) and **Tantra** (cold email) and Instantly for "cold calendar" were named in the brief.
- **Cloudflare**, **Namecheap**, **Colima** (Docker on the Mac), **Jina Reader**, **Exa**, **Serper**, **Apify**, **linkedin-mcp-server**.

### Existing systems and workflow
- The engine: FastAPI + MongoDB + Redis/arq backend, Next.js frontend, Docker Compose. Workflow in the app: Import, Research, Personalize, Download.
- Sibling projects on the same Mac under `/Users/machintosh/Projects/gc_projects/`: `content-engine-main`, `denchclaw-crm`, `pro-workflows-main`, `tantra`. Their notes show the team already runs Azure VMs (`staging.usetantra.com`, `claw.usetantra.com`; a staging VM `ce-staging`, Standard_B2als_v2, about $30 a month).

### Technical constraints and rules
- One arq job per row, never per upload (per-row retry). Do not change.
- Stage 2's forced citation is the anti-hallucination guard. Do not loosen it to "fix" rows without a personal line.
- Prompts and templates are append-only: saving creates a new version; nothing is edited in place.
- Subscription mode must keep using the unmodified Claude Code binary; never read the stored Claude token or build an in-app Claude.ai login.
- LinkedIn pacing must not be loosened to speed a job up.
- Never set `ANTHROPIC_API_KEY` in `.env` or compose unless API-key mode is intended.

### Business requirements (from Adi's brief, pasted by the operator)
- One engine for all channels: WhatsApp, cold email, cold calendar, LinkedIn.
- Upload CSV, choose channel, enter template; the engine adds scraping context and the personalised message as new columns; those columns are used as merge fields in the sending tool.
- Use Agent Reach for gated social content, specifically LinkedIn.
- Best source: recent posts on LinkedIn, then X, Facebook, Instagram, in that order, **not older than 10 days**. Then: podcasts they have been on; their LinkedIn profile; the company page; Google News or news articles; the company website including blog articles and press releases.

### Terminology
- **Slot**: `{{personalization}}` in a template; the one line the model writes.
- **Main copy / ask-first copy**: the two versions of a template (`body` / `fallback_body`).
- **Fit**: evidence that the prospect has the problem we solve (here, that they run Databricks).
- **Outreach value**: `personalised`, `generic`, `hold`.
- **Statuses**: row `done`, `thin_context` (shown as "Generic message"), `needs_review` (shown as "Hold"); job `rate_limited` (waiting for a limit, restarts itself) versus `blocked_auth` (needs a person).
- **Stage 1 / 2 / 3**: Dossier (gather facts), Angle (choose the angle), Draft (write the message).

### Assumptions established
- ASSUMPTION: "the account" in the operator's safety questions means the LinkedIn account unless hosting is the topic.
- ASSUMPTION: Adi's "Claude Sonnet 5.5, GPT-6 Luna to be used" means Sonnet for judgement and writing and Luna for the cheap fact-gathering step. This split was NOT confirmed by Adi; the engine lets each stage be set separately.

---

## 4. Decisions Already Made

| # | Decision | Why | Alternatives considered | Caveats |
|---|---|---|---|---|
| 1 | LinkedIn through a **free, signed-in LinkedIn account** "for now" (Adi) | Free; the only way Agent Reach reads gated posts | Apify no-login post scraper (about $2 per 1,000 posts, UNVERIFIED); Apify profile actors (already coded, need a key) | Breaks LinkedIn's User Agreement; the account can be restricted. Use an account that can be lost. |
| 2 | **Only the first 75 leads** of the 500 get LinkedIn research; the other 425 use the other sources | 75 leads is about 150 reads, the daily cap | All 500 with LinkedIn (about 7 days); none | Put the 75 priority leads in the first 75 rows |
| 3 | LinkedIn reads **spread over the day**: 20 an hour, 150 a day | Operator asked not to "run straight", to keep the account safe | 8 to 20 second gaps (the first implementation) | No rate is known to be safe; both numbers are in Settings |
| 4 | **Free hosting only; local is fine for now; use a Cloudflare tunnel** (Adi) | No card, no cost | Oracle Always Free VM (needs a card), existing Azure VM, Tailscale Funnel, Render/Zeabur/Back4app, Zoho Catalyst, Railway, spare computer | The link works only while the Mac is on, logged in and awake |
| 5 | Permanent hostname **`engine.lakehousemasterclass.com`** | Operator chose it from the Cloudflare account's 8 domains | `startupwebinars.com` (tried, failed, removed), `securemasterclass.com` (not on Cloudflare), `bighammerops.com` (assistant's suggestion) | The domain is used for calendar outreach; email records were verified unchanged. "For now." |
| 6 | **Stay on the Claude subscription** (Adi) | No API spend | API key (roughly $43 per 1,000 leads on Sonnet 5.5, assistant's calculation) | Jobs pause at plan limits; usage is shared with everything else on that Claude account |
| 7 | Models: **Claude Sonnet 5.5** and **GPT-6 Luna** "to be used" | Cost | Opus 5 (previous default), Haiku for stage 1 | Sonnet 5.5 is live on all three stages. Luna is built but inactive: no OpenAI key. The split between the two was not specified. |
| 8 | Thinking effort lowered to **low / medium / medium** | About 40% fewer thinking tokens | medium / high / high (previous) | One of four personalised test rows lost its line at the lower effort; judged defensible |
| 9 | **10 rows in parallel** | Operator asked for 10 simultaneous | 4 (previous) | Not yet measured at 10 |
| 10 | **One lead per chat stays** (three one-shot calls per lead) | A shared chat re-reads earlier leads, costing more; facts cannot leak between leads | Operator's idea: 10 chats, each handling 10 people | Operator's last question on this was informational; no instruction to change it |
| 11 | Rows end as **personalised / generic / hold** | "Needs review" covered two different cases | One "Needs review" label | 28 old blank rows were moved to Hold |
| 12 | A row whose contact is in doubt gets **no message at all** | A message to someone who has died or left is worse than none | Sending the generic copy | New stage 1 prompt version (v6) |
| 13 | Research text is **trimmed for the model, not in storage** (6,000 characters per source, links and images stripped) | Biggest token saving | Lower caps (rejected: evidence sits about 3,000 characters in) | Recent posts are exempt from the cap |
| 14 | **Merging stages 1 and 2 was dropped** | With the early exit in place the calculation showed almost no saving | — | Was only ever PROPOSED |
| 15 | **Zoho rejected** | Catalyst AppSail scales to zero after about 5 minutes, 15 GB-hours a month free, no MongoDB/Redis | — | UNVERIFIED beyond its docs |
| 16 | Everything on `startupwebinars.com` **removed** at the operator's request | A zone redirect sent every hostname to `https://webinar.fintechcircle.com/` | Excluding one hostname from the redirect rule | DNS record and tunnel deleted; the Cloudflare-side access tokens from the authorisations remain in those accounts |
| 17 | Skip Aquila's earlier build | Operator's instruction | — | — |

Not decided (do not treat as decisions): sign-off of the ask-first copy; the three template edits; "Send to Instantly"; 10-leads-per-request batching; cloud hosting; Apify; X posts; cold calendar; which stage GPT-6 Luna takes.

---

## 5. Current Technical Architecture

All CONFIRMED unless labelled.

### Inputs
- CSV upload (25 MB cap, no row cap) or Google Sheet URL. Column mapping to: full_name, first_name, last_name, title, company, website, linkedin_url, linkedin_company_url, email, phone, location.
- Template per channel (main copy and ask-first copy), three prompts, the "What you sell" offer text.

### Processing
```
CSV / Sheet -> upload + one Prospect per row
            -> research job (one arq task per row) -> registry.run_sources
            -> personalize job (one arq task per row) -> chain.run_chain
            -> CSV export
```
- **Research sources in priority order** (`backend/app/sources/registry.py`): `linkedin_posts`, `podcasts`, `linkedin_profile`, `linkedin_company`, `news`, `website`, `rss`. Results cached 7 days per (source, URL); posts cached 24 hours.
- **Personalise** (`backend/app/ai/chain.py`): no usable research -> no Claude call, ask-first copy. Stage 1 dossier (at most 12 items, `has_signal`, `contact_issue`). `contact_issue` set -> hold, no message. `has_signal` false -> skip stage 2. Stage 2 angles with citations plus `fit_established` / `fit_evidence`; the offer text is appended if the prompt does not place it. Stage 3 writes the slot; template and limits appended if the prompt does not place them.

### AI / model usage
- Claude Sonnet 5.5 (`claude-sonnet-5-5`) for all stages, adaptive thinking, effort low / medium / medium, through `claude -p --output-format stream-json --verbose --json-schema ...` (subscription mode). Each call is a fresh session with tools off.
- Per-stage model override (`ai.stage_models`). `gpt-` models go through `backend/app/ai/openai_stage.py` (OpenAI Responses API, `POST https://api.openai.com/v1/responses`, strict JSON schema, `reasoning.effort`, `store: false`). Tested offline only.
- API-key and OAuth Claude modes exist; not in use.

### APIs and services
- Jina Reader (`https://r.jina.ai/`), with headers `X-Retain-Images: none`, `X-Remove-Selector: nav, header`, `X-Md-Link-Style: discarded`. A Jina key is stored.
- Exa hosted MCP (`https://mcp.exa.ai/mcp`, tool `web_search_exa`, no key).
- Serper (`https://google.serper.dev/news`): a key is stored but returns 403; news falls back to Exa.
- Apify actors `dev_fusion~linkedin-profile-scraper`, `dev_fusion~linkedin-company-detail`: coded, no key stored.
- LinkedIn service: `stickerdaniel/linkedin-mcp-server:4.26.1`, MCP over streamable HTTP at `http://linkedin:8080/mcp`, tools used `get_person_profile` (sections "posts"), `get_company_profile` (sections "posts"), `get_my_profile`. The server also exposes `send_message` and `connect_with_person`; the engine never calls them.
- A small MCP client: `backend/app/sources/mcp_http.py`.

### Scripts
- `deploy/mac-always-on.sh` (LaunchAgent target), `deploy/linkedin-run.sh` (LinkedIn service entrypoint/supervisor), `deploy/linkedin-viewer.html` (sign-in viewer with paste, served as `/pe.html` on port 6080), `deploy/share.sh` (temporary Cloudflare quick tunnel), `deploy/backup.sh`, `backend/scripts/create_operator.py`.

### GitHub
- Remote `nelbinxav`: `https://github.com/nelbinxav/personalization-engine.git` (private; local `main` tracks it). PR #1 (template slot) and **PR #2 `unattended-runs-and-research-sources`** are merged; HEAD `c3ee1ab`, merged 3 October 2026 00:04 IST by a parallel session.
- Remote `origin`: `https://github.com/GrowthClub-org/personalization-engine.git`, still at the first scaffold commit. Do not push there unless asked.

### Browser automation
- Only inside the LinkedIn service container (Chromium driven by the MCP server, Xvfb, x11vnc, noVNC on port 6080 during sign-in).

### Authentication
- App: email + password operators, session cookie, 10 failed logins per 15 minutes per account. One operator exists: `you@bighammer.ai`.
- Claude: subscription sign-in stored in the `claude_code_profile` volume.
- LinkedIn: session stored in the `linkedin_profile` volume. Connected from Settings -> Research -> LinkedIn account -> Connect LinkedIn.
- Cloudflare tunnel: credentials file in `~/.cloudflared/`.

### Data stores
- MongoDB database `personalization` (collections: settings, uploads, prospects, jobs, prompts, templates, operators, sessions, source_cache, staging, counters). Redis for the arq queue. All in Docker volumes on the Mac.

### Outputs
- CSV columns after the originals: `research_<source>` x7, `research_errors`, then `outreach`, `channel`, `subject`, `message`, `personal_line`, `angle_used`, `evidence`, `evidence_source`, `fit_evidence`, `copy_used`, `status`, `status_note`, `model`, `cost_usd`.

### Hosting
- The operator's Mac (MacBook), Docker under Colima (4 CPU, 6 GB). Cloudflare named tunnel `pe-engine`, id `de64ef85-1c29-49de-ae6b-0020b6846337`, in "Marketing@bighammer.ai's Account"; CNAME `engine.lakehousemasterclass.com` -> `<id>.cfargotunnel.com` (added by hand by the operator); `~/.cloudflared/config.yml` routes it to `http://127.0.0.1:3000`.
- LaunchAgent `ai.bighammer.personalization-engine` (`~/Library/LaunchAgents/`) runs `deploy/mac-always-on.sh`: starts Colima, `docker compose up -d`, then `caffeinate -i cloudflared tunnel --no-autoupdate run`. Log: `~/Library/Logs/personalization-engine.log`. `.env` has `COMPOSE_PROFILES=linkedin`.
- Down when the Mac sleeps (closing the lid), is off, or is logged out.

### Integrations
- PROPOSED, not built: Instantly API push; Apify posts; X/Twitter posts; cold calendar channel; spintax.

---

## 6. Personalisation Engine

### How it works now
See section 5. One lead per chat: each lead gets up to three separate one-shot Claude calls; nothing is shared between leads. With 10 in parallel, up to 10 such calls run at once. 500 leads is up to 1,500 calls, fewer because rows stop early.

### Prompt structure (live versions, stored in MongoDB, full text in the docx Appendix A)
- **Stage 1, v6 "Dossier prompt + contact check"**: Step 1 confirm identity of each source; Step 2 extract with source keys; relationship to a technology stated precisely (uses / sells around / talks about); POSTS AND PODCASTS section; WHAT MATTERS MOST (6 items, Databricks-specific); CAN THIS PERSON BE CONTACTED AS ADDRESSED; KEEP IT SHORT (12 items); FINAL STEP: has_signal.
- **Stage 2, v4 "Angle prompt + source priority"**: five tests (Cited, Relevant, About them, Accurate about the stack, Safe to say); RANKING by source (linkedin_posts, podcasts, linkedin_profile, linkedin_company, news, website and rss); THE RECENT-POST EXCEPTION TO TEST 2; HOW MANY (one to three, none is fine); SPECIAL CASES; FIT section.
- **Stage 3, v4 "Draft prompt + recent-post opener"**: fill only the slot; use one angle; opener at most 2 sentences and 45 words; never reveal the research except their own recent post; WHEN EVIDENCE OF FIT IS NOT ESTABLISHED; WHEN THE ANGLE IS THEIR OWN RECENT POST; VOICE and banned-word list; channel notes (mentions a calendar invite channel that does not exist).
- The prompts are hard-coded to the Databricks campaign. Another client needs its own versions.

### Templates (live)
- Email v6 "Ferrari masterclass (subject A) + ask-first", limit 1,500 characters, subject up to 78. LinkedIn v5 "Connector note A1 (post-reactive) + ask-first", 300. WhatsApp v5 "Masterclass opener + question + ask-first", 600.
- Placeholders: `{{personalization}}`, `{{firstName|there}}`, `{{lastName}}`, `{{companyName|your company}}`, `{{identity.*}}`, `{{raw.Column}}`; anything else such as `{{sendingAccountFirstName}}` is left for the sending tool. A leading `Subject:` line fixes the subject.
- Ask-first email copy (drafted by the assistant, live, unsigned):
  ```
  Subject: is Databricks part of your stack?

  Hi {{firstName|there}},

  {{personalization}}

  A question before anything else: does {{companyName|your team}} run Databricks?

  If it does, and the bill is something you'd like to bring down, that's what we work on. BigHammer.ai moves the workloads that don't need premium compute onto right-sized compute, with no manual rewrites and no downtime.

  If that's relevant, reply and I'll send over how it works, plus a seat at our founder's next cost teardown on Thursday 15 October if you want one.

  If you're not on Databricks, tell me and I won't follow up.

  {{sendingAccountFirstName}}
  Data Engineering, BigHammer.ai
  ```

### Richard's feedback, 30 September 2026 (as supplied by the operator)
The campaign was jumping to the assumption that the prospect uses Databricks, then immediately pushing the masterclass, without context showing they use Databricks. Make the messaging more direct and contextually appropriate: ask whether they use Databricks and whether they want to save money. Adi acknowledged it. Requirements drawn from it: research before personalisation; do not assume Databricks use from list membership; use evidence to establish relevance; do not force the masterclass CTA without an established pain point; focus on cost saving / unblocking innovation when the context supports it. A separate earlier task: Richard tests 10 prospects across LinkedIn, email and WhatsApp, gives feedback, and the personalisation is iterated. The operator said he would check on Richard's feedback; no further feedback arrived in this session.

### CSV / Google Sheet workflow
Upload, map columns, Research (row limits: Trial 3, 10, 25, 75, 100, All; sources can be ticked per job; a second job on the same upload takes only rows the first has not claimed), Personalize (choose channel), Download.

### Python scripts
None standalone. The engine is the app. Not discussed: any separate Python personalisation script.

### Claude / ChatGPT / API usage
Claude subscription through Claude Code in the worker. ChatGPT in a browser was not discussed. OpenAI API only for GPT-6 Luna (inactive).

### Browser-authenticated approaches
Only LinkedIn (section 7). A browser-authenticated ChatGPT/Claude approach was not discussed.

### Current problems
- In testing, 7 or 8 of 10 leads got no personal line; none of the test leads had Databricks evidence, so every lead received the ask-first copy.
- Results vary run to run on identical research (the Borde row was personalised in 2 of 4 runs).
- A finding during the session: the Settings "What you sell" text had never reached the model, because the live prompts did not place `{{offer_context}}`. Fixed: stage 2 now always receives it.

### Scalability and token concerns
See sections 9 and 12.

### Desired final workflow
Upload a list, choose the channel, start, walk away, get notified, download, and use the columns as merge fields in the sending tool, at minimum token cost. Operator also wants: model choice per step in a dropdown (exists), usage and limits visible in the app (exists), LinkedIn connected from Settings (exists).

### Concrete examples (real test rows)
- **Personalised:** Marc Boulet, BGIS. Evidence (news): "Veritas Capital said it will leverage its technology investing playbook to accelerate BGIS's digital and AI roadmap and drive strategic M&A." Line: "Veritas is putting more capital behind BGIS's digital and AI roadmap, and that kind of push tends to land on finance as more data and AI workloads to plan for." `copy_used` = `ask_first`.
- **Generic:** Kristi Calderwood, Cascade Energy. No personal line; ask-first copy; note explains no data-platform signal.
- **Hold:** Pava LaPere, EcoMap Technologies. Research calls her the company's "late founder". No message. The operator was told to remove that row from the list.

---

## 7. LinkedIn / Scraping System

### Data wanted
The prospect's own posts from the last 10 days (top priority), their profile, the company page and its recent posts.

### Why authentication is required (CONFIRMED)
- Posts are visible only to signed-in members. Jina Reader on a LinkedIn profile and activity page returned LinkedIn error 999 (blocked).
- Agent Reach reads LinkedIn only through `linkedin-mcp-server`, which drives a browser signed in to a real account; its fallback is Jina on public pages.

### What is built (CONFIRMED)
- Provider `account` in `backend/app/sources/linkedin_account.py`; service in Docker Compose profile `linkedin`.
- Pacing: one read at a time; 20 reads an hour with a randomised gap (108 to 252 seconds at that rate, never under 8 seconds); 150 reads a day; a spent daily cap pauses the research job until just after midnight UTC. A lead costs about two reads (person with posts, company with posts). So about 75 leads a day, taking about 7.5 hours; 1,000 leads about two weeks.
- LinkedIn rows queue one at a time on their own lock so they do not block other rows.
- 10-day filter reads LinkedIn's age stamps ("5h", "3d", "1w", "2mo", "1yr"). "1w" (7 to 13 days) is kept and labelled. Reposts are labelled as not the person's own words. If no age stamps can be parsed the raw text is passed with an instruction.
- Connect flow: Settings button -> api writes a flag in the `linkedin_control` volume -> the service's supervisor swaps to the login browser -> link shown in Settings (`http://127.0.0.1:6080/pe.html#?path=...`), opens only on the machine running the engine. The viewer types the Mac clipboard in as keystrokes on Cmd+V or the Paste button.
- Status: **signed in**, 1 read used on 2 October.

### Limitations and unknowns
- UNVERIFIED: the post-age parser against real LinkedIn page text. It was written from LinkedIn's usual format and unit-tested on synthetic text only.
- UNVERIFIED: any safe rate. LinkedIn publishes none.
- ASSUMPTION: LinkedIn is more suspicious of a session from a cloud server address than from an office or home connection.
- The session expires over time; rows then report "not signed in" and the account must be reconnected.
- Facebook and Instagram in Agent Reach need a logged-in desktop Chrome and cannot run on a server. X needs login cookies (`TWITTER_AUTH_TOKEN`, `TWITTER_CT0`) and a handle column. None built.

### Alternatives
- **Public web search (Exa):** CONFIRMED it finds public LinkedIn posts with dates, but for the person tested the newest was from July; not fresh enough for a 10-day rule.
- **Apify "no cookies" post scrapers:** UNVERIFIED listing: HarvestAPI "LinkedIn Profile Posts Bulk Scraper (No Cookies)" at $2.00 per 1,000 posts; a company posts scraper at $4.00 per 1,000. Not run, not built.
- **Multiple-account approach:** not discussed.
- **ZoomInfo:** not discussed.
- **Unipile:** see section 8.
- **Profile search / profile visits:** the MCP server has `search_people`; not used or discussed further.

---

## 8. Unipile

**Not discussed as an option in this session.** No pricing, account counts, channels or capabilities were raised or verified. The only facts:
- CONFIRMED: the Settings page's LinkedIn provider list includes "Unipile (not implemented)" with the note "Account-based: uses your own LinkedIn session, so it carries account-ban risk rather than scraping-vendor risk." This text predates the session.
- CONFIRMED: Unipile appears as a sponsor banner in the `linkedin-mcp-server` README.

Everything else this section's template asks for (why considering it, pricing, number of accounts, WhatsApp, whether one account suffices) is **open and unverified**. Do not assume any of it.

---

## 9. AI / Claude / ChatGPT / API Architecture

- **Models discussed:** Claude Opus 5 (previous default), Claude Sonnet 5.5 (now live, $2 / $10 per million tokens), Claude Opus 5.5 ($4 / $20), Claude Haiku 4.5 (PROPOSED for stage 1), GPT-6 Luna (`gpt-6-luna`, $0.10 input / $0.50 output / $0.01 cached input per million; 1.05M context; structured outputs and reasoning effort supported; Tier 1 limits 500 RPM / 500K TPM, per OpenAI's model page).
- **Subscription versus API:** subscription chosen (decision 6). Subscription runs through the Claude Code binary; an OpenAI stage is always an API-key call.
- **Limits (CONFIRMED):** Claude Code's `stream-json` output carries a `rate_limit_event` with the plan's `five_hour` and `seven_day` utilisation and reset times. The engine stores the latest reading and shows it. Last reading, 2 October 16:22 UTC: 5-hour 48% (reset 17:10 UTC), weekly 65% (reset 3 October 22:00 UTC). These cover all use of that Claude account.
- **Token measurements** on the same 10 real rows: see section 12.
- **Sonnet 5.5 request rules:** no `thinking: disabled`, no forced `tool_choice`, no `budget_tokens`, no prefill, no `temperature`.
- **Not added:** the server-side refusal `fallbacks` parameter for API mode (the path is unused).
- **Security:** a Cloudflare API token was pasted in chat and should be rolled; the app is publicly reachable with one account; the LinkedIn MCP endpoint has no authentication but is reachable only inside the Docker network; the Claude credential is never read by the app.
- **What to inspect in the repository:** `backend/app/ai/chain.py`, `claude_code.py`, `openai_stage.py`, `pricing.py`, `backend/app/worker/tasks.py`, `bookkeeping.py`, `limiter.py`, `backend/app/sources/*`.

---

## 10. Existing GitHub / Open-Source System

### Agent Reach
- URL: https://github.com/Panniantong/Agent-Reach (MIT, v1.5.0 at inspection).
- CONFIRMED by reading the code: it is an installer, health checker and skill file that tells an AI coding agent which outside tools to run; its README says there is "no wrapper layer". Channels: web (Jina Reader), Exa search via mcporter, RSS, YouTube (yt-dlp), GitHub (gh), Twitter/X (twitter-cli, cookies), Reddit, Facebook and Instagram (OpenCLI, logged-in desktop Chrome), LinkedIn (`linkedin-mcp-server`, fallback Jina), and Chinese platforms (XiaoHongShu, Bilibili, V2EX, Xueqiu, Boss Zhipin, Xiaoyuzhou).
- How it fits: nothing to import; its upstream tools were added as sources (Exa search, the LinkedIn MCP server).
- Not in it: reading social platforms without an account; pacing, daily limits or a 10-day filter; a podcast-appearance finder.

### linkedin-mcp-server
- URL: https://github.com/stickerdaniel/linkedin-mcp-server (Apache-2.0, v4.26.1; Docker image `stickerdaniel/linkedin-mcp-server:4.26.1`).
- CONFIRMED: returns pages as raw text; tool calls queue sequentially; `--login --login-viewer` shows the login browser on port 6080 for at most 30 minutes; refuses requests to unknown hostnames unless listed in `FASTMCP_HTTP_ALLOWED_HOSTS`; its README says accounts using automated tools can be restricted or banned.
- Risk: the tool can break when LinkedIn changes; the post text format is not guaranteed.

### Our repository
- `nelbinxav/personalization-engine` (private). See section 5.

### Reference documentation named in the task list
- Tantra website scraping docs: https://adisuja.github.io/tantra-workshop-live/site/help/templates-and-ai/website-scraping/
- Tantra AI personalization docs: https://adisuja.github.io/tantra-workshop-live/site/help/templates-and-ai/ai-personalization/
- These were **not opened** in this session. Also named but not inspected: "merge tags and spintax", "personalisation troubleshooting", a "personalisation test list", "the existing outreach engine".

---

## 11. Data Flow

```
Lead list (CSV or Google Sheet; 500 leads, 75 priority leads first)
 -> upload, map columns (name, title, company, website, LinkedIn URLs, email)
 -> Research job 1: first 75 rows, all sources (LinkedIn account paced 20/hour, 150/day)
 -> Research job 2: remaining 425, LinkedIn sources unticked (podcasts via Exa, news via Exa, website via Jina, blog feed)
 -> Personalize (email channel): per lead
        no research           -> ask-first copy, no Claude call
        stage 1 facts         -> contact issue? -> HOLD, no message
                              -> no signal?     -> generic (ask-first) copy
        stage 2 angle + fit   -> no angle       -> generic (ask-first) copy
        stage 3 personal line -> placed in main copy (fit shown) or ask-first copy (fit not shown)
 -> Download CSV
 -> review: drop outreach = hold (read status_note); split on copy_used
 -> Instantly: map personal_line to a custom variable; main campaign and ask-first campaign
 -> send
```

---

## 12. Cost Analysis

| Item | Figure | Status |
|---|---|---|
| Tokens per lead, 52 old rows (Opus 5, website only) | 22,976 average (thin rows about 19,000; full rows about 29,000) | CONFIRMED measurement |
| Tokens per lead, 10 rows, Opus 5 with podcasts and news | 30,159; 57 s per lead | CONFIRMED |
| After trimming and lower effort (Opus 5) | 19,828; 35 s | CONFIRMED |
| Sonnet 5.5, trimmed | 16,418 (17,085 on a repeat); 17 to 18 s | CONFIRMED |
| After early exit and 12-item cap | 16,418; 14 s | CONFIRMED |
| Per stage (average) | stage 1 about 11,500; stage 2 about 5,600 (on 7 of 10 rows); stage 3 about 4,600 (on 2 of 10) | CONFIRMED |
| Tokens per 1,000 leads | about 16 million now (was 23M, then 30M) | Calculation |
| API cost per 1,000 leads | about $230 (Opus before), about $140 (Opus trimmed), about $43 (Sonnet 5.5) | Assistant's calculation from the price table; cache writes priced at 1.25x |
| Earlier estimates | $155 per 1,000 and $1,550 per 10,000 on Opus 5 | Superseded |
| Personalisation time | 1,000 leads: 4.5 to 6.5 hours at first; a bit over an hour now if no limit is hit. 500 leads at 10 parallel: about 15 minutes of processing, ESTIMATED 35 to 40 leads a minute, but expected to span more than one 5-hour window | Estimates; 10-parallel not measured |
| Research time | 2 to 4 s per row without LinkedIn; 425 rows about half an hour | Measured at small scale |
| Claude prices | Sonnet 5.5 $2 / $10; Opus 5 $5 / $25; Opus 5.5 $4 / $20; Haiku 4.5 $1 / $5 per million | From the model reference |
| GPT-6 Luna | $0.10 / $0.50 per million; cached input $0.01 | CONFIRMED on OpenAI's page |
| Apify LinkedIn posts (no cookies) | $2.00 per 1,000 posts; company posts $4.00 per 1,000; about $10 per 1,000 leads at 5 posts each | UNVERIFIED listing; calculation |
| Apify free credit | about $5 a month | UNVERIFIED (from memory) |
| Jina Reader | 20 requests a minute without a key, about 500 with a free key; a one-time allowance covering roughly a couple of thousand sites | UNVERIFIED (from memory) |
| Serper | 2,500 free searches, one time | UNVERIFIED (from memory) |
| Oracle Always Free VM | 2 OCPU / 12 GB; idle instances can be reclaimed after 7 days under 20% CPU, network and memory; needs a card | CONFIRMED in Oracle's docs |
| Tailscale free plan | up to 6 users | CONFIRMED on the pricing page (an earlier search said 3) |
| Cloudflare Zero Trust free | 50 users; needs a domain on Cloudflare | From search results |
| Cloudflare .com registration | $10.46 a year | From search results |
| Azure staging VM (sibling project) | about $30 a month (Standard_B2als_v2) | From that project's notes |
| Railway | about $5 to 20 a month; its terms forbid scraping without permission | UNVERIFIED estimate; terms from search |
| Render | about $7+ a month per service | UNVERIFIED estimate |
| Zoho Catalyst AppSail free | 900 GB-minutes (15 GB-hours) a month | From its docs |
| Hugging Face Spaces | Docker Spaces need PRO, $9 a month | From search results |
| Unipile | no figures discussed | — |

---

## 13. Current Problems / Bottlenecks

### Blocking
1. The 500-lead sheet is not uploaded, and the 10-lead trial with LinkedIn has not been run.
2. LinkedIn post reading is unproven on real data.

### Important
3. The ask-first copy is live but unsigned.
4. Template text names "Thursday 15 October"; main templates use `{{identity.first_name}}` (gives "Hi ," when empty).
5. Claude weekly window was at 65% (resets 3 October 22:00 UTC); 500 leads need roughly 8 million tokens and will probably pause across windows.
6. The link depends on the Mac being awake; it was on battery.
7. One app account (`you@bighammer.ai`) on a public sign-in page.
8. Most test leads got no personal line; quality on real LinkedIn data is unknown.
9. The Cloudflare API token was shared in chat.
10. Data lives only in the Mac's Docker volumes; no backup has been taken.

### Nice to solve
11. GPT-6 Luna inactive (no OpenAI key).
12. `docs/Personalization-Engine-Outreach-Context.docx` and `docs/Personalization-Engine-Handbook.docx` are out of date in places.
13. Stage 3 prompt mentions a calendar channel that does not exist.
14. X, Facebook, Instagram, cold calendar, spintax not built.
15. `origin` (GrowthClub-org) is far behind.
16. Adding LinkedIn to a sheet researched without it means redoing its research.

---

## 14. Open Questions

| Question | Why it matters | How to verify | Decision that depends on it |
|---|---|---|---|
| Do real LinkedIn posts come through with correct ages? | Core feature | Research the first 10 rows; read `research_linkedin_posts` | Whether to run the 75 |
| Is the ask-first copy approved? | It is what most leads receive | Operator / Adi / Richard read it | Whether to personalise the 500 |
| How should Sonnet 5.5 and GPT-6 Luna be split? | Adi named both | Ask Adi; add an OpenAI key; rerun the same 10 rows | Stage models |
| Build 10-leads-per-request batching? | Possible 25 to 30% saving, accuracy risk | Prototype and measure on the same rows | Token strategy |
| Build "Send to Instantly"? | Removes the CSV step | Operator's answer; needs an Instantly API key and two campaign IDs | Integration work |
| Make the three template edits? | Stale date, bad greeting | Operator's answer | New template versions |
| Apify for LinkedIn posts? | No account risk, faster | An Apify token and a test run | LinkedIn route at scale |
| Is 20 reads an hour safe for the account? | Account loss | Unknowable in advance; watch for LinkedIn warnings | Pacing settings |
| How many leads fit in one plan window? | Run duration | Watch the usage panel during the run | Subscription versus API |
| Where will it be hosted long-term? | Mac dependence | Adi | Azure / Oracle / stay local |
| Does 10 in parallel work on the 6 GB Colima VM? | Stability | Watch the first run | Concurrency setting |
| Did Richard give further feedback? | Prompt iteration | Operator said he would check | Prompt changes |
| Is the Cloudflare token rolled? | Security | Cloudflare dashboard | — |
| Anything about Unipile, ZoomInfo, multiple LinkedIn accounts | Not discussed here | — | — |

---

## 15. Next Actions

### Do Now
| Action | Owner | Dependency | Output |
|---|---|---|---|
| Put the 75 priority leads first; upload the 500-lead sheet; map columns | Nelbin | Sheet ready | Upload in the app |
| Trial: research then personalise the first 10 rows | Nelbin | Upload; Mac awake and on power | First real LinkedIn results |
| Check the trial: posts present, ages right, messages sensible | Nelbin + AI | Trial done | Go / no-go |
| Sign off or edit the ask-first copy; decide the three template edits | Nelbin / Adi / Richard | — | New template versions if needed |

### Do Next
| Action | Owner | Dependency | Output |
|---|---|---|---|
| Research job 1: limit 75, all sources | Nelbin | Trial OK | 75 leads with LinkedIn (about 7.5 hours) |
| Research job 2: All, three LinkedIn sources unticked | Nelbin | Can start straight after job 1 | 425 leads (about half an hour) |
| Personalise the whole sheet, email channel | Nelbin | Both jobs done; ideally after the weekly reset | Messages |
| Download; drop `hold`; split on `copy_used`; build two Instantly campaigns | Nelbin | Personalisation done | Campaigns |
| Run `deploy/backup.sh` | Nelbin | — | Backup |
| Set a strong password; create an account per teammate | Nelbin | — | Accounts |
| Roll the Cloudflare API token | Nelbin / token owner | — | New token |

### Later
| Action | Owner | Dependency | Output |
|---|---|---|---|
| Add an OpenAI key and measure GPT-6 Luna on stage 1 | Nelbin + AI | Key | Measured saving |
| Decide and build: batching, Send to Instantly, Apify posts, X posts, cold calendar, spintax | Adi decides | Answers | Features |
| Cloud hosting | Adi | Decision | Server |
| Test LinkedIn and WhatsApp channel messages | Nelbin | — | Tested channels |
| Refresh the two docx files | AI | After the run | Current documents |

---

## 16. Things We Should NOT Forget

- A frontend change needs `docker compose up -d --build --no-deps frontend`; backend code is mounted, so `docker compose restart api worker` picks it up. Check for running jobs before restarting the worker.
- The Mac must stay awake and logged in; lid closed means the link is down.
- `.env` has `COMPOSE_PROFILES=linkedin`; without it `docker compose up` leaves the LinkedIn service stopped.
- The LinkedIn sign-in link opens only on the Mac running the engine, lasts 30 minutes, and paste works with Cmd+V or the Paste button after allowing clipboard access.
- A stale Chromium `SingletonLock` once blocked sign-in after a restart; the supervisor now clears it.
- Usage percentages cover all use of the Claude account, not only the engine.
- Cost on job pages shows as tokens because subscription mode bills nothing per row.
- 28 older rows are on Hold only because they predate the ask-first copy; redoing personalisation fixes most.
- One deceased prospect (Pava LaPere, EcoMap) is in the test sheet "BigHammer.ai _ CEO_CFOs".
- The Serper key returns 403; news silently uses Exa.
- `startupwebinars.com` redirects everything to `https://webinar.fintechcircle.com/`; do not reuse it. `securemasterclass.com` is on Namecheap nameservers, not Cloudflare. `acceleratemasterclass.com` belongs to Patrick's Cloudflare account.
- The Cloudflare token given is read-only for DNS; the DNS record had to be added by hand.
- Dictated messages can contradict themselves; ask rather than guess.
- The operator's messages sometimes arrive entirely as pasted text; they are his own words.

---

## 17. Files / Links / Resources

### Live
- https://engine.lakehousemasterclass.com : the engine (public sign-in page).
- http://localhost:3000 : the same, on the Mac.

### Repository files
- `CLAUDE.md` : architecture and rules.
- `SESSION_HANDOFF_2026_10_03_UNATTENDED_RUNS_MERGED.md` : short handoff from a parallel session.
- `SESSION_HANDOVER_2026_10_03_FULL.md` : this file (not committed when written).
- `docs/Personalization-Engine-Outreach-Context.docx` : context for templates and Instantly (also in `~/Downloads`).
- `docs/Personalization-Engine-Handbook.docx` : team handbook from 26 September (older).
- `deploy/TAILSCALE.md` : hosting guide (Oracle + Tailscale Funnel / Serve, Cloudflare notes).
- `deploy/LINKEDIN.md` : LinkedIn account setup and risks.
- `deploy/mac-always-on.sh`, `deploy/linkedin-run.sh`, `deploy/linkedin-viewer.html`, `deploy/share.sh`, `deploy/backup.sh`.
- `docker-compose.yml`, `.env` (secrets; contains `COMPOSE_PROFILES=linkedin`).

### On the Mac, outside the repository
- `~/.cloudflared/config.yml` and the tunnel credentials file.
- `~/Library/LaunchAgents/ai.bighammer.personalization-engine.plist`; log `~/Library/Logs/personalization-engine.log`.

### GitHub
- https://github.com/nelbinxav/personalization-engine (working remote, private).
- https://github.com/GrowthClub-org/personalization-engine (`origin`, stale).
- https://github.com/Panniantong/Agent-Reach
- https://github.com/stickerdaniel/linkedin-mcp-server

### Documentation and APIs
- Tantra docs (two URLs in section 10).
- Instantly API: https://developer.instantly.ai/api-reference/lead/add-leads-in-bulk-to-a-campaign-or-list.md (`POST /api/v2/leads/add`, up to 1,000 leads, fields include `personalization` and `custom_variables`, Bearer auth).
- OpenAI model page: https://developers.openai.com/api/docs/models/gpt-6-luna.md
- Exa MCP: https://mcp.exa.ai/mcp
- Webinar: https://webinar.bighammerai.com

### Accounts
- App operator: `you@bighammer.ai`.
- Claude: Max plan, "boards@fintechcircle.com's Organization".
- Cloudflare: "Marketing@bighammer.ai's Account" with 8 domains: analyticsseminars.com, analyticswebinars.com, bighammerai.com, bighammerops.com, dataopsmasterclass.com, dataopswebinars.com, lakehousemasterclass.com, lakehousewebinars.com. "Boards@fintechcircle.com's Account" holds startupwebinars.com. Patrick's account holds acceleratemasterclass.com.
- LinkedIn: a free account, signed in inside the engine.
- Keys stored in the engine: Jina, Serper (rejected). Not stored: Apify, OpenAI, Instantly.

### Uploads in the database (tests)
- "ENGINE TEST - web4 26-09 sample (10)", "PERSONALISATION ENGINE TEST - web4 (20)", "BigHammer.ai _ CEO_CFOs - Sheet1 (1)" (20), "test-prospects" (15).

---

## 18. Exact Current State

**CURRENTLY WORKING:**
The engine at https://engine.lakehousemasterclass.com (tunnel, LaunchAgent, all six containers up). Research from podcasts, news, website, blog feeds. LinkedIn account signed in (1 of 150 reads used on 2 October). Claude Sonnet 5.5 on the subscription, effort low / medium / medium, 10 rows in parallel, research cap 6,000 characters. Prompts v6 / v4 / v4; templates email v6, LinkedIn v5, WhatsApp v5, each with ask-first copy. Usage panel, job notices, outcome labels. No jobs running.

**COMPLETED:**
Everything in section 2.1 to 2.7. Code committed and merged as PR #2 into `nelbinxav/main` (HEAD `c3ee1ab`); 92 backend tests pass; frontend builds.

**BLOCKED BY:**
Nothing technical. The 500-lead run needs the operator to upload the sheet.

**WAITING FOR:**
The operator: upload and trial; sign-off of the ask-first copy; answers on the three template edits, "Send to Instantly" and batching. Adi: the Sonnet / Luna split, long-term hosting. Richard: any further feedback.

**NEXT STEP:**
Upload the 500-lead sheet with the 75 priority leads first, research and personalise the first 10 rows, and check that recent LinkedIn posts appear with sensible ages before running the rest.

---

## 19. Continuation Instructions for the Next AI

**Retain:** the rules in `CLAUDE.md`; the decisions in section 4; the run plan in section 15; that the operator wants plain, direct answers and usually wants things built rather than described; that he dictates and his messages can be garbled.

**Do not assume:**
- that LinkedIn post reading works on real data; it has never been run on a lead;
- that any LinkedIn rate is safe;
- that the ask-first copy is approved;
- that Adi's "Sonnet 5.5 and GPT-6 Luna" means a particular split;
- anything about Unipile, ZoomInfo or multiple LinkedIn accounts: they were not discussed;
- that figures marked UNVERIFIED are right (Apify, Jina, Serper allowances and prices);
- that a notification or a pasted block is the operator's approval of a pending question.

**Verify before implementing:**
- running jobs, before restarting the worker or the LinkedIn service;
- the live state (`docker compose ps`, Settings, the usage panel) rather than this document, which is a snapshot;
- for any outward change (DNS, pushes to `origin`, sending anything), ask first. The operator had one bad experience with a domain that redirected and asked for everything to be removed.

**Immediate next task:** support the 10-row trial. When it has run, inspect `research_linkedin_posts` and the messages; if posts are missing or ages are wrong, fix `split_posts` in `backend/app/sources/linkedin_account.py` against the real text.

**Final decisions:** 1 to 13 and 15 to 17 in section 4.

**Still open:** ask-first copy sign-off; the three template edits; "Send to Instantly"; 10-leads-per-request batching; Apify; X posts; cold calendar; spintax; the model split; long-term hosting; rolling the Cloudflare token.

**Contradictions to keep in view, not resolve silently:**
- The operator once asked for posts "from 10 days ago, with at least a 10-day gap"; Adi's brief says posts "should not be older than 10 days". The engine implements the brief (within 10 days, "1w" kept).
- The operator asked for "10 chats, one chat used for 10 people"; the engine uses one lead per chat, and he was told why. He did not restate the request.
- The operator said prompt tuning "is done" early on, yet prompts changed several times afterwards.
- He mixed "10,000" and "1,000" leads in one message; the next real run is 500.
- Sources disagreed on Oracle's free tier (4 OCPU / 24 GB versus 2 / 12; Oracle's docs say 2 / 12), on Tailscale's free user limit (3 versus 6; the pricing page says 6), and on whether Tailscale Funnel is on the free plan (a reading of the pricing page said no; the Funnel docs say all plans).
- The outreach context docx says LinkedIn is not connected; it now is.
