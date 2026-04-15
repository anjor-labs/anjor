import pytest

from anjor.watchers.antigravity import AntiGravityTranscriptWatcher
from anjor.watchers.codex import CodexTranscriptWatcher
from anjor.watchers.gemini import GeminiTranscriptWatcher


@pytest.mark.parametrize(
    "cls", [GeminiTranscriptWatcher, CodexTranscriptWatcher, AntiGravityTranscriptWatcher]
)
def test_provider_stubs(cls):
    w = cls()
    assert bool(w.provider_name)
    assert bool(w.source_tag)
    assert " " not in w.source_tag
    assert bool(w.default_paths())
    assert isinstance(w.default_paths(), list)

    assert w.parse_line('{"some": "json"}') is None
    assert w.parse_line("not json at all") is None
