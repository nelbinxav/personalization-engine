# SESSION HANDOVER: Agents chat, 7 October 2026

Covers one session on 7 October 2026 between the operator (Nelbin) and an AI coding assistant, in `/Users/machintosh/Projects/gc_projects/personalised-engine`. It adds to, and does not replace, `SESSION_HANDOVER_2026_10_03_FULL.md` (whole-project context, decisions, costs, run plan) and `SESSION_HANDOFF_2026_10_03_UNATTENDED_RUNS_MERGED.md`. Read `CLAUDE.md` first: it is the architecture reference and the Agents section is already updated for this session.

Labels: **CONFIRMED** (checked in code, tests or the running stack), **UNVERIFIED** (built but not exercised in real conditions), **PROPOSED** (suggested, not built).

The work is **paused, not finished**. The operator will continue later.

---

## 1. State in one paragraph

The Agents feature (a trained profile per offer) was started in an earlier session and was uncommitted. This session rebuilt its training screen as a real streaming chat, moved all training and personalization controls out of Settings and into the agent, added a "Try it on a real row" panel, and produced a questionnaire for the client (Big Hammer) whose answers will be fed into the chat. **None of this is committed.** Backend tests: 213 pass (`cd backend && .venv/bin/python -m pytest -q`). Frontend type-checks (`npx tsc --noEmit -p .` in `frontend/`). The api, frontend and worker containers were rebuilt or restarted after the last change, with no jobs running at the time.

## 2. What was done

### 2.1 Agent training is a live chat (CONFIRMED in tests; UNVERIFIED live)
- Before: a 320px box, one question per turn, a separate "source text" box, a "Start" button.
- Now: `POST /agents/chat` streams server-sent events. Each turn is two model calls: (1) the reply as plain text, streamed word by word; (2) a structured call that returns the updated profile. Events: `delta`, `reply_done`, `profile`, `done`, `error`.
- The trainer talks like a colleague, asks for what is missing in prose, accepts anything pasted or attached, and applies edits ("drop the second proof point", "never mention pricing") at any time.
- Streaming is real only on the Anthropic API/OAuth path (`client.messages.stream`). `claude_code` (the Max subscription, which is what the operator uses) and `gpt-` models send the reply in one piece. Same two calls either way.
- Files: `backend/app/ai/trainer.py` (rewritten), `backend/app/api/v1/endpoints/agents.py` (`/chat` replaces `/train`), `backend/app/ai/schemas.py` (`TrainerSchema` replaced by `ChatSchema` and `ProfileUpdateSchema`), `frontend/components/agent-chat.tsx` (new), `frontend/lib/api.ts` (`streamPost`), `frontend/lib/types.ts` (`ChatMessage`, `ChatEvent`).
- Chat UI: full-height thread, one auto-growing input, Enter sends, Shift+Enter newline, paperclip / drag / paste for text files (txt, md, csv, json, html, xml, yaml, log), Stop button, 12,000 characters read per attachment. Only the newest message resends its attachment text; older ones are name-only to save tokens. The transcript is kept in the browser's localStorage per saved agent (attachment text stripped). The profile is the real memory: reopening an agent does not need the old chat.
- A new agent opens with the trainer speaking first. An existing agent opens with an empty thread and a hint.

### 2.2 Everything about training and personalization now lives under Agents
- Removed from Settings: "What you sell", "What gets written" (output mode), "Compact research", "Relevant words". Settings keeps the Claude connection, default model, per-stage models and effort, research sources and LinkedIn pacing, concurrency, provider keys.
- `AgentProfile` gained `relevance_terms` (filled by the trainer), `output_mode` and `compact_research` (set by checkboxes, never by the trainer). The profile panel has a "How it writes and researches" section.
- `settings_with_agent()` now also swaps the agent's output mode, compact-research switch and relevant words into the settings a job sees. Empty relevant words fall back to the global list. New `apply_profile(settings, profile)` does the work and is reused by preview.
- The trainer's profile update merges onto the existing profile, so the trainer cannot overwrite the writing switches.
- The launch form now preselects the active agent and only shows a blank option when there are no agents.
- The old global fields still exist in `AppSettings` and in the database. They are the **fallback for a job run without an agent** and are no longer editable in the UI.

### 2.3 "Try it on a real row" (CONFIRMED in tests; UNVERIFIED live)
- `frontend/components/agent-try.tsx` on the Agents page. Pick an upload that has researched rows and a channel, press Try it, then "Another row".
- Uses `POST /preview` with two new fields: `agent_profile` (the unsaved profile on screen, wins over `agent_id`) and `offset` (skips that many researched rows, wraps round). Nothing is saved. Shows the personal line or message, fit evidence, angles, warnings and the cost of the try.

### 2.4 Client questionnaire
- A Claude Doc, "Big Hammer: Personalization Agent Questionnaire", 10 sections of question / answer tables: offer, who it is for, proof, voice and examples, never-say, objections, fit and keywords, the ask, channels and templates, volume / compliance / sign-off. Link: https://claude.ai/artifact/Qz7xgwSaaAHxtpcSwNpWnz (opened for the operator; **not shared with anyone**).
- Plan for the answers: paste them into the agent chat (or attach as a text file). The trainer fills the profile and asks about gaps. Then use Try it and correct in chat.

