"""What the panel is told about the candidate, and what it is never told.

A CV is personal data. The rules single that out, and the honest way to show
how it is handled is to assert it here rather than describe it in a README:
contact details are removed, the size is bounded, and a candidate who supplies
nothing changes nothing about the instructions the model receives.
"""

from app.agent import panel_instructions
from app.panel.background import MAX_CHARS, MAX_LINES, briefing, condense, redact


class TestRedaction:
    def test_an_email_address_is_removed(self) -> None:
        assert "vaibhav@example.com" not in redact("Reach me at vaibhav@example.com")
        assert "[email]" in redact("Reach me at vaibhav@example.com")

    def test_a_phone_number_is_removed(self) -> None:
        out = redact("Call +91 98765 43210 any time")
        assert "98765" not in out
        assert "[phone]" in out

    def test_a_link_is_removed(self) -> None:
        out = redact("Portfolio: https://example.com/vaibhav")
        assert "example.com" not in out
        assert "[link]" in out

    def test_the_work_itself_survives(self) -> None:
        """Redaction must not eat the thing the panel is meant to ask about."""
        cv = "Shipped a recommendation engine for 70,000 premium card members."
        assert redact(cv) == cv

    def test_a_year_range_is_not_mistaken_for_a_phone_number(self) -> None:
        assert redact("Product Manager 2021 - 2024") == "Product Manager 2021 - 2024"


class TestCondense:
    def test_nothing_in_nothing_out(self) -> None:
        assert condense("") == ""
        assert condense("   \n\n  ") == ""

    def test_runs_of_blank_lines_collapse(self) -> None:
        assert condense("Alpha\n\n\n\nBeta") == "Alpha\n\nBeta"

    def test_a_long_document_is_capped(self) -> None:
        assert len(condense("A line of a CV.\n" * 500)) <= MAX_CHARS

    def test_a_long_document_is_cut_at_a_line_not_mid_word(self) -> None:
        out = condense("Managed the onboarding rewrite.\n" * 400)
        assert not out.endswith("Manage")
        assert out.count("\n") <= MAX_LINES

    def test_it_redacts_as_well_as_trims(self) -> None:
        assert "me@example.com" not in condense("Vaibhav\nme@example.com\nPM at Acme")


class TestBriefing:
    def test_no_background_produces_no_briefing(self) -> None:
        assert briefing("") == ""

    def test_it_tells_the_panel_not_to_read_it_aloud(self) -> None:
        """A model handed a block of someone's CV will otherwise recite it."""
        text = briefing("PM at Acme, shipped onboarding.")
        assert "never read it back" in text.lower()
        assert "PM at Acme" in text

    def test_it_frames_the_text_as_a_direction_not_as_conversation(self) -> None:
        text = briefing("PM at Acme.")
        assert text.startswith("The candidate supplied this background.")


class TestPanelInstructions:
    def test_without_a_background_the_prompt_is_unchanged(self) -> None:
        """A candidate who skips the field gets the same interview."""
        assert panel_instructions() == panel_instructions("")
        assert "candidate background" not in panel_instructions()

    def test_a_background_is_included(self) -> None:
        text = panel_instructions("Shipped a recommendation engine.")
        assert "Shipped a recommendation engine." in text
        assert "candidate background" in text

    def test_the_turn_direction_comes_last(self) -> None:
        """Whoever is speaking now is the most recent thing the model reads."""
        text = panel_instructions("PM at Acme.", "Speak now as Maya Chen.")
        assert text.rstrip().endswith("Speak now as Maya Chen.")

    def test_empty_parts_leave_no_empty_headings(self) -> None:
        assert "\n\n\n" not in panel_instructions("", "Speak now as Maya Chen.")
