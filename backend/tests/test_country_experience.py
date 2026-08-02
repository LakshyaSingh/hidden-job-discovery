"""Tests for US-location detection and title-based experience inference."""
from app.scrapers.extract import infer_experience_from_title, is_us_location


def test_is_us_true_cases():
    assert is_us_location("US, CA, Santa Clara") is True
    assert is_us_location("New York, NY") is True
    assert is_us_location("Austin, TX (Hybrid)") is True
    assert is_us_location("Remote - US") is True
    assert is_us_location("United States") is True
    assert is_us_location("Indianapolis, Indiana") is True  # not confused with India
    assert is_us_location("New Mexico") is True  # not confused with Mexico


def test_is_us_false_cases():
    assert is_us_location("Bengaluru, India") is False
    assert is_us_location("Stockholm") is False
    assert is_us_location("London, United Kingdom") is False
    assert is_us_location("Toronto, Canada") is False
    assert is_us_location("Taipei, Taiwan") is False
    assert is_us_location("Mexico City") is False


def test_is_us_unknown():
    assert is_us_location(None) is None
    assert is_us_location("Remote") is None  # no country signal


def test_title_experience_seniority():
    assert infer_experience_from_title("Senior Product Manager") == (5, None)
    assert infer_experience_from_title("Principal Product Manager") == (8, None)
    assert infer_experience_from_title("Staff Software Engineer") == (6, None)
    assert infer_experience_from_title("Director of Product") == (10, None)
    assert infer_experience_from_title("VP, Product") == (12, None)


def test_title_experience_junior():
    assert infer_experience_from_title("Product Manager Intern") == (0, 1)
    assert infer_experience_from_title("Associate Product Manager") == (0, 2)
    assert infer_experience_from_title("New Grad Software Engineer") == (0, 1)


def test_title_experience_none_when_no_signal():
    assert infer_experience_from_title("Product Manager") == (None, None)
    assert infer_experience_from_title("Product Manager, Growth") == (None, None)


def test_senior_excluded_from_entry_filter():
    # The "0 to 2 years" filter uses min<=fmax; a senior floor of 5 fails it.
    lo, _ = infer_experience_from_title("Senior Product Manager")
    assert lo is not None and lo > 2


def test_title_experience_new_seniority_signals():
    assert infer_experience_from_title("Executive Vice President, Sales") == (14, None)
    assert infer_experience_from_title("President, North America") == (14, None)
    assert infer_experience_from_title("Founding Engineer") == (7, None)
    assert infer_experience_from_title("Software Engineer III") == (4, None)
    assert infer_experience_from_title("Data Analyst II") == (2, None)


def test_title_experience_new_entry_signals():
    assert infer_experience_from_title("Engineering Trainee") == (0, 1)
    assert infer_experience_from_title("Campus Hire, Analytics") == (0, 1)
    assert infer_experience_from_title("Early Career Software Engineer") == (0, 2)


def test_vice_president_is_not_read_as_president():
    """Ordering matters: the president rule sits below the vp rules."""
    assert infer_experience_from_title("Vice President, Marketing") == (12, None)


def test_ambiguous_titles_stay_uninferred():
    """A wrong guess hides a job; no guess only leaves it unfiltered.

    'Manager' spans an IC product manager and a director-equivalent, and
    'Architect' spans a first solutions-architect hire and a distinguished
    one, so neither earns a rule.
    """
    assert infer_experience_from_title("Product Manager") == (None, None)
    assert infer_experience_from_title("Solutions Architect") == (None, None)
    assert infer_experience_from_title("Software Engineer") == (None, None)
