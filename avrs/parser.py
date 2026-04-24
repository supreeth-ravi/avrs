from __future__ import annotations

import re

from avrs.config import Segment


def parse_utterance(text: str) -> list[Segment]:
    placeholder_pattern = re.compile(r"\{(\w+)\}")

    if placeholder_pattern.search(text):
        return _parse_annotated(text, placeholder_pattern)
    return _parse_ner(text)


def _parse_annotated(text: str, pattern: re.Pattern) -> list[Segment]:
    segments: list[Segment] = []
    last = 0

    for match in pattern.finditer(text):
        start, end = match.span()
        static_text = text[last:start]
        if static_text:
            segments.append(Segment(type="static", text=static_text))
        segments.append(Segment(type="slot", text="", slot_key=match.group(1)))
        last = end

    tail = text[last:]
    if tail:
        segments.append(Segment(type="static", text=tail))

    return segments


def _parse_ner(text: str) -> list[Segment]:
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
    except (ImportError, OSError):
        return [Segment(type="static", text=text)]

    doc = nlp(text)
    slot_labels = {"MONEY", "CARDINAL", "ORG", "PERSON", "DATE"}

    if not doc.ents:
        return [Segment(type="static", text=text)]

    segments: list[Segment] = []
    last = 0

    for ent in doc.ents:
        if ent.label_ not in slot_labels:
            continue
        if last < ent.start_char:
            segments.append(Segment(type="static", text=text[last:ent.start_char]))
        segments.append(
            Segment(type="slot", text=ent.text, slot_key=ent.label_.lower())
        )
        last = ent.end_char

    if last < len(text):
        segments.append(Segment(type="static", text=text[last:]))

    return segments or [Segment(type="static", text=text)]


def fill_slots(segments: list[Segment], slots: dict) -> list[Segment]:
    filled: list[Segment] = []
    for seg in segments:
        if seg.type == "slot":
            # Use empty string for missing keys rather than crashing — the
            # clean_for_tts pass will strip any residual {placeholder} markers.
            value = slots.get(seg.slot_key, slots.get(seg.slot_key.lower(), ""))
            filled.append(Segment(type="slot", text=str(value),
                                  slot_key=seg.slot_key))
        else:
            filled.append(seg)
    return filled
