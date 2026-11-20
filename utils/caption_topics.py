# -*- coding: utf-8 -*-
"""Find public ``#topic`` occurrences in a final caption.

Pure text only: no browser, no platform candidate list, no writes. The publish
commands use the same parsed occurrences for their own per-platform evidence.

A topic is ``#`` followed by one or more letters, digits, underscores, or CJK
characters. Whitespace, another ``#``, and punctuation end it. URL fragments
(``https://…/#frag``, ``http://…/#frag``, ``www.…/#frag``) are not topics and
are left untouched in :attr:`CaptionTopics.text`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

#: Platform evidence states shared by the publish commands. ``text`` means the
#: occurrence is present as plain text (no candidate association was read back).
STATUS_TEXT = "text"
STATUS_LINKED = "linked"

#: Schemes and host prefixes whose ``#fragment`` is part of a URL.
_URL_RE = re.compile(r"(?i)(?:https?://|www\.)[^\s]*")


@dataclass(frozen=True, slots=True)
class TopicOccurrence:
    """One public ``#topic`` in the original caption."""

    name: str
    text: str
    start: int
    end: int
    index: int


@dataclass(frozen=True, slots=True)
class CaptionTopics:
    """Parsed caption with the original string and ordered occurrences."""

    text: str
    occurrences: tuple[TopicOccurrence, ...]


@dataclass(frozen=True, slots=True)
class TopicResult:
    """Evidence for one occurrence: what the platform observed for it."""

    occurrence: TopicOccurrence
    status: str
    reason: str | None = None


def _is_topic_char(char: str) -> bool:
    return char == "_" or char.isalnum()


def _url_spans(caption: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _URL_RE.finditer(caption)]


def parse_caption_topics(caption: str) -> CaptionTopics:
    """Return every public ``#topic`` in ``caption``, in order and with duplicates.

    ``start``/``end`` are code-point offsets into ``caption``; ``text`` is the
    exact ``#name`` slice and ``index`` is 1-based.
    """
    text = str(caption)
    occurrences: list[TopicOccurrence] = []
    urls = _url_spans(text)
    cursor = 0
    while True:
        start = text.find("#", cursor)
        if start < 0:
            break
        if any(url_start <= start < url_end for url_start, url_end in urls):
            cursor = start + 1
            continue
        end = start + 1
        while end < len(text) and _is_topic_char(text[end]):
            end += 1
        if end == start + 1:
            cursor = start + 1
            continue
        occurrences.append(
            TopicOccurrence(
                name=text[start + 1:end],
                text=text[start:end],
                start=start,
                end=end,
                index=len(occurrences) + 1,
            )
        )
        cursor = end
    return CaptionTopics(text=text, occurrences=tuple(occurrences))


def text_results(
    topics: CaptionTopics, *, reason: str | None = None
) -> tuple[TopicResult, ...]:
    """Report every occurrence as plain text evidence, preserving order."""
    return tuple(
        TopicResult(occurrence=occurrence, status=STATUS_TEXT, reason=reason)
        for occurrence in topics.occurrences
    )
