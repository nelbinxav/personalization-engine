"""Map arbitrary sheet headers onto the canonical Identity fields.

Outbound sheets in the wild use wildly inconsistent headers ("Company Name",
"company", "Organisation", "Account"). The operator always confirms the mapping
in the UI; this module just makes the first guess a good one.
"""
import re

from app.models.common import Identity

IDENTITY_FIELDS: list[str] = list(Identity.model_fields.keys())

# Ordered: the first pattern that matches a header wins that field, and each
# field is claimed at most once.
_PATTERNS: dict[str, list[str]] = {
    "linkedin_company_url": [
        r"linkedin.*(company|org|firm)",
        r"(company|org).*linkedin",
        r"^company_?li$",
    ],
    "linkedin_url": [r"linkedin", r"^li_?(url|profile)$", r"profile.*url"],
    # Anchored deliberately. A loose `^web` matched "Webinar id" in a real
    # BigHammer sheet and would have pointed the scraper at a numeric id; a bare
    # `site` does the same to "Registration source".
    "website": [
        r"web_?site",
        r"^web$",
        r"(^|_)urls?($|_)",
        r"domain",
        r"homepage",
        r"company_?site",
    ],
    "email": [r"e-?mail", r"^mail$"],
    "phone": [r"phone", r"mobile", r"whatsapp", r"telephone", r"^tel$", r"contact.*number"],
    "first_name": [r"^first", r"first.?name", r"^fname$", r"given.?name"],
    "last_name": [r"^last", r"last.?name", r"^lname$", r"surname", r"family.?name"],
    "full_name": [r"full.?name", r"^name$", r"contact.?name", r"person", r"prospect"],
    "title": [r"title", r"position", r"^role$", r"designation", r"job.?title", r"seniority"],
    "company": [r"company", r"organisation", r"organization", r"^org$", r"account", r"employer"],
    "location": [r"location", r"city", r"country", r"region", r"geo", r"^based"],
}


def _normalize(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """Best-effort {identity_field: header}. Unmatched fields are simply absent."""
    mapping: dict[str, str] = {}
    taken: set[str] = set()

    for field, patterns in _PATTERNS.items():
        for pattern in patterns:
            match = next(
                (h for h in headers if h not in taken and re.search(pattern, _normalize(h))),
                None,
            )
            if match:
                mapping[field] = match
                taken.add(match)
                break

    return mapping


def validate_mapping(mapping: dict[str, str], headers: list[str]) -> list[str]:
    """Return human-readable problems with a proposed mapping (empty == valid)."""
    problems: list[str] = []
    header_set = set(headers)

    for field, column in mapping.items():
        if field not in IDENTITY_FIELDS:
            problems.append(f"Unknown field '{field}'")
        if column and column not in header_set:
            problems.append(f"Column '{column}' is not in the sheet")

    # A row with no name and no company can't be researched or addressed.
    if not any(mapping.get(f) for f in ("full_name", "first_name", "company")):
        problems.append(
            "Map at least one of 'full_name', 'first_name' or 'company' - "
            "rows need something to identify the prospect by."
        )

    # Nothing to point a scraper at.
    if not any(mapping.get(f) for f in ("website", "linkedin_url", "linkedin_company_url")):
        problems.append(
            "Map at least one of 'website', 'linkedin_url' or 'linkedin_company_url' - "
            "otherwise there is nothing for the scraping engine to fetch."
        )

    return problems
