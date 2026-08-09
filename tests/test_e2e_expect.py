import pytest

from visus.web import expect


@pytest.fixture
def page(browser, base_url):
    p = browser.new_page()
    p.goto(f"{base_url}/expects.html")
    return p


@pytest.mark.browser
def test_to_have_text_retries_until_changed(page):
    expect(page.locator("#msg")).to_have_text("ready")  # text flips from 'loading' at 700ms


@pytest.mark.browser
def test_to_contain_text(page):
    expect(page.locator("#msg")).to_contain_text("read")


@pytest.mark.browser
def test_to_be_visible_retries_until_appears(page):
    expect(page.locator("#appear")).to_be_visible()


@pytest.mark.browser
def test_not_to_be_visible_retries_until_vanishes(page):
    expect(page.locator("#vanish")).not_.to_be_visible()


@pytest.mark.browser
def test_to_have_count_retries_until_list_grows(page):
    expect(page.locator("#list li")).to_have_count(3)


@pytest.mark.browser
def test_to_be_enabled_retries(page):
    expect(page.locator("#enableme")).to_be_enabled()


@pytest.mark.browser
def test_already_true_passes_fast(page):
    # one-shot path: msg is present immediately (text 'loading')
    expect(page.locator("#msg")).to_be_visible()


@pytest.mark.browser
def test_failing_assertion_raises_assertionerror(page):
    with pytest.raises(AssertionError):
        expect(page.locator("#appear")).to_have_text("never", timeout=800)


@pytest.mark.browser
def test_not_negation_failure_raises(page):
    # #msg IS visible, so not_.to_be_visible must fail within the timeout
    with pytest.raises(AssertionError):
        expect(page.locator("#msg")).not_.to_be_visible(timeout=800)


@pytest.mark.browser
def test_page_matches_a_partial_aria_snapshot(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    """Partial by design: assert the rows that matter, ignore the rest.

    Mirrors playwright-cli's rule that "snapshot to be matched does not have to
    contain all the information".
    """
    import re

    from visus.web import expect

    page = browser.new_page()
    page.goto(f"{base_url}/forms.html")

    expect(page).to_match_aria_snapshot([{"role": "textbox", "name": "Username"}])
    expect(page).to_match_aria_snapshot([{"role": "textbox", "name": re.compile(r"^User")}])


@pytest.mark.browser
def test_aria_snapshot_mismatch_reports_what_it_saw(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    from visus.web import expect

    page = browser.new_page()
    page.goto(f"{base_url}/forms.html")
    with pytest.raises(AssertionError) as excinfo:
        expect(page).to_match_aria_snapshot(
            [{"role": "button", "name": "Definitely Not Here"}], timeout=500
        )
    message = str(excinfo.value)
    assert "to_match_aria_snapshot" in message
    assert "Definitely Not Here" in message
    assert "last received" in message


@pytest.mark.browser
def test_aria_snapshot_respects_order(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    """Rows must appear as a SUBSEQUENCE, so a reordered page fails."""
    from visus.web import expect

    page = browser.new_page()
    page.goto(f"{base_url}/locators.html")
    rows = page.snapshot()
    assert len(rows) >= 2
    forwards = [{"role": r["role"], "name": r["name"]} for r in rows[:2]]
    expect(page).to_match_aria_snapshot(forwards)
    with pytest.raises(AssertionError):
        expect(page).to_match_aria_snapshot(list(reversed(forwards)), timeout=500)


@pytest.mark.browser
def test_aria_snapshot_can_be_scoped_to_a_region(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    """The scoped form: assert one region without the rest of the page."""
    from visus.web import expect

    page = browser.new_page()
    page.goto(f"{base_url}/snapshot_tree.html")
    expect(page).to_match_aria_snapshot(
        [{"role": "button", "name": "Deep button"}], selector="#main"
    )
    with pytest.raises(AssertionError):
        expect(page).to_match_aria_snapshot(
            [{"role": "link", "name": "Footer link"}], selector="#main", timeout=500
        )
