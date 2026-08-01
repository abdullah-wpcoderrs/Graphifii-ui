"""Pure-logic tests for the streaming tag parser — no DB, no network.

This is the piece the WebSocket handler trusts to correctly split one raw
LLM token stream into prose events and per-file content events. A bug here
either leaks marker syntax into the visible answer or corrupts a proposed
file's content, so it is tested chunk-by-chunk rather than only on whole
strings — the real failure mode is a marker split across two network reads.
"""
from __future__ import annotations

from graphify.server.agent_llm import (
    FileDelta,
    FileEnd,
    FileStart,
    StreamDemultiplexer,
    TextDelta,
)


def _feed_all(demux: StreamDemultiplexer, chunks: list[str]) -> list:
    events = []
    for chunk in chunks:
        events.extend(demux.feed(chunk))
    events.extend(demux.finish())
    return events


def test_plain_prose_passes_through_untouched():
    demux = StreamDemultiplexer()
    events = _feed_all(demux, ["Hello, ", "world!"])
    assert events == [TextDelta(text="Hello, "), TextDelta(text="world!")]
    assert demux.paths == []


def test_single_file_block_whole_in_one_chunk():
    demux = StreamDemultiplexer()
    chunk = "Here is the fix:\n\n<<<FILE: src/a.py>>>\nprint('hi')\n<<<END FILE>>>\n\nDone."
    events = _feed_all(demux, [chunk])

    assert TextDelta(text="Here is the fix:\n\n") in events
    assert FileStart(path="src/a.py") in events
    assert any(isinstance(e, FileDelta) and e.path == "src/a.py" for e in events)
    assert FileEnd(path="src/a.py") in events
    assert events[-1] == TextDelta(text="\n\nDone.")

    file_text = "".join(e.text for e in events if isinstance(e, FileDelta) and e.path == "src/a.py")
    assert file_text == "print('hi')"
    assert demux.paths == ["src/a.py"]


def test_marker_split_across_many_small_chunks():
    """The realistic streaming case: markers arrive one token at a time."""
    whole = "before <<<FILE: x.py>>>\nbody\n<<<END FILE>>> after"
    demux = StreamDemultiplexer()
    # Feed one character at a time — the worst case for a marker straddling
    # chunk boundaries.
    events = _feed_all(demux, list(whole))

    prose = "".join(e.text for e in events if isinstance(e, TextDelta))
    file_text = "".join(e.text for e in events if isinstance(e, FileDelta) and e.path == "x.py")

    assert prose == "before  after"
    assert file_text == "body"
    assert FileStart(path="x.py") in events
    assert FileEnd(path="x.py") in events
    # No marker fragment ever leaked into visible prose.
    assert "<<<" not in prose
    assert ">>>" not in prose


def test_multiple_file_blocks_in_one_response():
    whole = (
        "First file:\n<<<FILE: a.py>>>\nA\n<<<END FILE>>>\n"
        "Second file:\n<<<FILE: b.py>>>\nB\n<<<END FILE>>>\nDone."
    )
    demux = StreamDemultiplexer()
    events = _feed_all(demux, [whole[i : i + 7] for i in range(0, len(whole), 7)])

    assert demux.paths == ["a.py", "b.py"]
    a_text = "".join(e.text for e in events if isinstance(e, FileDelta) and e.path == "a.py")
    b_text = "".join(e.text for e in events if isinstance(e, FileDelta) and e.path == "b.py")
    assert a_text == "A"
    assert b_text == "B"


def test_unterminated_file_block_is_closed_on_finish():
    """A truncated provider response must not leave a file block open forever."""
    demux = StreamDemultiplexer()
    events = _feed_all(demux, ["<<<FILE: partial.py>>>\nsome content but no end marker"])

    assert FileStart(path="partial.py") in events
    assert FileEnd(path="partial.py") in events
    # The end event is the last thing emitted once the stream is finished.
    assert events[-1] == FileEnd(path="partial.py")


def test_malformed_marker_with_empty_path_is_treated_as_prose():
    demux = StreamDemultiplexer()
    events = _feed_all(demux, ["oops <<<FILE: >>> not a real block"])

    assert demux.paths == []
    assert not any(isinstance(e, (FileStart, FileEnd, FileDelta)) for e in events)
    prose = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert "<<<FILE:" in prose  # preserved verbatim, not silently dropped


def test_repeated_path_is_recorded_once_in_paths_list():
    whole = "<<<FILE: a.py>>>\nfirst\n<<<END FILE>>>more<<<FILE: a.py>>>\nsecond\n<<<END FILE>>>"
    demux = StreamDemultiplexer()
    _feed_all(demux, [whole])
    assert demux.paths == ["a.py"]
