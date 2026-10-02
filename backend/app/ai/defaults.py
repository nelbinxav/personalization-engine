"""Starter prompts and templates, seeded on a fresh database.

These are deliberately opinionated rather than blank. They are ordinary
versioned rows -- editing one in the UI creates version 2 and nothing here is
consulted again.

The available placeholders in prompts and templates:
  {{offer_context}}   what we sell, from Settings
  {{research}}        the raw scraped context (stage 1 only)
  {{dossier}}         stage 1 output (stages 2 and 3)
  {{angles}}          stage 2 output (stage 3)
  {{identity.*}}      mapped prospect fields, e.g. {{identity.first_name}}
  {{raw.*}}           any original sheet column, e.g. {{raw.Industry}}
  {{template}}        the channel template (stage 3)
  {{constraints}}     the channel's hard limits (stage 3)
"""
import logging

from app.db import mongo
from app.models.common import Channel
from app.models.prompt import Prompt, Stage
from app.models.template import CHANNEL_DEFAULTS, Template

logger = logging.getLogger(__name__)


STAGE_1_DOSSIER = """\
You are a research analyst preparing a one-page dossier on a sales prospect.

Below is everything our scrapers collected about this prospect. It is raw and
uneven: some sources will be empty, some will be mostly navigation text, some
will be about a different company with a similar name.

Your job is to extract only what is specific and verifiable, and to tag each
item with the source it came from.

Rules:
- Every fact must be traceable to the supplied sources. Do not add industry
  knowledge, do not infer, do not fill gaps from what you know about the
  company. If the sources are thin, return few facts.
- Prefer the specific over the general. "Launched a Databricks cost-monitoring
  product in March" is useful. "Is a technology company" is not.
- Discard boilerplate: cookie notices, nav menus, careers pages, legal footers.
- If a source clearly describes a different organisation, ignore it.
- Recent events matter most. Anything dated in the last 12 months belongs in
  recent_events.
- linkedin_posts holds what the prospect posted recently. Record each of their
  own posts in recent_events with its date and the specific thing they said or
  did. An entry marked "reposted this" is someone else's post: say so, and
  never record it as their own words.
- podcasts holds search results. Use one only if it names this person together
  with this company or role; a namesake is discarded.
- If a source shows this person should not be contacted as addressed (they
  have died, have left the company, or the company has closed), say so in
  contact_issue in one sentence. Do not guess; otherwise leave it empty.
- Return at most 12 items in total, the ones most likely to matter to what we
  sell or that the prospect said themselves. Do not pad.
- Set has_signal to false only when nothing you extracted relates to what we
  sell and nothing was said by the prospect themselves about their work. When
  unsure, true: a false ends the work on this prospect. Give the reason in
  signal_note.

The prospect's details and the raw research follow in the next message.
"""


STAGE_2_ANGLE = """\
You are an outbound strategist choosing how to open a conversation with a
prospect.

WHAT WE SELL
{{offer_context}}

The prospect's dossier follows in the next message. Pick at most two angles for
reaching out. An angle is a specific reason this
particular person, at this particular company, might care right now.

Rules:
- Every angle must cite one concrete fact from the dossier as its evidence.
  Quote the fact. If you cannot quote one, the angle does not exist.
- The angle must connect the fact to what we sell. A true but irrelevant fact
  is not an angle.
- Reject the generic. If your angle would read identically for any company in
  the sector, it is not personalization, it is filler.
- Flattery is not an angle. "I loved your recent post" is not an angle unless
  it says something specific about what the post argued.
- Prefer sources in this order: the prospect's own LinkedIn post from the last
  10 days, a podcast or interview they appeared on, their LinkedIn profile,
  the company's LinkedIn page, news about the company, the company website.
- A post the prospect wrote themselves in the last 10 days, about their work,
  is a valid opener even when it does not connect to what we sell. Say that it
  is an opener and not evidence of need. Never use a post about their personal
  life, and never treat a repost as their own words.
- If the dossier does not support a real angle, set sufficient to false and say
  what was missing. This is a good outcome, not a failure. A flagged row costs
  us nothing; a fabricated compliment costs us the prospect.
- Being on our list is not evidence. Decide separately whether the dossier
  shows this company actually has the problem we solve, for example that it
  runs the platform our offer targets. Set fit_established to true only when
  you can quote the dossier item that shows it in fit_evidence. Their role,
  their industry and the fact that we chose to contact them do not count.
"""


