#!/usr/bin/env python3
"""Inspect a MIDI's tracks before mapping it with midi_to_sng.py.

`midi_arrange.py` guesses roles by average pitch — wrong for karaoke/GM files
where the vocal sits mid-stack. This prints the **track names + GM programs**
per channel so you can pick the channel that's literally labelled the melody
(`CANTO`, `Melody`, `Vocal`, or a lead patch like Sax/Flute/Lead).

    python3 midi_inspect.py song.mid              # list tracks (name/program/notes)
    python3 midi_inspect.py song.mid --channel 5  # dump ch5's busiest bar as notes
                                                  #   (confirm it carries the hook)
"""
import argparse
import struct
from collections import Counter

NOTE_NAMES = "C C# D D# E F F# G G# A A# B".split()

# GM melodic program (0-based) -> short name, just the families worth spotting
# when hunting for the lead/vocal voice. Unknown programs print their number.
GM_PROGRAM = {
    0: "Ac.Piano", 1: "Br.Piano", 2: "El.Piano", 4: "El.Piano",
    16: "Organ", 18: "Rock Organ", 19: "Church Organ",
    24: "Nylon Gtr", 25: "Steel Gtr", 27: "Clean Gtr",
    32: "Ac.Bass", 33: "Finger Bass", 35: "Fretless", 38: "Synth Bass",
    39: "Synth Bass", 40: "Violin", 48: "Strings", 49: "Strings",
    50: "Syn.Strings", 52: "Choir", 53: "Voice Oohs", 54: "Synth Voice",
    56: "Trumpet", 57: "Trombone", 58: "Tuba", 61: "Brass",
    64: "Sop.Sax", 65: "Alto Sax", 66: "Tenor Sax", 71: "Clarinet",
    72: "Piccolo", 73: "Flute", 75: "Pan Flute", 78: "Whistle",
    80: "Sq.Lead", 81: "Saw Lead", 82: "Calliope", 87: "Bass+Lead",
}


def _vlq(d, p):
    """Read a variable-length quantity; return (value, new_pos)."""
    v = 0
    while True:
        b = d[p]
        p += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            break
    return v, p


def parse_tracks(path):
    """Return (div, tracks) where each track is a dict with its name, the
    {channel: program} it sets, note count, and per-channel (beat, pitch) notes."""
    with open(path, "rb") as f:
        d = f.read()
    assert d[:4] == b"MThd", "not a MIDI file"
    _, _, div = struct.unpack(">HHH", d[8:14])
    pos = 8 + struct.unpack(">I", d[4:8])[0]
    tracks = []
    while pos < len(d) - 8:
        if d[pos:pos + 4] != b"MTrk":
            pos += 1
            continue
        tlen = struct.unpack(">I", d[pos + 4:pos + 8])[0]
        p, end = pos + 8, pos + 8 + tlen
        run = None
        t = 0
        name = ""
        prog = {}
        notes = {}        # channel -> list[(beat, pitch)]
        while p < end:
            dt, p = _vlq(d, p)
            t += dt
            if p >= end:
                break
            st = d[p]
            if st & 0x80:
                p += 1
                run = st
            else:
                st = run
            hi, ch = st & 0xF0, st & 0x0F
            if st == 0xFF:                       # meta
                mt = d[p]
                p += 1
                mlen, p = _vlq(d, p)
                if mt in (0x01, 0x03, 0x04):     # text / track name / instrument
                    name += d[p:p + mlen].decode("latin1", "ignore") + " "
                p += mlen
            elif st in (0xF0, 0xF7):             # sysex
                slen, p = _vlq(d, p)
                p += slen
            else:
                nd = 1 if hi in (0xC0, 0xD0) else 2
                if hi == 0xC0:
                    prog[ch] = d[p]
                if hi == 0x90 and d[p + 1] > 0:
                    notes.setdefault(ch, []).append((t / div, d[p]))
                p += nd
        nn = sum(len(v) for v in notes.values())
        if name.strip() or notes:
            tracks.append({"name": name.strip(), "prog": prog,
                           "notes": notes, "n": nn})
        pos = end
    return div, tracks


def note_name(pitch):
    return NOTE_NAMES[pitch % 12] + str(pitch // 12 - 1)


def list_tracks(path):
    div, tracks = parse_tracks(path)
    print(f"== {path}  ({div} ticks/quarter, {len(tracks)} tracks) ==")
    for i, tr in enumerate(tracks):
        chans = sorted({c + 1 for c in tr["notes"]})
        progs = ", ".join(f"ch{c + 1}={GM_PROGRAM.get(pr, pr)}"
                          for c, pr in sorted(tr["prog"].items()))
        drums = " [DRUMS]" if 9 in tr["notes"] else ""
        print(f"trk{i:2} ch{chans} n={tr['n']:<5}{drums} "
              f"{progs}  '{tr['name']}'")
    print("\nVocal = the channel labelled Melody/Vocal/CANTO or a lead patch "
          "(Sax/Flute/Lead) — NOT just the highest one.")


def dump_channel(path, ch1):
    """Print the busiest 4-bar block of a 1-based channel as note names, to
    confirm it carries the recognizable hook."""
    div, tracks = parse_tracks(path)
    ch0 = ch1 - 1
    notes = sorted(n for tr in tracks for n in tr["notes"].get(ch0, []))
    if not notes:
        print(f"ch{ch1}: no notes")
        return
    dens = Counter(int(beat // 16) for beat, _ in notes)
    blk = dens.most_common(1)[0][0]
    lo, hi = blk * 16, blk * 16 + 16
    phrase = " ".join(note_name(p) for beat, p in notes if lo <= beat < hi)
    print(f"ch{ch1} busiest block (bars {blk * 4}-{blk * 4 + 4}): {phrase}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("midi", help="the .mid file to inspect")
    ap.add_argument("--channel", type=int, default=None, metavar="N",
                    help="dump 1-based channel N's busiest bar as note names")
    a = ap.parse_args()
    if a.channel is not None:
        dump_channel(a.midi, a.channel)
    else:
        list_tracks(a.midi)


if __name__ == "__main__":
    main()
