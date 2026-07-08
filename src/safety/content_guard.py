"""
Content guard — the deterministic backstop for the project's hard safety
invariants on every *outgoing* reply.

The suspicion checker answers "does this reply sound like an AI?". That is a
different — and weaker — question than "does this reply break the rules the
whole tool is built around?":

* never actually agree to **send money** (cash, wire, gift cards, crypto), and
* never emit a real **personal/financial identifier** (SSN, card/account/
  routing number, crypto wallet).

A reply can be perfectly human-sounding — "sure babe, I'll wire the $500 on
Western Union, my SSN is 123-45-6789" — and so sail past the suspicion checker
with a score of ``0.0``, yet be the single worst thing the bot could do. The
counterparty is *actively trying* to extract exactly these things, and until
now the only thing standing in the way was a line in the system prompt that the
model may ignore under pressure (or be steered past by an injection in the
scammer's own message). This guard is the code-level enforcement of those
invariants: a violation always forces human review **and always withholds the
reply**, regardless of the AI-suspicion score or the ``auto_pause_on_flag``
setting.

Design priority is **precision over recall for the money case.** The persona is
*supposed* to talk about money in order to stall — "my account's frozen", "I
can't send anything till payday", "I'd never wire money to someone I haven't
met". Those deflections are the tool working as intended and must NOT trip the
guard; only an *affirmative commitment to send* does. So money checks run clause
by clause and, within a clause, blank out only the span where a negation
*directly governs a sending verb* — the refusal — before screening what is left.
That scoping is deliberate: a negation attached to some other verb ("**don't**
worry, I'll **wire** the 500", "I **can't** **wait** to **send** you the money")
must NOT cancel a real commitment riding alongside it, since that reply is
casual enough to score ~0 on the suspicion checker and sail straight through.
The PII/identifier checks are pattern-based on the whole reply — those strings
are essentially never legitimate for the persona to emit, deflection or not.

Pure and dependency-free (regex only), so it runs and is tested without a
browser, exactly like :mod:`suspicion_checker`.
"""

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class GuardResult:
    """Outcome of a content-guard check on one proposed reply."""

    is_safe: bool
    violations: List[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        """Human-readable summary of why the reply was blocked (``""`` if safe)."""
        return "; ".join(self.violations)


class ContentGuard:
    """Screens an outgoing reply for hard-safety invariant violations."""

    # --- Negation scoped to the sending verb -------------------------------
    # A deflection is the persona *declining* to send — "I can't send", "I won't
    # wire", "I'm not going to buy", "I wish I could send but...". These must
    # pass: they are the bot doing its job (stalling by talking about money).
    #
    # The earlier design skipped a whole clause whenever *any* negation token
    # appeared in it. That over-suppressed: a negation governing some *other*
    # verb — "**don't** worry babe I'll **wire** the 500", "I **can't** **wait**
    # to **send** you the money" — wrongly cancelled a real commitment sharing
    # the clause (no comma to split them), so the worst-case reply slipped
    # through scoring 0.0 on the suspicion checker. Instead we now neutralise
    # only the span where a negation *directly governs a sending verb*, and screen
    # whatever commitment survives.
    #
    # ``_NEG_OPENER`` + a short gap + a ``_SEND_VERB`` is treated as a refusal
    # and blanked out. The gap may not cross a ``_NEG_BREAKER``: a future
    # commitment lead-in ("I'll", "imma") or an unambiguously *eager* idiom
    # ("can't **wait** to send", "won't **hesitate** to send") means the negation
    # is attached elsewhere and the send is a real promise, so it must stay
    # visible. Apostrophes are normalised to ``'`` before matching.
    _NEG_OPENER = (
        r"(?:can'?t|cannot|can ?not|won'?t|will\s+not|wouldn'?t|would\s+not|"
        r"don'?t|do\s+not|didn'?t|did\s+not|doesn'?t|isn'?t|aren'?t|ain'?t|"
        r"shouldn'?t|should\s+not|couldn'?t|could\s+not|mustn'?t|shan'?t|"
        r"never|no\s+way|unable|not|wish\s+i\s+could|if\s+i\s+could)"
    )
    _NEG_BREAKER = (
        r"(?:wait|waiting|hesitate|hesitating|"
        r"i'?ll|ill|imma|i'?ma|we'?ll|i\s+will|we\s+will)\b"
    )
    _SEND_VERB = (
        r"(?:send(?:ing|s)?|sent|wire|wiring|wired|transfer(?:ring|red|s)?|"
        r"pay(?:ing|s)?|paid|deposit(?:ing|ed|s)?|give|giving|gave|buy(?:ing|s)?|"
        r"bought|load(?:ing|ed|s)?|reload|remit(?:ting|ted)?|venmo|zelle|paypal|"
        r"cash\s?app|e-?transfer(?:red)?)"
    )
    _NEGATED_SEND = re.compile(
        r"\b" + _NEG_OPENER + r"\b"
        r"(?:\s+(?!" + _NEG_BREAKER + r")\w+(?:'\w+)?){0,6}?"
        r"\s+" + _SEND_VERB + r"\b",
        re.IGNORECASE,
    )

    # The set of "money objects" a commitment can be directed at. Mentioning one
    # is not itself a violation (the persona stalls by talking about money); it
    # only matters next to an affirmative sending verb, below.
    _MONEY_OBJECT = (
        r"(?:\bmoney\b|\bcash\b|\$\s?\d|\b\d{1,3}\s?k\b|"
        r"\b\d+\s?(?:dollars|usd|bucks|euros?|pounds|grand)\b|"
        r"gift\s?cards?|steam\s?cards?|itunes|google\s?play|\bcrypto\b|\bbitcoin\b|\bbtc\b|"
        r"\beth\b|\bfunds\b|\bfees?\b|western\s?union|moneygram|"
        r"the\s+(?:payment|deposit|money|amount))"
    )

    # Reply is examined clause by clause. We split not just on sentence
    # terminators but also on commas and adversative conjunctions ("but",
    # "though", ...) so a deflection and a commitment that sit on opposite sides
    # of a hedge — "I shouldn't, but for you I'll send the money" — are screened
    # independently. Within a clause, a negation no longer suppresses the whole
    # span (see ``_NEGATED_SEND``); it only blanks the verb it actually governs.
    _CLAUSE_SPLIT = re.compile(
        r"[.!?\n;,]+|\b(?:but|though|although|however)\b",
        re.IGNORECASE,
    )

    # --- Affirmative money-commitment signals ------------------------------
    # Each is applied to a clause after its negated-send spans are blanked out.
    # They are intentionally narrow: a *commitment to move funds*, not a mere
    # mention of money. The
    # ``(?:\s+\w+){0,3}?`` bridge keeps the verb and its object within a few
    # words, so an unrelated co-occurrence — "send you a hug instead, money's
    # too tight" — does not trip it (the verb and "money" are 4+ words apart).
    _MONEY_COMMIT = [
        # transfer verb (present or past) closely followed by a money object:
        # "I'll send you the money", "I transferred the funds", "pay the fee".
        re.compile(
            r"\b(send|sending|sent|wire|wiring|wired|transfer|transferring|transferred|"
            r"pay|paying|paid|deposit|depositing|deposited|reimburse|reimbursed|repay|repaid)\b"
            r"(?:\s+\w+){0,3}?\s*" + _MONEY_OBJECT,
            re.IGNORECASE,
        ),
        # a claim that the money is already sent / on its way / in their account
        re.compile(
            r"\b(the|your)\s+(money|cash|funds|payment|\$\s?\d+)\b(?:\s+\w+){0,3}?\s*"
            r"\b(is|are|has been|have been|was|were)\b\s+"
            r"(on\s+(?:its|the)\s+way|sent|wired|transferred|deposited|in\s+your\s+account)",
            re.IGNORECASE,
        ),
        # payment apps addressed straight at a recipient/amount: "venmo you 500"
        re.compile(
            r"\b(venmo|zelle|cash\s?app|cashapp|paypal)\s+"
            r"(you|me|him|her|them|u|ya|it|\$\s?\d|\d)",
            re.IGNORECASE,
        ),
        # ...or a first-person commitment lead-in just before the app name.
        re.compile(
            r"\b(i'?ll|i will|let me|i can|i'?m gonna|i'?m going to|gonna|i'?d)\b"
            r"(?:\s+\w+){0,3}?\s+\b(venmo|zelle|cash\s?app|cashapp|paypal)\b",
            re.IGNORECASE,
        ),
        # buying/loading the classic scam payout instruments for them
        re.compile(
            r"\b(buy|buying|bought|purchase|purchasing|load|loading|reload|"
            r"grab|pick up|picking up)\b(?:\s+\w+){0,3}?\s*"
            r"(gift\s?cards?|steam\s?cards?|itunes|google\s?play|\bcrypto\b|\bbitcoin\b|\bbtc\b)",
            re.IGNORECASE,
        ),
        # an *unambiguous* money verb followed by a bare amount: "wire the 500",
        # "deposit 200". Restricted to wire/deposit/remit — you don't wire or
        # deposit "100 reasons" — so a bare number is safe to treat as cash here
        # (whereas send/pay/buy stay number-agnostic to avoid blocking "send you
        # the 100 reasons i love you").
        re.compile(
            r"\b(wire|wiring|wired|deposit|depositing|deposited|remit|remitted|"
            r"e-?transfer(?:red)?)\b(?:\s+\w+){0,2}?\s*(?:the\s+)?\$?\d{2,}\b",
            re.IGNORECASE,
        ),
    ]

    # --- Personal / financial identifiers (whole-reply) --------------------
    # US Social Security number, grouped 3-2-4 by a dash, space or dot. The
    # distinctive 3-2-4 shape keeps it off phone numbers (which group 3-3-4).
    _SSN = re.compile(r"\b\d{3}[-. ]\d{2}[-. ]\d{4}\b")
    # ...and an SSN volunteered as a bare 9-digit run *when explicitly labelled*
    # ("my ssn is 123456789", "social security number 123456789"). The label is
    # required because an unlabelled 9-digit run is too ambiguous (order numbers,
    # etc.) to block on, but a labelled one is unmistakably PII and otherwise
    # slips past both ``_SSN`` (no separators) and ``_LONG_NUMBER`` (needs 13+).
    _SSN_LABELLED = re.compile(
        r"\b(?:ssn|social(?:\s+security)?(?:\s+(?:number|num|no|#))?)\b"
        r"[^\d]{0,12}\d{9}\b",
        re.IGNORECASE,
    )
    # Crypto wallet addresses (high precision).
    _CRYPTO_ADDR = [
        re.compile(r"\b0x[a-fA-F0-9]{40}\b"),          # Ethereum
        re.compile(r"\bbc1[a-z0-9]{20,80}\b", re.IGNORECASE),  # Bitcoin bech32
    ]
    # Explicitly labelled bank identifiers, even when short (e.g. an 8-digit
    # account number that the length heuristic below would miss).
    _ACCOUNT = re.compile(
        r"\b(routing|account|acct|swift|iban)\b[^.!?\d]{0,15}\d{5,}",
        re.IGNORECASE,
    )
    # A run of 13+ digits (optionally grouped by spaces/dashes) — card or
    # account length. The 13 floor sits safely above any phone number
    # (a +country-code number tops out around 11–12 digits), so "call me at
    # +1 555 123 4567" is left alone.
    _LONG_NUMBER = re.compile(r"\d[\d \-]{11,}\d")

    def check(self, reply: str) -> GuardResult:
        """
        Inspect a proposed outgoing reply and return a :class:`GuardResult`.

        ``is_safe`` is ``True`` when the reply violates none of the hard
        invariants. When it is ``False``, ``violations`` lists every distinct
        reason, suitable for the suspicion reason / review queue.
        """
        if not reply or not reply.strip():
            return GuardResult(is_safe=True)

        # Normalise curly apostrophes so "I'll" and "I’ll" match identically.
        text = reply.replace("’", "'")
        violations: List[str] = []

        # Money commitment: clause by clause. Within each clause, blank out the
        # spans where a negation directly governs a sending verb (the persona
        # *declining* — the desired behaviour) so a refusal can no longer mask a
        # *separate* commitment made in the same breath, then screen whatever
        # survives. The span is replaced with a hard separator (" ; ") rather
        # than a space so a removed refusal can never let an earlier verb drift
        # up against a later money word and read as a commitment.
        for clause in self._CLAUSE_SPLIT.split(text):
            s = clause.strip()
            if not s:
                continue
            screened = self._NEGATED_SEND.sub(" ; ", s)
            if any(pat.search(screened) for pat in self._MONEY_COMMIT):
                violations.append("reply appears to commit to sending money/payment")
                break

        # Personal / financial identifiers: whole reply.
        if self._SSN.search(text) or self._SSN_LABELLED.search(text):
            violations.append("reply contains an SSN-like number")
        if any(pat.search(text) for pat in self._CRYPTO_ADDR):
            violations.append("reply contains a crypto wallet address")
        if self._ACCOUNT.search(text):
            violations.append("reply contains a bank account/routing number")
        elif self._has_long_number(text):
            # ``elif``: a labelled account number is usually *also* a long digit
            # run, so prefer the more specific message and avoid double-reporting
            # the same number. Either way the reply is unsafe and gets withheld.
            violations.append("reply contains a card/account-length number")

        return GuardResult(is_safe=not violations, violations=violations)

    @classmethod
    def _has_long_number(cls, text: str) -> bool:
        """True if any digit run (ignoring spaces/dashes) is 13+ digits long."""
        for match in cls._LONG_NUMBER.finditer(text):
            if len(re.sub(r"\D", "", match.group())) >= 13:
                return True
        return False