STAGE_3_DRAFT = """\
You are writing an outbound message. Follow the template's structure and voice.

WHAT WE SELL
{{offer_context}}

TEMPLATE
{{template}}

HARD CONSTRAINTS
{{constraints}}

The prospect's details, the chosen angle and the supporting dossier follow in
the next message.

Rules:
- Use the template's structure, tone and calls to action. The template still
  contains {{placeholder}} markers; resolve every one of them from the prospect
  details. Never emit a literal {{...}} marker in your output.
- Lead with the angle. The personalized line goes first, before anything about
  us, and it must be specific enough that it could not be sent to anyone else.
- State only what the dossier supports. No invented numbers, no assumed pain
  points, no "I saw you're scaling" unless a source says so.
- The next message says whether evidence of fit is established. When it is not,
  never state or imply that the prospect uses the technology or has the problem
  we solve. Ask whether they do, and do not press the call to action as if they
  had already said yes.
- When the angle is the prospect's own recent post, refer to it directly and
  specifically, as someone who read it would. Do not praise it, and do not
  bend it into a claim about a problem it does not mention.
- Write like a person: plain sentences, no marketing register, no "I hope this
  finds you well", no em-dashes, no exclamation marks.
- Respect the character limits exactly. They are hard limits, not targets.
- Return the body ready to send. Include a subject only for email.
"""


LINKEDIN_TEMPLATE = """\
Hi {{identity.first_name}},

[One specific line about {{identity.company}} drawn from the angle.]

[One line on why that made me reach out, referencing what we do.]

Worth a quick chat?
"""


EMAIL_TEMPLATE = """\
Subject: [4-7 words, specific to them, no clickbait]

Hi {{identity.first_name}},

[Opening line: the angle, stated concretely. Name the thing you saw.]

[Second line: the bridge from that to what we do, in one sentence. Concrete
outcome, not a capability list.]

[Third line: one sentence of proof or relevance.]

Open to a 15-minute call next week?

Best,
[Sender]
"""


WHATSAPP_TEMPLATE = """\
Hi {{identity.first_name}} - [one specific line about {{identity.company}}
from the angle].

[One line on why I'm reaching out.]

Would a quick call be useful?
"""


async def ensure_defaults() -> None:
    """Idempotent: only seeds when a stage or channel has nothing at all."""
    for stage, name, body in (
        (Stage.dossier, "Default dossier prompt", STAGE_1_DOSSIER),
        (Stage.angle, "Default angle prompt", STAGE_2_ANGLE),
        (Stage.draft, "Default draft prompt", STAGE_3_DRAFT),
    ):
        if await mongo.prompts().count_documents({"stage": int(stage)}, limit=1):
            continue
        await mongo.prompts().insert_one(
            Prompt(stage=stage, name=name, body=body, version=1, is_active=True).to_mongo()
        )
        logger.info("Seeded default prompt for stage %s", int(stage))

    for channel, name, body in (
        (Channel.linkedin, "Default LinkedIn connection note", LINKEDIN_TEMPLATE),
        (Channel.email, "Default cold email", EMAIL_TEMPLATE),
        (Channel.whatsapp, "Default WhatsApp opener", WHATSAPP_TEMPLATE),
    ):
        if await mongo.templates().count_documents({"channel": channel.value}, limit=1):
            continue
        await mongo.templates().insert_one(
            Template(
                channel=channel,
                name=name,
                body=body,
                constraints=CHANNEL_DEFAULTS[channel],
                version=1,
                is_active=True,
            ).to_mongo()
        )
        logger.info("Seeded default template for %s", channel.value)
