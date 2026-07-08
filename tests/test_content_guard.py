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
    # A negation that directly governs the sending verb is a deflection and must
    # stay safe, even with fillers between the negation and the verb, and even
    # when there is no comma to split it off. These pin the *scoped* negation
    # behaviour (the negation only neutralises the verb it governs).
    "no way im sending you cash babe",
    "i can't possibly send you any money right now",
    "i won't be sending anything until we meet in person",
    "i'm not able to wire money this week, everything's frozen",
    "i don't think i should send money to be honest",
    "i never agreed to send you a single dime",
    "honestly i can't afford to send the money right now",
    # A far-scoping "let alone" refusal must not be read as a commitment.
    "i can't even afford my rent let alone send you money",
    # Verb and an unrelated money word co-occurring in one sentence: the verb
    # has a non-money object ("a hug"), so proximity keeps this safe.
    "let me send you a hug instead, money's too tight lol",
    "i sent you a photo of my garden earlier, did you see it?",
    # Broadening the commitment patterns (below) must not cost precision: each of
    # these mentions money, a rail, or a generic hand-over verb yet commits to
    # nothing, so it must stay safe.
    #   - a *reported* request (narrating / rebuffing the scammer's ask), which
    #     carries a sending verb but is not the persona agreeing to anything:
    "you keep asking me to send money and it's honestly upsetting",
    "he wanted me to wire money for a flight but i said no",
    "please stop asking me to send money, it's making me sad",
    #   - a refusal framed as the *rejected* side of a "rather ... than":
    "i'd rather buy a plane ticket than send money to some stranger's account",
    #   - stating income, not offering to *make a payment* ("make 40k a year"):
    "i make about 40k a year, comfortable but not rich",
    #   - generic verbs (make/cover/do) under a negation are still a decline:
    "i can't make the payment, my account is frozen",
    "i can't cover that fee right now, i'm so sorry",
    #   - checking one's *own* payment app is not a send:
    "let me check my paypal, i think your message ended up there",
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
    # Warm capitulation with NO delimiter between the hedge and the commitment:
    # the negation governs a *different* verb ("don't worry", "can't wait", "never
    # been more sure"), so it must not cancel the real send riding alongside it.
    # Previously a clause-level negation skip swallowed the whole sentence and let
    # these through scoring ~0 on the suspicion checker — the worst-case miss.
    "dont worry babe ill wire the 500 today",
    "dont worry ill send the cash tomorrow",
    "i cannot wait to send you the money baby",
    "ive never been more sure ill wire you 500 dollars",
    "no worries ill just venmo you the 200 now",
    "i wont hesitate to send you the money love",
]


@pytest.mark.parametrize("reply", MONEY_COMMITMENTS)
def test_money_commitments_are_blocked(guard, reply):
    result = guard.check(reply)
    assert not result.is_safe, f"missed commitment: {reply!r}"
    assert any("money" in v or "payment" in v for v in result.violations)


# --- Broadened commitment recall --------------------------------------------
# The earlier matcher only fired on a transfer verb *immediately* followed by a
# money object, so a large family of realistic capitulations sailed straight
# through — and because they read as perfectly casual, the suspicion checker
# scored them ~0 too, so *nothing* caught them. Each entry below is one such
# miss, grouped by the structure that used to defeat the guard. These are the
# worst-case failure mode (an autonomous reply that agrees to send), so recall
# here matters as much as the precision corpus above.
BROADENED_COMMITMENTS = [
    # generic hand-over verbs (make / put / drop / cover) beside a money object
    "alright ill go ahead and make the payment tonight",
    "ok baby i already put the money in your account",
    "ill drop the cash in your account tonight",
    "i can cover the 500 fee for you",
    # a payment rail used as a verb, or reached by a sending verb
    "okay ill western union it to you",
    "okay fine, i will do the western union transfer tomorrow",
    "just sent you the 200 on zelle",
    # buying / *getting* the classic scam payout instruments
    "fine ill get you the gift cards after work",
    "ill go to walmart and get the steam cards for you",
    # a bare amount after a money verb — unambiguous (spot/lend) or money-terminal
    "sending you 500 now love",
    "yes ok i can do 500 today",
    "alright i can spot you 400 til payday",
    "ill lend you the 500 just this once",
    # a claim the transfer is already done / on its way / theirs
    "consider the money sent babe",
    "sure, consider it done, the 500 is yours",
    "money's on its way babe dont worry",
    # a directional delivery or a delivery promise aimed at the recipient
    "ill have the funds to you by friday i promise",
    "ok i put 300 into your account this morning",
    "you'll have the cash by tonight i promise",
    # a funds-only verb with a pronoun / "everything" object
    "i went ahead and wired it this morning",
    "ill transfer everything i have to you",
    # telling them to check the rail the money supposedly landed in
    "okay i sent it already, check your paypal",
]


