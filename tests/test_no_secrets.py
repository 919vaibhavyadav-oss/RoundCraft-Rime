"""The secret scanner has to catch a real key and ignore ordinary code.

A scanner that cries wolf gets disabled, and a disabled scanner is how a live
credential reaches a submission.
"""

from scripts.check_no_secrets import looks_like_a_key


def test_it_catches_a_key_shaped_string() -> None:
    """A synthetic string with a credential's shape: mixed case, digits, long."""
    assert looks_like_a_key("Qv7mKp2xTz9bNw4hLr6sJd1fGy8cVa3e") is True


def test_it_ignores_a_rule_of_dashes() -> None:
    assert looks_like_a_key("-" * 40) is False


def test_it_ignores_long_identifiers() -> None:
    assert looks_like_a_key("interview_configs_profession_check") is False
    assert looks_like_a_key("RIME_API_KEY_PLACEHOLDER") is False


def test_it_ignores_documented_placeholders() -> None:
    assert looks_like_a_key("your_rime_api_key_goes_here_1234") is False


def test_it_needs_both_letters_and_digits() -> None:
    assert looks_like_a_key("abcdefghijklmnopqrstuvwxyzabcdef") is False
    assert looks_like_a_key("12345678901234567890123456789012") is False
