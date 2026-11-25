"""Pre-model screen for instruction-like text (patent claim 6).

A source document is plain data. If it contains a passage addressed to an automated reader, for example
"ignore previous instructions" or "set the score to critical", the document is quarantined: its text is not
given to the language model and not given to the keyword extractor. A reviewer sees the quarantine list.

The screen is deliberately narrow. Government notices do not address AI systems, so ordinary regulatory text does not
match. It is a first line only; the schema, the validators and the severity table still stand behind it.
"""
from __future__ import annotations
import re
import unicodedata

_AI = r"(?:ai|a\.i\.|language model|llm|chatbot|chat bot|assistant|automated (?:reader|system|agent|tool)|ai agent|crawler|scraper|bot|claude|chatgpt|gpt)"
RULES = [
    ("override_instructions", r"\b(?:ignore|disregard|forget|override|bypass|overrule)\b[^.\n]{0,30}\b(?:previous|prior|above|earlier|preceding|your|all|any|the)\b[^.\n]{0,30}\b(?:instructions?|prompts?|rules|guidelines|directions|constraints|system prompt)\b"),
    ("system_prompt_reference", r"\b(?:system prompt|developer (?:message|prompt)|system message|hidden instructions?)\b"),
    ("addresses_ai", rf"\b(?:you are|you're|act as|pretend to be|behave as)\s+(?:now\s+)?(?:an?\s+|the\s+)?{_AI}\b"),
    ("addresses_ai", rf"\b(?:note|message|instruction|attention|important|dear|hello|hi)s?\s*(?:to|for)\s+(?:the\s+)?{_AI}\b"),
    ("addresses_ai", rf"\b(?:if|when)\s+you\s+are\s+(?:an?\s+)?{_AI}\b"),
    ("addresses_ai", rf"\b{_AI}\s*[:,]\s*(?:you\s+)?(?:must|should|shall|please|do not|don't|always|never|output|respond|reply|answer|set|mark|assign|report|ignore)\b"),
    ("output_format_demand", r"\b(?:respond|reply|answer|output|return)\s+(?:only\s+)?(?:with|in|as)\s+(?:json|the following|exactly|this)\b"),
    ("score_manipulation", r"\b(?:set|raise|increase|lower|change|override|adjust|assign)\s+(?:the\s+)?(?:risk\s+|exposure\s+)?(?:score|stage|effect|severity|multiplier|tier)\b"),
    ("score_manipulation", r"\b(?:mark|report|classify|label|record|treat|tag)\s+(?:this|it|the\s+(?:event|measure|restriction|notice))\s+as\s+(?:enacted|ban|banned|confirmed|critical|verified)\b"),
    ("fake_role_markup", r"<\s*/?\s*(?:system|assistant|instructions?|prompt)\s*>|\[\s*(?:system|inst|/inst)\s*\]|\bbegin\s+(?:system|instructions?|prompt)\b|\b(?:###\s*)?(?:system|assistant)\s*:\s"),
    ("secrecy_demand", r"\bdo not\s+(?:mention|tell|reveal|disclose)\s+(?:this|these|the)\s+(?:instruction|message|text|prompt)s?\b"),
]
_COMPILED = [(name, re.compile(rx, re.I)) for name, rx in RULES]
_ZERO_WIDTH = re.compile("[​‌‍⁠﻿‪-‮⁦-⁩]")
HIDDEN_CHAR_LIMIT = 3


def _normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZERO_WIDTH.sub("", t)
    return re.sub(r"\s+", " ", t)


def screen(text: str) -> list[str]:
    """Reason codes. An empty list means the text may go to the extractor."""
    raw = text or ""
    reasons: list[str] = []
    if len(_ZERO_WIDTH.findall(raw)) >= HIDDEN_CHAR_LIMIT:
        reasons.append("hidden_characters")
    t = _normalise(raw)
    for name, rx in _COMPILED:
        if rx.search(t) and name not in reasons:
            reasons.append(name)
    return reasons
