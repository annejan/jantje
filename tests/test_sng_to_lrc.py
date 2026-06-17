"""Tests for sng_to_lrc.py — map a karaoke MIDI's lyrics onto a SID render's
vocal-note onsets. Self-contained: synthesize a tiny karaoke SMF + build a .sng.
"""
import struct
import subprocess
import sys

import midi_to_sng as m
import sng_to_lrc as s


def _vlq(n):
    out = bytearray([n & 0x7F]); n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80); n >>= 7
    return bytes(out)


def _lyric(text):                               # meta-lyric WITHOUT a delta
    b = text.encode("latin1")
    return b"\xff\x01" + _vlq(len(b)) + b


def make_karaoke(tmp_path, div=96, bars=4):
    """Karaoke SMF: a VOCAL on ch1 (one note/beat) with a '/'-prefixed lyric exactly
    ON each note (KAR = one word per line), a low BASS on ch2, and a DECOY track on
    ch3 with the SAME note count but shifted OFF the lyric grid — so the vocal channel
    can only be found by lyric-ALIGNMENT, not by note count."""
    q = div
    words = ["/Bar", "/bie", "/girl", "/yeah"]
    vocal = bytearray(); bass = bytearray(); decoy = bytearray()
    for bar in range(bars):
        for beat in range(4):
            on = 0 if (bar == 0 and beat == 0) else q // 2
            vocal += _vlq(on) + _lyric(words[beat])             # lyric AT the note tick
            vocal += _vlq(0) + bytes([0x90, 72, 100]) + _vlq(q // 2) + bytes([0x80, 72, 0])
            bass += _vlq(on) + bytes([0x91, 36, 100]) + _vlq(q // 2) + bytes([0x81, 36, 0])
            # decoy: one note/beat, a quarter-beat off the grid (never near a lyric)
            decoy += _vlq(on + q // 4) + bytes([0x92, 60, 80])
            decoy += _vlq(q // 2) + bytes([0x82, 60, 0])
    def trk(body):
        body = bytes(body) + _vlq(0) + b"\xff\x2f\x00"
        return b"MTrk" + struct.pack(">I", len(body)) + body
    hdr = b"MThd" + struct.pack(">IHHH", 6, 1, 3, div)
    p = tmp_path / "kar.mid"
    p.write_bytes(hdr + trk(vocal) + trk(bass) + trk(decoy))
    return str(p)


def test_read_midi_collects_lyrics_and_channels(tmp_path):
    syl, chan, div = s.read_midi(make_karaoke(tmp_path))
    assert div == 96
    assert len(syl) == 16                       # 4 bars * 4 beats
    assert {0, 1, 2} <= set(chan)               # vocal ch1, bass ch2, decoy ch3 (0-based)
    assert len(chan[0]) == len(chan[2]) == 16   # vocal and decoy: equal note count


def test_pick_vocal_channel_prefers_alignment_over_count():
    """The regression that broke The Sign: a busy channel with a closer note count
    must NOT beat the lyric-aligned one."""
    syl = [(0, "a"), (100, "b"), (200, "c"), (300, "d"), (400, "e")]
    chan = {
        0: [0, 100, 200, 300, 400],             # vocal: 5 notes, ON the lyric grid
        1: [40, 140, 240, 340, 440, 540, 640],   # decoy: 7 notes, OFF grid, count-closer
    }
    # target=6 is closer to the decoy's 7 than the vocal's 5 -> count alone picks decoy
    assert s.pick_vocal_channel(chan, syl, 96, 6, None) == 0
    assert s.pick_vocal_channel(chan, syl, 96, 6, 2) == 1   # explicit override wins


def test_group_lines_splits_on_kar_markers():
    syl = [(0, "\\Hel"), (1, "lo"), (2, "/world"), (3, "!")]
    assert [t for _, t in s.group_lines(syl)] == ["Hello", "world!"]


def test_end_to_end_lrc_from_render(tmp_path):
    """Build a .sng from the karaoke MIDI (lead = the vocal channel), then derive
    the .lrc: read the tempo from the .sng, pick the vocal channel by alignment, and
    emit monotonic timestamps — one line per KAR word."""
    midi = make_karaoke(tmp_path)
    sng = tmp_path / "kar.sng"
    m.build(midi, str(sng), tempo=6, rows_per_pat=64, mode="clean",
            chmap="1,2,-", intro_fill=False, title="T")

    orders, pats = s.read_sng(str(sng))
    assert abs(s.sng_tempo_secs(orders, pats) - 6 / 50) < 1e-9   # tempo 6 -> 0.12 s/row
    onsets = s.vocal_onsets(orders, pats, 1)                     # instr 1 = Lead
    assert onsets, "no vocal onsets in the render"

    syl, chan, div = s.read_midi(midi)
    assert s.pick_vocal_channel(chan, syl, div, len(onsets), None) == 0

    out = tmp_path / "kar.lrc"
    r = subprocess.run([sys.executable, "sng_to_lrc.py", str(sng), midi, str(out),
                        "--title", "T"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    times = []
    for ln in out.read_text().splitlines():
        if ln.startswith("[0"):
            mm, ss = ln[1:].split("]")[0].split(":")
            times.append(int(mm) * 60 + float(ss))
    assert times == sorted(times) and len(times) == 16
