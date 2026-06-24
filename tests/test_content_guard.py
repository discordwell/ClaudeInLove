"""
Tests for the hard-safety ContentGuard.

Two things matter equally here:

* **Recall** — an outgoing reply that actually commits to sending money or
  leaks a personal/financial identifier must be blocked, even when it is
  perfectly human-sounding (so the suspicion checker would wave it through).
* **Precision** — the persona is *designed* to talk about money in order to
  stall ("my account's frozen", "I can't send anything till payday"). Those
  deflections are the tool working, and must NOT be blocked, or the bot can no
  longer do its core job autonomously.
"""

import pytest

from src.safety.content_guard import ContentGuard, GuardResult


@pytest.fixture
def guard():
    return ContentGuard()


# --- Safe replies: ordinary baiting chatter ---------------------------------

SAFE_REPLIES = [
    "haha yeah maybe... we'll see",
    "aww you're so sweet, i've been thinking about you all day",
    "i'm right here babe lol",
    "hey you! how's your day going?",
    "sure, sounds good to me",
    "tell me more about your work on the oil rig, it sounds exciting",
    # Replies that *mention* money but only to deflect — the desired behaviour.
    "ugh my bank account is frozen right now so i can't send anything",
    "i'm waiting on my paycheck, money's been really tight lately",
    "i wish i could send you the money but i'm completely broke this month",
    "i would never wire money to someone i haven't even met in person",
    "i can't do western union, i've heard too many scary stories",
    "i don't have any gift cards and i'm not going to buy any sorry",
    "is western union even safe? a friend got scammed that way",
    "my paycheck comes friday, then we can talk about it",
    "i'll think about the western union thing, no promises though",
    # Clause-splitting must not turn romantic hyperbole into a money commitment.
    "i'll send you the 100 reasons i love you, but not a dime",
    "i would, but i can't send anything right now",
    "money is tight, but i'll talk to you later ok?",
    "i can't send money, gift cards, or anything else sorry",
    # "not <verb>" must read as a refusal, not a commitment.
    "i'm not sending any gift cards, my sister said that's a scam",
    # Verb and an unrelated money word co-occurring in one sentence: the verb
    # has a non-money object ("a hug"), so proximity keeps this safe.
    "let me send you a hug instead, money's too tight lol",
    "i sent you a photo of my garden earlier, did you see it?",
    # A phone number must not look like a card/account number.
    "call me anytime at +1 555 123 4567 ok?",
    "you can reach me on 5551234567 babe",
    "you want my number? it's 555-0142, call me tonight",
]


@pytest.mark.parametrize("reply", SAFE_REPLIES)
def test_safe_replies_pass(guard, reply):
    result = guard.check(reply)
    assert result.is_safe, f"false positive on: {reply!r} -> {result.violations}"
    assert result.violations == []


def test_empty_or_blank_reply_is_safe(guard):
    assert guard.check("").is_safe
    assert guard.check("   \n  ").is_safe


# --- Money commitments: must be blocked -------------------------------------

MONEY_COMMITMENTS = [
    "ok babe i'll send you the $500 tomorrow",
    "sure, i'll wire the money through western union in the morning",
    "i'll transfer the funds to you tonight",
    "let me venmo you right now",
    "i'll just paypal it over to you",
    "i'll zelle you the 500 bucks",
    "okay i'll buy you those steam cards after work",
    "i'll go load a gift card for you today",
    "i'll pay the customs fee, just tell me how much",
    "i'll deposit the cash into your account this afternoon",
    # Past-tense claim of having already sent funds.
    "okay i transferred the funds to your account",
    "the money is on its way to you sweetheart",
    # Rail named as the destination of a sending verb.
    "i'll send it via western union first thing tomorrow",
    # "Warm capitulation": a hedge and a commitment in one breath. A negation in
    # the hedge clause must NOT cover the committing clause (clause-splitting).
    "i dont usually do this but ill send you the money tonight",
    "i cant believe im doing this but ill buy you the steam cards after work",
    "i never thought id say this but ill pay the fee for you",
    "i'm not going to lie, i'll send the money",
    "i shouldn't, but i'll venmo you the 200",
    # Bare amount after an unambiguous money verb.
    "i know i said i couldnt but for you ill wire the 500 today",
]


@pytest.mark.parametrize("reply", MONEY_COMMITMENTS)
def test_money_commitments_are_blocked(guard, reply):
    result = guard.check(reply)
    assert not result.is_safe, f"missed commitment: {reply!r}"
    assert any("money" in v or "payment" in v for v in result.violations)


# --- PII / identifiers: must be blocked -------------------------------------

def test_ssn_is_blocked(guard):
    result = guard.check("if you need it my ssn is 123-45-6789")
    assert not result.is_safe
    assert any("SSN" in v for v in result.violations)


def test_credit_card_number_is_blocked(guard):
    result = guard.check("here's my card, 4111 1111 1111 1111, use it")
    assert not result.is_safe
    assert any("card/account-length" in v for v in result.violations)


def test_bare_long_number_is_blocked(guard):
    result = guard.check("the account is 4000123412341234 ok")
    assert not result.is_safe


def test_eth_wallet_is_blocked(guard):
    result = guard.check(
        "send it to my wallet 0x52908400098527886E0F7030069857D2E4169EE7"
    )
    assert not result.is_safe
    assert any("crypto wallet" in v for v in result.violations)


def test_btc_wallet_is_blocked(guard):
    result = guard.check("my btc address is bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")
    assert not result.is_safe
    assert any("crypto wallet" in v for v in result.violations)


def test_labelled_short_account_number_is_blocked(guard):
    # 8 digits — below the 13-digit length floor, but explicitly labelled, so
    # the labelled-identifier rule still catches it.
    result = guard.check("my account number is 12345678, routing 021000021")
    assert not result.is_safe
    assert any("bank account" in v for v in result.violations)


# --- Combined / structural ---------------------------------------------------

def test_money_and_pii_combine_into_multiple_violations(guard):
    result = guard.check(
        "ok i'll wire you the $500 on western union, my ssn is 123-45-6789"
    )
    assert not result.is_safe
    assert len(result.violations) >= 2


def test_negated_clause_does_not_mask_a_separate_committing_sentence(guard):
    # First sentence deflects; second commits. Sentence-level scanning must
    # still catch the second.
    result = guard.check(
        "i can't do it through the bank. but i'll send you the cash instead."
    )
    assert not result.is_safe


def test_guard_result_reason_joins_violations(guard):
    result = guard.check("my ssn is 123-45-6789 and my btc is bc1qarxx000111222333444")
    assert "; " in result.reason or len(result.violations) == 1
    assert not result.is_safe


def test_result_reason_is_empty_when_safe(guard):
    assert GuardResult(is_safe=True).reason == ""
