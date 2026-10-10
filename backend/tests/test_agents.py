import asyncio

import pytest
from fastapi import HTTPException

from app.ai import agent_context, chain, trainer
from app.api.v1.endpoints import agents as agents_ep
from app.models.agent import AgentIn, AgentProfile, Objection
from app.models.operator import Operator
from app.models.settings import AppSettings, CredentialMode, OutputMode

OPERATOR = Operator(email="ops@bighammer.ai", password_hash="x")


class FakeAgents:
    def __init__(self):
        self.docs: list[dict] = []

    @staticmethod
    def _match(doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    async def find_one(self, query, sort=None):
        found = [d for d in self.docs if self._match(d, query)]
        if sort:
            key, direction = sort[0]
            found.sort(key=lambda d: d[key], reverse=direction < 0)
        return found[0] if found else None

    async def update_many(self, query, update):
        for doc in self.docs:
            if self._match(doc, query):
                doc.update(update["$set"])

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._match(doc, query):
                doc.update(update["$set"])
                return

    async def insert_one(self, doc):
        self.docs.append(doc)

    async def delete_one(self, query):
        self.docs = [d for d in self.docs if not self._match(d, query)]


@pytest.fixture
def store(monkeypatch):
    fake = FakeAgents()
    monkeypatch.setattr(agents_ep.mongo, "agents", lambda: fake)
    return fake


def create(payload):
    return asyncio.run(agents_ep.create_agent(payload, OPERATOR))


def test_versioning_and_activation(store):
    first = create(AgentIn(name="Databricks", profile=AgentProfile(offer="a")))
    assert first.version == 1 and first.is_active

    second = create(
        AgentIn(lineage_id=first.lineage_id, name="Databricks", profile=AgentProfile(offer="b"))
    )
    assert second.version == 2 and second.lineage_id == first.lineage_id
    assert [d["is_active"] for d in store.docs] == [False, True]

    other = create(AgentIn(name="Other"))
    assert other.version == 1 and other.lineage_id != first.lineage_id
    assert store.docs[1]["is_active"]  # another lineage does not deactivate it

    with pytest.raises(HTTPException) as err:
        asyncio.run(agents_ep.delete_agent(second.id))
    assert err.value.status_code == 400

    asyncio.run(agents_ep.activate_agent(first.id))
    asyncio.run(agents_ep.delete_agent(second.id))
    assert len(store.docs) == 2


def test_unknown_lineage_is_404(store):
    with pytest.raises(HTTPException) as err:
        create(AgentIn(lineage_id="nope", name="x"))
    assert err.value.status_code == 404


def test_render_offer_sections_and_omits_empty():
    text = agent_context.render_offer(
        AgentProfile(
            offer="We cut Databricks cost.",
            proof_points=["Saved Acme 30%", "  "],
            objections=[Objection(objection="Too pricey", response="Pays back in a quarter")],
            never_claim=["Guaranteed savings"],
        )
    )
    assert text.startswith("We cut Databricks cost.")
    assert "- Saved Acme 30%" in text
    assert "Too pricey -> Pays back in a quarter" in text
    assert "NEVER CLAIM OR SAY\n- Guaranteed savings" in text
    assert "VOICE" not in text and "WHO IT IS FOR" not in text
    assert agent_context.render_offer(AgentProfile()) == ""


def test_agent_offer_overrides_settings_and_falls_back(store, monkeypatch):
    monkeypatch.setattr(agent_context.mongo, "agents", lambda: store)
    settings = AppSettings(offer_context="from settings")
    created = create(AgentIn(name="A", profile=AgentProfile(offer="from agent")))
    empty = create(AgentIn(name="Empty"))

    async def run(agent_id):
        return (await agent_context.settings_with_agent(settings, agent_id)).offer_context

    assert asyncio.run(run(created.id)) == "from agent"
    assert asyncio.run(run(None)) == "from settings"
    assert asyncio.run(run("missing")) == "from settings"
    assert asyncio.run(run(empty.id)) == "from settings"


def test_agent_carries_output_and_research_switches(store, monkeypatch):
    monkeypatch.setattr(agent_context.mongo, "agents", lambda: store)
    settings = AppSettings(offer_context="from settings")
    settings.ai.relevance_terms = ["global"]
    line = create(
        AgentIn(
            name="Line",
            profile=AgentProfile(
                offer="from agent",
                output_mode=OutputMode.personalized_line,
                compact_research=True,
                relevance_terms=["databricks"],
            ),
        )
    )
    plain = create(AgentIn(name="Plain", profile=AgentProfile(offer="from agent")))

    async def run(agent_id):
        return (await agent_context.settings_with_agent(settings, agent_id)).ai

    ai = asyncio.run(run(line.id))
    assert ai.personalization_output_mode is OutputMode.personalized_line
    assert ai.compact_research is True and ai.relevance_terms == ["databricks"]
    # No words on the agent: the global ones stay, and the switches are its own.
    ai = asyncio.run(run(plain.id))
    assert ai.personalization_output_mode is OutputMode.full_message
    assert ai.compact_research is False and ai.relevance_terms == ["global"]
    # The shared settings object is never modified.
    assert settings.ai.compact_research is False


def test_chat_update_keeps_the_writing_switches(monkeypatch):
    async def fake(client, *, schema_model, **kwargs):
        profile = {k: ([] if isinstance(v, list) else "") for k, v in AgentProfile().model_dump().items()
                   if k not in ("output_mode", "compact_research")}
        profile["offer"] = "new"
        return chain.StageResult(
            parsed={"profile": profile, "missing": [], "done": False},
            usage=chain.Usage(), cacheable=True, cache_hit=False,
        )

    monkeypatch.setattr(trainer, "call_stage", fake)
    settings = AppSettings()
    settings.ai.mode = CredentialMode.claude_code
    request = trainer.TrainRequest(
        profile=AgentProfile(output_mode=OutputMode.personalized_line, compact_research=True)
    )
    update = asyncio.run(trainer.update_profile(request, settings))
    assert update.profile.offer == "new"
    assert update.profile.output_mode is OutputMode.personalized_line and update.profile.compact_research


def test_chat_turn_replies_then_updates_profile(monkeypatch):
    calls = []

    async def fake(client, *, system_text, user_text, schema_model, **kwargs):
        calls.append((client, system_text, user_text, schema_model.__name__))
        if schema_model.__name__ == "ChatSchema":
            parsed = {"reply": "Who is it for?"}
        else:
            parsed = {
                "profile": {
                    "offer": "We cut cost",
                    "what_we_do": "",
                    "icp": "",
                    "proof_points": [],
                    "voice": "",
                    "sample_messages": [],
                    "objections": [{"objection": "price", "response": "payback"}],
                    "qualification": "",
                    "booking_link": "",
                    "never_claim": [],
                    "relevance_terms": ["databricks"],
                },
                "missing": ["icp"],
                "done": False,
            }
        return chain.StageResult(parsed=parsed, usage=chain.Usage(), cacheable=True, cache_hit=False)

    monkeypatch.setattr(trainer, "call_stage", fake)
    settings = AppSettings()
    settings.ai.mode = CredentialMode.claude_code
    request = trainer.TrainRequest(
        messages=[
            trainer.Message(
                role="user",
                text="We sell FinOps for Databricks",
                attachments=[trainer.Attachment(name="site.md", text="  site text ")],
            )
        ],
        profile=AgentProfile(offer="We cut cost"),
    )

    async def collect():
        return [event async for event in trainer.chat_events(request, settings)]

    events = asyncio.run(collect())

    assert [e["type"] for e in events] == ["delta", "reply_done", "profile", "done"]
    assert events[0]["text"] == "Who is it for?"
    assert events[2]["missing"] == ["icp"]
    assert events[2]["profile"]["objections"][0]["response"] == "payback"
    assert events[2]["profile"]["relevance_terms"] == ["databricks"]

    (c1, sys1, user1, _), (c2, sys2, user2, _) = calls
    assert c1 is None and sys1 == trainer.CHAT_PROMPT and sys2 == trainer.UPDATE_PROMPT
    assert "OPERATOR: We sell FinOps for Databricks" in user1
    assert "[Attached: site.md]" in user1 and "site text" in user1
    # The profile update sees the reply that was just written.
    assert "ASSISTANT: Who is it for?" in user2


def test_chat_turn_reports_failure_as_event(monkeypatch):
    async def boom(client, **kwargs):
        raise chain.ChainError("Model not found")

    monkeypatch.setattr(trainer, "call_stage", boom)
    settings = AppSettings()
    settings.ai.mode = CredentialMode.claude_code

    async def collect():
        return [e async for e in trainer.chat_events(trainer.TrainRequest(), settings)]

    assert asyncio.run(collect()) == [{"type": "error", "message": "Model not found"}]


def test_apply_profile_matches_saved_agent_and_ignores_empty():
    settings = AppSettings(offer_context="from settings")
    draft = AgentProfile(offer="draft offer", compact_research=True)
    applied = agent_context.apply_profile(settings, draft)
    assert applied.offer_context.startswith("draft offer") and applied.ai.compact_research
    # An empty draft changes nothing, so a preview never runs blind.
    assert agent_context.apply_profile(settings, AgentProfile()) is settings
