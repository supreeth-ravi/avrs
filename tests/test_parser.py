import pytest

from avrs.parser import fill_slots, parse_utterance


def test_annotated_slots():
    # "Hello {name}, your amount is ₹{amount}." → 5 segments:
    # "Hello ", {name}, ", your amount is ₹", {amount}, "."
    segs = parse_utterance("Hello {name}, your amount is ₹{amount}.")
    assert len(segs) == 5
    assert segs[1].type == "slot"
    assert segs[1].slot_key == "name"
    assert segs[3].type == "slot"
    assert segs[3].slot_key == "amount"


def test_fill_slots():
    segs = parse_utterance("Premium for {plan} is ₹{amount}.")
    filled = fill_slots(segs, {"plan": "Gold", "amount": "5000"})
    assert filled[1].text == "Gold"
    assert filled[3].text == "5000"


def test_no_slots():
    # Text with no placeholders and no NER-triggering entities → single static segment
    text = "Thank you for choosing us."
    segs = parse_utterance(text)
    assert all(s.type == "static" for s in segs)
    assert len(segs) == 1
    assert segs[0].text == text


def test_fill_slots_missing_key():
    segs = parse_utterance("Hello {name}.")
    with pytest.raises(ValueError):
        fill_slots(segs, {})


def test_annotated_leading_slot():
    segs = parse_utterance("{name} is here.")
    assert segs[0].type == "slot"
    assert segs[0].slot_key == "name"
    assert segs[1].type == "static"


def test_annotated_trailing_slot():
    segs = parse_utterance("Welcome to {city}")
    assert segs[0].type == "static"
    assert segs[1].type == "slot"
    assert segs[1].slot_key == "city"


def test_multiple_consecutive_slots():
    segs = parse_utterance("{a}{b}")
    slot_keys = [s.slot_key for s in segs if s.type == "slot"]
    assert "a" in slot_keys
    assert "b" in slot_keys
