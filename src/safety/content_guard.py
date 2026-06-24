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
guard; only an *affirmative commitment to send* does. So money checks run
sentence by sentence and skip any sentence carrying a negation. The
PII/identifier checks are pattern-based on the whole reply — those strings are
essentially never legitimate for the persona to emit, deflection or not.

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

    # --- Negation / deflection markers -------------------------------------
    # A sentence carrying any of these is the persona *declining* to send (the
    # desired behaviour), so its money signals are ignored. Apostrophes are
    # normalised to ``'`` before matching, so only the straight form is listed.
    # The ``not <verb>`` arm catches "I'm not sending any gift cards" etc.
    _NEGATION = re.compile(
        r"\b("
        r"can'?t|can ?not|cannot|won'?t|will not|wouldn'?t|would not|"
        r"don'?t|do not|didn'?t|did not|never|no way|unable|isn'?t|ain'?t|"
        r"not\s+(?:gonna\s+|going\s+to\s+|able\s+to\s+)?"
        r"(?:send|sending|wir(?:e|ing)|transfer(?:ring)?|pay(?:ing)?|"
        r"deposit(?:ing)?|buy(?:ing)?|load(?:ing)?|venmo|zelle|paypal|giv(?:e|ing))|"
        r"not (?:going|gonna|able|sure|gonna be)|"
        r"wish i could|if i could|i'?d love to but"
        r")\b",
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
    # "though", ...), because a negation only suppresses *its own* clause — a
    # "warm capitulation" packs a hedge and a commitment into one breath
    # ("I shouldn't, but for you I'll send the money"), and the committing
    # clause must still be screened on its own.
    _CLAUSE_SPLIT = re.compile(
        r"[.!?\n;,]+|\b(?:but|though|although|however)\b",
        re.IGNORECASE,
    )

    # --- Affirmative money-commitment signals ------------------------------
    # Each is applied only to a non-negated clause. They are intentionally
    # narrow: a *commitment to move funds*, not a mere mention of money. The
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
    # US Social Security number.
    _SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
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

        # Money commitment: clause by clause, ignoring deflection clauses.
        for clause in self._CLAUSE_SPLIT.split(text):
            s = clause.strip()
            if not s or self._NEGATION.search(s):
                continue
            if any(pat.search(s) for pat in self._MONEY_COMMIT):
                violations.append("reply appears to commit to sending money/payment")
                break

        # Personal / financial identifiers: whole reply.
        if self._SSN.search(text):
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
