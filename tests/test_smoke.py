"""Smoke tests: synthesize a tiny MIDI in-memory and drive every build path.

No fixtures on disk (sources/ is git-ignored) — we hand-write a minimal valid
SMF so CI is fully self-contained. We assert the arranger produces a well-formed
GoatTracker GTS5 `.sng`; we don't (can't) judge how it *sounds*.
"""
import struct

import pytest

import midi_inspect
import midi_to_sng as m


def _vlq(n):
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def _track(events, name=None, program=None, ch=0):
    """Build one MTrk chunk from (delta, status, d1, d2) note events."""
    body = bytearray()
    if name:
        body += _vlq(0) + b"\xff\x03" + _vlq(len(name)) + name.encode()
    if program is not None:
        body += _vlq(0) + bytes([0xC0 | ch, program])
    for delta, status, d1, d2 in events:
        body += _vlq(delta) + bytes([status, d1, d2])
    body += _vlq(0) + b"\xff\x2f\x00"          # end of track
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def make_midi(div=96, bars=8):
    """A 3-track SMF: a 'Melody' on ch1, a 'Bass' on ch2, a kick on ch10."""
    q = div                                     # one quarter note
    lead, bass, drums = [], [], []
    for bar in range(bars):
        base = bar * 4 * q
        for beat in range(4):
            t = base + beat * q
            pitch = 72 + (beat % 3)             # a little C5-ish wiggle
            lead.append((q // 2 if t else 0, 0x90, pitch, 100))
            lead.append((q // 2, 0x80, pitch, 0))
            bass.append((q // 2 if t else 0, 0x91, 36 + (beat % 2), 100))
            bass.append((q // 2, 0x81, 36 + (beat % 2), 0))
            drums.append((q // 2 if t else 0, 0x99, 36, 110))   # kick on ch10
            drums.append((q // 2, 0x89, 36, 0))
    hdr = b"MThd" + struct.pack(">IHHH", 6, 1, 3, div)
    return (hdr
            + _track(lead, name="Melody", program=73, ch=0)
            + _track(bass, name="Bass", program=38, ch=1)
            + _track(drums, name="Drums", ch=9))


@pytest.fixture
def midi_file(tmp_path):
    p = tmp_path / "tiny.mid"
    p.write_bytes(make_midi())
    return str(p)


def _assert_valid_sng(path):
    with open(path, "rb") as f:
        data = f.read()
    assert data[:4] == b"GTS5", "missing GTS5 magic"
    assert len(data) > 100, "suspiciously small .sng"


def test_parse_midi_roundtrip(midi_file):
    div, end_tick, notes, drums = m.parse_midi(midi_file)
    assert div == 96
    assert notes[0] and notes[1]          # lead (ch1) + bass (ch2) parsed
    assert len(drums) == 32               # 8 bars * 4 kicks


def test_build_mono_clean(midi_file, tmp_path):
    out = tmp_path / "clean.sng"
    m.build(midi_file, str(out), tempo=6, rows_per_pat=64,
            mode="clean", chmap="1,2,-", title="T")
    _assert_valid_sng(out)


def test_build_mono_fill(midi_file, tmp_path):
    out = tmp_path / "fill.sng"
    # fill the lead's holes from ch1 (priority-pool list, the fixed --fill path)
    m.build(midi_file, str(out), tempo=6, rows_per_pat=64,
            mode="clean", chmap="1,2,-", fill=[0], title="T")
    _assert_valid_sng(out)


@pytest.mark.parametrize("preset", ["darude", "darude-build"])
def test_build_arranged_presets(midi_file, tmp_path, preset):
    out = tmp_path / f"{preset}.sng"
    m.build_arranged(midi_file, str(out), tempo=6, rows_per_pat=64,
                     sections=m.parse_arrange(preset), chmap="1,2,-",
                     four_floor=True, title="T")
    _assert_valid_sng(out)


def test_parse_arrange_spec():
    secs = m.parse_arrange("8:khr,16:khbl")
    assert secs[0] == (8, {"k", "h"}, True)
    assert secs[1] == (16, {"k", "h", "b", "l"}, False)


def test_build_stereo_from_combined(midi_file, tmp_path):
    out = tmp_path / "stereo.sng"
    div, et, notes, drums = m.parse_midi(midi_file)
    voices = [(0, "lead", "@1"), (1, "bass", "@2"),
              (3, "kick", "@"), (4, "hihat", "@")]
    m.build_stereo(str(out), voices, tempo=6, rows_per_pat=64,
                   title="T", combined=(div, notes, drums, et))
    _assert_valid_sng(out)


def test_midi_inspect_finds_named_tracks(midi_file):
    div, tracks = midi_inspect.parse_tracks(midi_file)
    names = {t["name"] for t in tracks}
    assert {"Melody", "Bass", "Drums"} <= names
    melody = next(t for t in tracks if t["name"] == "Melody")
    assert melody["prog"][0] == 73        # the Flute program we wrote


def test_note_byte_clamps_into_sid_range():
    for midi_pitch in (0, 24, 60, 96, 127):
        b = m.note_byte(midi_pitch)
        assert m.FIRSTNOTE <= b <= m.LASTNOTE