### 2.5 Tests added or changed (`backend/tests/test_agents.py`)
Chat turn emits `delta, reply_done, profile, done`; a failing turn becomes one `error` event; the profile update keeps the writing switches; an agent carries its switches into settings and falls back to global words; `apply_profile` ignores an empty draft.

## 3. Not verified (do these first when resuming)
1. **Live chat has never been run.** The session could not sign in. Only confirmed: the route exists (401 unauthenticated through both the api and the Next proxy) and the page loads. Open `localhost:3000/agents`, choose New agent, and check the greeting, the reply, and the profile filling.
2. **Streaming through the Next proxy.** If replies on the API-key or OAuth path arrive all at once, something is buffering. The response sets `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`; Next compression is the likely culprit if it happens. On the subscription path (`claude_code`) one-piece replies are expected, not a bug.
3. **Try it** has not been clicked in a browser. It needs an upload with researched rows and an active template for the chosen channel.
4. **Settings page** after the removals: check it loads and saves without the removed fields (the save no longer sends `offer_context` or the three research-writing fields; the backend treats absent as unchanged).
5. Whether the model split of two calls per turn is acceptable on the Max plan's usage windows (each chat turn costs two calls).

## 4. Known gaps and decisions
- **Never-claim list is prompt text only, not a code check.** The operator said to leave it for now. It is the recommended thing to add before the 500-lead run (guard it in `backend/app/ai/grounding.py` like the other claims).
- Text files only for attachments. PDF and Word need a parser (PROPOSED). Pasting a URL for the trainer to read is not built; the website source fetcher exists and could be reused (PROPOSED).
- Templates and the ask-first copy are still on their own Templates page. The operator's rule is that training and personalization belong under Agents, so moving templates in (per agent, per channel, drafted by the chat from the voice and examples) is the recommended next improvement (PROPOSED, not agreed).
- Third idea (PROPOSED): show why a row was written the way it was on the job page, reusing the Try it evidence view.
- Chat history is browser-local. Clearing site data or switching browser loses the thread (the profile is unaffected).
- The prompts page still lists `{{offer_context}}` and now says it comes from the agent you pick.

## 5. Files touched this session
New: `frontend/components/agent-chat.tsx`, `frontend/components/agent-try.tsx`, this file. Rewritten: `backend/app/ai/trainer.py`, `frontend/app/(app)/agents/page.tsx`. Changed: `backend/app/ai/agent_context.py`, `backend/app/ai/schemas.py`, `backend/app/models/agent.py`, `backend/app/api/v1/endpoints/agents.py`, `backend/app/api/v1/endpoints/preview.py`, `backend/tests/test_agents.py`, `frontend/app/(app)/settings/page.tsx`, `frontend/app/(app)/prompts/page.tsx`, `frontend/components/launch-job.tsx`, `frontend/lib/api.ts`, `frontend/lib/types.ts`, `frontend/lib/workflow.ts`, `CLAUDE.md`.

The earlier, also uncommitted, Agents work from the previous session is in the same working tree: `backend/app/models/agent.py`, `agent_context.py`, `endpoints/agents.py`, `api_router.py`, `db/init_db.py`, `db/mongo.py`, `models/job.py` (`options.agent_id`), `worker/tasks.py`, `endpoints/jobs.py`, `layout.tsx`.

## 6. How to resume
- Backend tests: `cd backend && .venv/bin/python -m pytest -q` (macOS path; `CLAUDE.md` shows the Windows one).
- Frontend change: `docker compose up -d --build --no-deps frontend`. Backend code is mounted: `docker compose restart api worker`. **Check there are no running jobs before restarting the worker.**
- Stack was up at the end: api, frontend, mongo, linkedin (worker restarted cleanly, concurrency 10).
- **Nothing is committed.** Do not commit or push without the operator asking. Commit trailer to use: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- `ANTHROPIC_API_KEY` must stay out of `.env` and compose unless API-key mode is intended (see `CLAUDE.md`).

## 7. The wider plan (unchanged, from the 3 October handover, section 15)
1. Train the Big Hammer agent in the new chat (use the client's answers once back) and save it as v1.
2. Upload the 500-lead sheet with the 75 priority leads first and map columns.
3. Trial: research then personalize the first 10 rows with the agent. Check LinkedIn posts appear with sensible ages; if not, fix `split_posts` in `backend/app/sources/linkedin_account.py`.
4. Then research job 1 (75 leads, all sources), job 2 (425, LinkedIn sources unticked), personalize the whole sheet, download, drop `hold`, split on `copy_used`, build the Instantly campaigns.
5. Still open: ask-first copy sign-off (also in the questionnaire), the three template edits, Send to Instantly, 10-leads-per-request batching, Apify and X posts, cold calendar, spintax, the Sonnet / GPT-6 Luna split, hosting, strong passwords and per-teammate accounts, rolling the Cloudflare token.

## 8. Immediate next task
Send the questionnaire to Big Hammer. When answers arrive, paste them into the agent chat, complete and save the agent, use Try it on a few researched rows, then start the 10-row trial. Resolve section 3 (live verification) first, because the chat has never run against a real model.
