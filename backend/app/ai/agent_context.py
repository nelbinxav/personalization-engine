"""Turn a trained Agent profile into the offer text the chain already reads.

The chain takes one string (`AppSettings.offer_context`). An agent replaces it
for a job, so nothing downstream changes and the prompt bodies stay
prospect-free for caching.
"""
from app.db import mongo
from app.models.agent import Agent, AgentProfile
from app.models.settings import AppSettings


def _lines(title: str, items: list[str]) -> str:
    items = [item.strip() for item in items if item.strip()]
    if not items:
        return ""
    return title + "\n" + "\n".join(f"- {item}" for item in items)


def render_offer(profile: AgentProfile) -> str:
    parts = [
        profile.offer.strip(),
        f"WHAT WE DO\n{profile.what_we_do.strip()}" if profile.what_we_do.strip() else "",
        f"WHO IT IS FOR\n{profile.icp.strip()}" if profile.icp.strip() else "",
        _lines("PROOF WE MAY USE", profile.proof_points),
        f"HOW WE QUALIFY\n{profile.qualification.strip()}" if profile.qualification.strip() else "",
        f"VOICE\n{profile.voice.strip()}" if profile.voice.strip() else "",
        _lines("SAMPLE MESSAGES IN OUR VOICE", profile.sample_messages),
        _lines(
            "COMMON OBJECTIONS",
            [
                f"{o.objection.strip()} -> {o.response.strip()}"
                for o in profile.objections
                if o.objection.strip()
            ],
        ),
        _lines("NEVER CLAIM OR SAY", profile.never_claim),
    ]
    return "\n\n".join(part for part in parts if part)


async def settings_with_agent(settings: AppSettings, agent_id: str | None) -> AppSettings:
    """`settings` with the agent's offer, output mode and research switches in place
    of the Settings ones. An unknown id or an empty profile leaves the Settings
    values, so a job never runs blind."""
    if not agent_id:
        return settings
    doc = await mongo.agents().find_one({"_id": agent_id})
    if not doc:
        return settings
    return apply_profile(settings, Agent.model_validate(doc).profile)


def apply_profile(settings: AppSettings, profile: AgentProfile) -> AppSettings:
    """`settings` as a job run with this profile would see them. An empty offer
    leaves the Settings values. Also used to try a draft that is not saved."""
    offer = render_offer(profile)
    if not offer:
        return settings
    ai = settings.ai.model_copy(
        update={
            "personalization_output_mode": profile.output_mode,
            "compact_research": profile.compact_research,
            # Empty: keep the global words rather than reading with none.
            "relevance_terms": profile.relevance_terms or settings.ai.relevance_terms,
        }
    )
    return settings.model_copy(update={"offer_context": offer, "ai": ai})
