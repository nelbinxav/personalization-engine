from app.ai import grounding
from app.models.prospect import Fact

SOURCE = (
    "Priya Shah leads the Data Platform team at Acme. Acme raised $45M in March "
    "and runs its pipelines on Databricks and Delta Lake."
)


def fact(text, key="website", kind="other"):
    return Fact(text=text, source_key=key, kind=kind)


def test_a_fact_is_grounded_when_its_numbers_and_names_are_in_the_source():
    assert grounding.fact_problem(fact("Acme raised $45M in March"), SOURCE) is None
    assert grounding.fact_problem(fact("Priya Shah leads the Data Platform team"), SOURCE) is None


def test_an_invented_number_or_name_is_caught():
    assert grounding.fact_problem(fact("Acme raised $4M in March"), SOURCE)
    assert grounding.fact_problem(fact("Acme raised $450M in March"), SOURCE)
    assert grounding.fact_problem(fact("Acme migrated to Snowflake"), SOURCE)


def test_a_fact_naming_a_source_with_no_text_is_caught():
    assert "held no research" in grounding.fact_problem(fact("Anything", "news"), None)


def test_dates_worked_out_from_linkedin_age_stamps_are_not_held_against_a_post():
    posts = "Priya Shah 2w\nTalked about Delta Lake migration at the summit."
    f = fact("Priya Shah posted around 29 September 2026 about a Delta Lake migration", "linkedin_posts")
    assert grounding.fact_problem(f, posts) is None


def test_evidence_must_be_one_dossier_item():
    facts = [fact("Acme runs its pipelines on Databricks", kind="tech_uses"), fact("Acme raised $45M")]
    assert grounding.match_fact("Acme runs its pipelines on Databricks", facts) is facts[0]
    assert grounding.match_fact("acme runs pipelines on databricks and delta", facts) is facts[0]
    assert grounding.match_fact("Acme opened an office in Lisbon", facts) is None
    assert grounding.match_fact("", facts) is None


def test_copy_may_use_only_numbers_the_evidence_has():
    assert grounding.copy_problems("A $45M round and Databricks.", ["Acme raised $45M"]) == []
    assert grounding.copy_problems("Over 300 engineers.", ["Acme raised $45M"])
    assert grounding.copy_problems("Fine \u2014 but not this!", [])


def test_a_line_may_not_name_its_source_or_use_banned_wording():
    assert grounding.copy_problems("Both sit in your LinkedIn headline.", [])
    assert grounding.copy_problems("I noticed the Databricks hiring.", [])
    assert grounding.copy_problems("Your post on the summit talks about Delta.", [], own_post=True) == []
    assert grounding.copy_problems("Hiring Databricks engineers usually means more compute.", []) == []


def test_words_that_only_describe_where_a_fact_was_found_are_not_evidence():
    f = fact("Joe Gangaram's LinkedIn About section says he has over 15 years of experience", "linkedin_profile")
    assert grounding.fact_problem(f, "Joe Gangaram. Over 15 years of experience in data.") is None
