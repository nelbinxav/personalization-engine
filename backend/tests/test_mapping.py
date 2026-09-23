from app.ingest.mapping import suggest_mapping, validate_mapping
from app.models.upload import identity_from_row


def test_suggests_real_outreach_headers():
    headers = [
        "First Name",
        "Last Name",
        "Job Title",
        "Company Name",
        "Website",
        "LinkedIn Profile",
        "Company LinkedIn",
        "Email",
        "City",
    ]
    mapping = suggest_mapping(headers)

    assert mapping["first_name"] == "First Name"
    assert mapping["last_name"] == "Last Name"
    assert mapping["title"] == "Job Title"
    assert mapping["company"] == "Company Name"
    assert mapping["website"] == "Website"
    assert mapping["email"] == "Email"
    assert mapping["location"] == "City"


def test_company_linkedin_does_not_steal_the_personal_profile_column():
    # The ordering in _PATTERNS exists for this: "Company LinkedIn" must not be
    # claimed by linkedin_url, or every row researches the wrong page.
    headers = ["LinkedIn Profile", "Company LinkedIn"]
    mapping = suggest_mapping(headers)

    assert mapping["linkedin_company_url"] == "Company LinkedIn"
    assert mapping["linkedin_url"] == "LinkedIn Profile"


def test_webinar_id_is_not_mistaken_for_a_website():
    # Regression: the real "Dummy Data - Verified emails" sheet has a
    # "Webinar id" column that a loose ^web pattern claimed as the website,
    # pointing the scraper at a numeric id.
    headers = [
        "email",
        "Webinar id",
        "Webinar name",
        "First name",
        "Surname",
        "Company",
        "Job title",
        "City",
        "Registration source",
    ]
    mapping = suggest_mapping(headers)

    assert "website" not in mapping
    assert mapping["company"] == "Company"
    assert mapping["title"] == "Job title"
    assert mapping["location"] == "City"


def test_real_website_headers_still_map():
    for header in ["Website", "website", "Company Website", "Domain", "URL", "Homepage"]:
        assert suggest_mapping([header, "Company"]).get("website") == header, header


def test_each_column_is_claimed_once():
    headers = ["Name", "Company", "URL"]
    mapping = suggest_mapping(headers)
    assert len(set(mapping.values())) == len(mapping.values())


def test_validate_rejects_a_mapping_with_nothing_to_scrape():
    headers = ["Full Name", "Company"]
    problems = validate_mapping({"full_name": "Full Name", "company": "Company"}, headers)
    assert any("website" in problem for problem in problems)


def test_validate_rejects_a_mapping_with_no_identifier():
    headers = ["Website"]
    problems = validate_mapping({"website": "Website"}, headers)
    assert any("full_name" in problem for problem in problems)


def test_validate_rejects_a_column_that_is_not_in_the_sheet():
    problems = validate_mapping({"company": "Nope", "website": "Website"}, ["Website"])
    assert any("not in the sheet" in problem for problem in problems)


def test_validate_accepts_a_workable_mapping():
    headers = ["Full Name", "Company", "Website"]
    mapping = {"full_name": "Full Name", "company": "Company", "website": "Website"}
    assert validate_mapping(mapping, headers) == []


def test_identity_projection_trims_and_skips_blanks():
    row = {"Full Name": "  Ada Lovelace  ", "Company": "", "Website": "example.com"}
    mapping = {"full_name": "Full Name", "company": "Company", "website": "Website"}

    identity = identity_from_row(row, mapping)

    assert identity.full_name == "Ada Lovelace"
    assert identity.company is None
    assert identity.website == "example.com"
    assert identity.display_name == "Ada Lovelace"
