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


def make_solo(div=96, bars=8, active=None, ch=0, pitch=72, name="Solo"):
    """A 1-track SMF holding ONE isolated melodic part (the clean-stem shape:
    load_stem merges a file's channels, so a stem must be a single part). `active`
    = set of bar indices that play (None = every bar); skipped bars leave a rest
    hole. Used to build a lead with a deliberate multi-bar hole + a dense hook."""
    q = div
    ev = []
    dt = 0                                       # carries delta across rested bars
    for bar in range(bars):
        for beat in range(4):
            if active is None or bar in active:
                ev.append((dt, 0x90 | ch, pitch + (beat % 3), 100))
                ev.append((q // 2, 0x80 | ch, pitch + (beat % 3), 0))
                dt = q // 2
            else:
                dt += q                          # rest this beat
    hdr = b"MThd" + struct.pack(">IHHH", 6, 1, 1, div)
    return hdr + _track(ev, name=name, ch=ch)


def _chord_stem(div=96, bars=8, root=60):
    """A 1-track SMF holding a sustained triad (root/+4/+7) for the whole song —
    a real chord, to exercise --arp-fill (3 simultaneous notes per row)."""
    body = bytearray()
    for off in (0, 4, 7):                       # all three note-ons at t=0
        body += _vlq(0) + bytes([0x90, root + off, 100])
    span = bars * 4 * div
    for i, off in enumerate((0, 4, 7)):         # note-offs at the end
        body += _vlq(span if i == 0 else 0) + bytes([0x80, root + off, 0])
    body += _vlq(0) + b"\xff\x2f\x00"
    return (b"MThd" + struct.pack(">IHHH", 6, 0, 1, div)
            + b"MTrk" + struct.pack(">I", len(body)) + bytes(body))


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


def test_build_stem_fill_from_file(tmp_path):
    """--fill accepts a stem FILE, not just a channel: it's loaded, rescaled
    onto this build's 16th grid (here 96 vs 240 tpq), and the rescaled notes
    are placed into the lead's rest holes — the na_na_hook-into-vocal-gaps path.

    The lead rests bars 1-6 (a 6-bar hole >> the half-bar MIN_GAP), so the hook
    actually lands notes there; we assert the .sng changes vs the no-fill build
    (filled == 0 would leave it byte-identical and silently pass)."""
    lead = tmp_path / "lead.mid"
    lead.write_bytes(make_solo(active={0, 7}))        # 96 tpq, isolated, bars 1-6 rest
    bass = tmp_path / "bass.mid"
    bass.write_bytes(make_solo(ch=1, pitch=40))       # full, low
    hook = tmp_path / "hook.mid"
    hook.write_bytes(make_solo(div=240, pitch=60))    # different tpq -> exercises rescale
    stems = {"lead": str(lead), "bass": str(bass)}

    nofill = tmp_path / "nofill.sng"
    m.build(None, str(nofill), tempo=6, rows_per_pat=64, mode="shared",
            stems=stems, title="T")
    out = tmp_path / "stemfill.sng"
    m.build(None, str(out), tempo=6, rows_per_pat=64, mode="shared",
            fill=[str(hook)], stems=stems, title="T")
    _assert_valid_sng(out)
    assert out.read_bytes() != nofill.read_bytes(), \
        "stem --fill placed no notes (the rescaled hook never reached the grid)"


def test_build_arp_fill_chord(tmp_path):
    """--arp-fill cycles a chord's real tones across the fill rows. Build a lead
    with a long hole + a 3-note chord source, and assert the arp'd fill places
    more notes than the held-single-note version (it emits a tone per row)."""
    # lead: only bar 0, then a long rest (so the fill fires in bars 1-7)
    lead = tmp_path / "lead.mid"
    lead.write_bytes(make_solo(active={0}))
    bass = tmp_path / "bass.mid"
    bass.write_bytes(make_solo(ch=1, pitch=40))
    # a chord stem: three sustained notes (a triad) held across the whole song
    chord = tmp_path / "chord.mid"
    chord.write_bytes(_chord_stem())
    stems = {"lead": str(lead), "bass": str(bass)}

    held = tmp_path / "held.sng"
    m.build(None, str(held), tempo=6, rows_per_pat=64, mode="shared",
            fill=[str(chord)], stems=stems, title="T", arp_fill=False)
    arped = tmp_path / "arped.sng"
    m.build(None, str(arped), tempo=6, rows_per_pat=64, mode="shared",
            fill=[str(chord)], stems=stems, title="T", arp_fill=True)
    _assert_valid_sng(held)
    _assert_valid_sng(arped)
    assert arped.read_bytes() != held.read_bytes(), "arp-fill changed nothing on a chord"


def _roll_midi(div=96):
    """A lead + bass + a 16-step 16th-note snare roll on ch10 (>=8 consecutive ->
    triggers the smooth gliding-riser path)."""
    lead, bass, drums = [], [], []
    for bar in range(4):
        base = bar * 4 * div
        for beat in range(4):
            t = base + beat * div
            lead.append((div // 2 if t else 0, 0x90, 72, 100))
            lead.append((div // 2, 0x80, 72, 0))
            bass.append((div // 2 if t else 0, 0x91, 36, 100))
            bass.append((div // 2, 0x81, 36, 0))
    for i in range(16):                              # a one-bar 16th-note snare roll
        drums.append((0 if i == 0 else div // 4, 0x99, 38, 100))
        drums.append((div // 4, 0x89, 38, 0))
    hdr = b"MThd" + struct.pack(">IHHH", 6, 1, 3, div)
    return (hdr + _track(lead, name="Melody", ch=0) + _track(bass, name="Bass", ch=1)
            + _track(drums, name="Drums", ch=9))


def _bend_midi(div=96):
    """A 1-track lead (ch1): one held note with a MIDI pitch-bend UP (~+2 st)
    halfway through — to drive the --bends -> portamento path."""
    body = bytearray()
    body += _vlq(div) + bytes([0x90, 60, 100])           # note on C4 (NOT row 0 —
    #                                                      row 0/ch 0 is the tempo Fxx)
    body += _vlq(div) + bytes([0xE0, 0x00, 0x7F])        # pitch bend ~+2 semitones
    body += _vlq(div) + bytes([0x80, 60, 0])             # note off
    body += _vlq(0) + b"\xff\x2f\x00"
    return (b"MThd" + struct.pack(">IHHH", 6, 0, 1, div)
            + b"MTrk" + struct.pack(">I", len(body)) + bytes(body))


def test_parse_bends_and_portamento(tmp_path):
    """parse_bends reads 0xE0 events; --bends turns a lead note's bend into a
    portamento command, so the .sng differs from the no-bends build."""
    p = tmp_path / "bend.mid"
    p.write_bytes(_bend_midi())
    b = m.parse_bends(str(p))
    assert 0 in b and any(abs(v) > 1.0 for _, v in b[0]), "bend not parsed"
    plain = tmp_path / "plain.sng"
    m.build(str(p), str(plain), tempo=6, rows_per_pat=64, mode="clean",
            chmap="1,-,-", title="T")
    bent = tmp_path / "bent.sng"
    m.build(str(p), str(bent), tempo=6, rows_per_pat=64, mode="clean",
            chmap="1,-,-", title="T", bends=b)
    _assert_valid_sng(bent)
    assert bent.read_bytes() != plain.read_bytes(), "bends changed nothing"


def test_build_riser_smooth(tmp_path):
    """A long snare roll becomes ONE gliding riser note + a portamento-up command,
    not N re-triggered notes. Drive the path and assert a well-formed .sng."""
    p = tmp_path / "roll.mid"
    p.write_bytes(_roll_midi())
    out = tmp_path / "riser.sng"
    m.build(str(p), str(out), tempo=6, rows_per_pat=64,
            mode="clean", chmap="1,2,-", title="T")
    _assert_valid_sng(out)


def test_build_no_intro_fill(midi_file, tmp_path):
    """--no-intro-fill (intro_fill=False) skips tiling the bass riff into a thin
    intro — used when the source has a deliberate sparse build before the drop."""
    out = tmp_path / "nointro.sng"
    m.build(midi_file, str(out), tempo=6, rows_per_pat=64,
            mode="clean", chmap="1,2,-", intro_fill=False, title="T")
    _assert_valid_sng(out)


@pytest.mark.parametrize("preset", ["darude", "darude-build"])
def test_build_arranged_presets(midi_file, tmp_path, preset):
    out = tmp_path / f"{preset}.sng"
    m.build_arranged(midi_file, str(out), tempo=6, rows_per_pat=64,
                     sections=m.parse_arrange(preset), chmap="1,2,-",
                     four_floor=True, title="T")
    _assert_valid_sng(out)


def test_parse_tempo_map():
    assert m.parse_tempo_map("0:07,24:05,48:04") == [(0, 7), (24, 5), (48, 4)]


def test_build_tempo_map_journey(midi_file, tmp_path):
    """--tempo-map drops CMD_SETTEMPO at bar boundaries -> a genre journey in one
    song; the .sng must differ from the flat-tempo build and stay well-formed."""
    flat = tmp_path / "flat.sng"
    m.build(midi_file, str(flat), tempo=6, rows_per_pat=64, mode="clean",
            chmap="1,2,-", title="T")
    journey = tmp_path / "journey.sng"
    m.build(midi_file, str(journey), tempo=7, rows_per_pat=64, mode="clean",
            chmap="1,2,-", title="T", tempo_map=[(0, 7), (4, 5), (6, 4)])
    _assert_valid_sng(journey)
    assert journey.read_bytes() != flat.read_bytes()


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


def test_gm_drum_maps_aux_percussion_without_drowning_the_groove():
    """Aux percussion (tambourine 54, shaker 82, …) must route to a SID drum so
    the groove isn't dropped — without the two failure modes the build's priority
    model creates: a 'crash' wall-of-swells, and 'tom' deleting the hat groove."""
    # every value must be a drum the full-kit paths (build/build_stereo) know,
    # else `name not in drumdef` silently drops it
    known = {"kick", "snare", "clap", "rim", "hihat", "openhat", "ride", "tom", "crash"}
    assert set(m.GM_DRUM.values()) <= known, "GM_DRUM maps to an unknown drum name"
    assert m.GM_DRUM[54] == "hihat" and m.GM_DRUM[82] == "hihat"   # tambourine/shaker offbeat
    # splash 55 + crash2 57 are open accents, NOT crash: crash (prio 6) wins its
    # row and fires a multi-row swell, so dozens of them = a wall of noise.
    assert m.GM_DRUM[55] == "openhat" and m.GM_DRUM[57] == "openhat"
    assert 49 in m.GM_DRUM and m.GM_DRUM[49] == "crash"            # only the real crash swells
    # the hand-drum family is left UNMAPPED on purpose: tom (prio 3) outranks
    # hihat (prio 2), so congas-in-unison-with-hats would delete the offbeat groove.
    for n in (*range(60, 67), 76, 77):
        assert n not in m.GM_DRUM, f"GM {n} (hand drum) would route to tom and outrank the hats"


def test_note_byte_clamps_into_sid_range():
    for midi_pitch in (0, 24, 60, 96, 127):
        b = m.note_byte(midi_pitch)
        assert m.FIRSTNOTE <= b <= m.LASTNOTE
