import pytest

from avrs.router import RenderRouter


def test_tts_fallback(mock_config):
    router = RenderRouter(mock_config)
    merged, rendered = router.render("Hello world")
    assert all(r.mode == "tts" for r in rendered)
    assert merged.audio is not None
    assert len(merged.audio) > 0


def test_cache_hit(mock_config):
    router = RenderRouter(mock_config)
    router.render("Hello world")
    _, rendered2 = router.render("Hello world")
    assert any(r.mode == "cached" for r in rendered2)


def test_slot_rendering(mock_config):
    router = RenderRouter(mock_config)
    merged, rendered = router.render(
        "Your premium for {plan} is ₹{amount}.",
        slots={"plan": "Gold", "amount": "5000"},
    )
    assert len(rendered) >= 3
    assert merged.audio is not None
    assert len(merged.audio) > 0


def test_render_returns_merged_audio(mock_config):
    router = RenderRouter(mock_config)
    merged, rendered = router.render("Thank you for calling.")
    assert merged.sr == mock_config.sr
    assert merged.audio.ndim == 1


def test_slot_segments_are_tts_first_run(mock_config):
    router = RenderRouter(mock_config)
    _, rendered = router.render(
        "Hello {name}.", slots={"name": "Priya"}
    )
    slot_segs = [r for r in rendered if r.text == "Priya"]
    assert all(r.mode == "tts" for r in slot_segs)
