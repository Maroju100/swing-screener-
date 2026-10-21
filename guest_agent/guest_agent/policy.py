"""Deterministic safety rules that sit OUTSIDE the model.

The model proposes; these rules decide what may go out without a human. They run on
every message and can only make a decision stricter, never looser, so a confused or
manipulated model reply cannot talk its way past them.
"""
import re
from dataclasses import dataclass, field

# Life-safety or property-damage words: page the on-call person immediately, never auto-reply.
EMERGENCY = [
    r"\bfire\b", r"\bsmoke\b", r"\bgas\b", r"carbon monoxide", r"\bco alarm\b", r"\bflood",
    r"\bleak", r"no power", r"power (is )?out", r"\binjur", r"\bhurt\b", r"\bbleed",
    r"ambulance", r"\b911\b", r"police", r"break[- ]?in", r"broke in", r"locked out",
    r"can'?t get in", r"intruder", r"\bunsafe\b", r"no (hot )?water", r"\bac\b.*(broken|not working|out)",
    r"air ?condition\w*.*(broken|not working|out)",
]

# Anything that commits money, changes the booking or concerns a dispute: draft only.
NEEDS_APPROVAL = [
    r"refund", r"discount", r"\bcredit\b", r"compensat", r"money back", r"chargeback",
    r"cancel", r"early check[- ]?in", r"late check[- ]?out", r"extend", r"extra night",
    r"\bpet", r"\bdog\b", r"\bcat\b", r"\bparty\b", r"\bevent\b", r"extra guest", r"more guests",
    r"damage", r"broke", r"broken", r"stain", r"complain", r"dirty", r"bed ?bugs?", r"\bbugs?\b",
    r"cockroach", r"\bmold\b", r"review", r"\blawyer\b", r"\bsue\b", r"airbnb support",
    r"pay (you )?(directly|outside|off[- ]platform)", r"venmo", r"zelle", r"cash app", r"wire",
]

ACCESS = [r"door code", r"lock ?box", r"access code", r"\bkey\b", r"\bcode\b", r"\bgate\b"]


def _hits(patterns, text):
    t = text.lower()
    return [p for p in patterns if re.search(p, t)]


@dataclass
class Verdict:
    route: str                    # "auto_send" | "approval" | "emergency"
    reasons: list = field(default_factory=list)


def screen_message(message: str) -> Verdict:
    """Rules applied to the guest's own words, before any model call."""
    e = _hits(EMERGENCY, message)
    if e:
        return Verdict("emergency", [f"emergency keyword: {p}" for p in e])
    a = _hits(NEEDS_APPROVAL, message)
    if a:
        return Verdict("approval", [f"needs a human: {p}" for p in a])
    return Verdict("auto_send", [])


def screen_reply(reply: str) -> list:
    """Rules applied to the drafted reply. Any hit forces approval."""
    problems = []
    t = reply.lower()
    if re.search(r"\b(refund|discount|credit|compensat|free night|waive)", t):
        problems.append("draft offers money or a concession")
    if re.search(r"\b(guarantee|promise)\b", t):
        problems.append("draft makes a promise")
    if re.search(r"https?://", t) and "{{" not in t:
        problems.append("draft contains a link")
    if re.search(r"\b\d{4,}\b", reply) and "{{door_code}}" not in reply:
        problems.append("draft contains a long number (possible code or phone)")
    return problems