@pytest.mark.parametrize("reply", BROADENED_COMMITMENTS)
def test_broadened_commitments_are_blocked(guard, reply):
    result = guard.check(reply)
    assert not result.is_safe, f"missed commitment: {reply!r}"
    assert any("money" in v or "payment" in v for v in result.violations)


# --- Discriminators: the same verb, safe or unsafe by *context* -------------
# These pin the precision/recall boundary on cases where the naive signal (a
# money word, a rail, a sending verb) is present on both sides, so only the
# surrounding structure separates a decline from a commitment.

def test_income_statement_is_not_a_payment(guard):
    # "make 40k a year" is income; "make the payment" is a commitment. The verb
    # is identical — only the object tells them apart.
    assert guard.check("i make about 40k a year, comfortable but not rich").is_safe
    assert not guard.check("i'll make the payment first thing tomorrow").is_safe


def test_reported_request_is_not_a_commitment(guard):
    # Narrating or rebuffing the scammer's ask ("you keep asking me to send",
    # "he wanted me to wire") carries a sending verb but is not the persona
    # agreeing to send. A first-person promise still trips.
    assert guard.check("you keep asking me to send money and it's upsetting").is_safe
    assert guard.check("he wanted me to wire money but i refused").is_safe
    assert not guard.check("okay i'll send you the money you keep asking for").is_safe


def test_rather_than_send_is_a_refusal(guard):
    # In "rather X than send money" the send is the *rejected* alternative; in
    # "rather send money than X" it is the chosen one.
    assert guard.check("i'd rather fly out to see you than send any money").is_safe
    assert not guard.check(
        "i'd rather send you the money than watch you struggle"
    ).is_safe


def test_bare_amount_needs_a_money_context(guard):
    # A bare number reads as cash only next to a money verb and a money-terminal
    # cue; romantic hyperbole trailing a content noun ("100 reasons") stays safe.
    assert guard.check("i'll send you the 100 reasons i love you").is_safe
    assert not guard.check("i'll send you 500 tonight babe").is_safe


def test_checking_own_app_is_safe_but_directing_them_is_not(guard):
    # Checking *my own* payment app is benign; telling *them* the money is in
    # *their* app is a completion claim.
    assert guard.check("let me check my paypal for your message").is_safe
    assert not guard.check("check your paypal babe, it's there").is_safe


# --- PII / identifiers: must be blocked -------------------------------------

def test_ssn_is_blocked(guard):
    result = guard.check("if you need it my ssn is 123-45-6789")
    assert not result.is_safe
    assert any("SSN" in v for v in result.violations)


@pytest.mark.parametrize(
    "reply",
    [
        "my ssn is 123-45-6789",       # dashed
        "my ssn is 123 45 6789",       # space-grouped
        "my ssn is 123.45.6789",       # dot-grouped
        "my ssn is 123456789",         # bare 9 digits, but labelled
        "social security number 123456789 if you really need it",
        "here's my social 123-45-6789",
    ],
)
def test_ssn_in_any_common_format_is_blocked(guard, reply):
    # A coerced victim typing their SSN without dashes (or with spaces/dots) is
    # just as much a leak as the canonical 123-45-6789 form. The bare 9-digit
    # run slips past both the separator pattern and the 13-digit length floor,
    # so it is caught only when explicitly labelled "ssn"/"social".
    result = guard.check(reply)
    assert not result.is_safe, f"missed SSN: {reply!r}"
    assert any("SSN" in v for v in result.violations)


@pytest.mark.parametrize(
    "reply",
    [
        "you can reach me on 5551234567 babe",        # 10-digit phone, no label
        "my order number was 100200300 from amazon",  # 9 digits, no SSN label
        "call me anytime at +1 555 123 4567 ok?",     # phone groups 3-3-4, not 3-2-4
    ],
)
def test_unlabelled_numbers_are_not_mistaken_for_ssn(guard, reply):
    # Precision: an unlabelled 9/10-digit run (a phone or an order number) must
    # not be blocked as an SSN — only the distinctive 3-2-4 grouping or an
    # explicit "ssn"/"social" label counts.
    result = guard.check(reply)
    assert result.is_safe, f"false SSN positive on: {reply!r} -> {result.violations}"


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


def test_negation_scope_is_the_discriminator(guard):
    # The crux of the guard's negation handling: the *same* sending verb is safe
    # or unsafe depending on whether the negation actually governs it. When the
    # negation binds "send" itself, it's a refusal (safe); when it binds some
    # other verb in the same breath ("worry"), the send is a real commitment
    # (unsafe) — even with no comma to split the two apart.
    assert guard.check("i can't send you the money babe").is_safe
    assert not guard.check("dont worry babe i'll send you the money").is_safe


def test_guard_result_reason_joins_violations(guard):
    result = guard.check("my ssn is 123-45-6789 and my btc is bc1qarxx000111222333444")
    assert "; " in result.reason or len(result.violations) == 1
    assert not result.is_safe


def test_result_reason_is_empty_when_safe(guard):
    assert GuardResult(is_safe=True).reason == ""
