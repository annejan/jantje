#!/usr/bin/env python3
"""Parametric MIDI -> SID arranger, stage 1: parse + propose an arrangement.

Reads a multi-channel MIDI (melody / bass / harmony + GM drums on ch10) and
prints a concrete plan: which source channel maps to which SID voice, and how
the GM drum kit maps to SID drum instruments. No audio yet — this is the plan
we then feed to the .sng generator.
"""
import struct, sys
from collections import defaultdict, Counter

GM_DRUMS = {
    35: "kick", 36: "kick", 37: "rim", 38: "snare", 40: "snare",
    39: "clap", 42: "hihat", 44: "hihat", 46: "openhat",
    49: "crash", 51: "ride", 41: "tom", 43: "tom", 45: "tom", 47: "tom", 48: "tom", 50: "tom",
}
NOTE = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
def nm(p): return f"{NOTE[p%12]}{p//12-1}"

def parse(path):
    d = open(path, "rb").read()
    assert d[:4] == b"MThd"
    fmt, ntrks, div = struct.unpack(">HHH", d[8:14])
    pos = 8 + struct.unpack(">I", d[4:8])[0]
    # events[ch] = list of (start_tick, dur_tick, pitch)
    notes = defaultdict(list)
    drumhits = Counter()
    end_tick = 0
    while pos < len(d) - 8:
        if d[pos:pos+4] != b"MTrk":
            pos += 1; continue
        tl = struct.unpack(">I", d[pos+4:pos+8])[0]
        p = pos + 8; end = p + tl; t = 0; run = None
        open_notes = {}  # (ch,pitch) -> start
        while p < end:
            dt = 0
            while True:
                b = d[p]; p += 1; dt = (dt << 7) | (b & 0x7F)
                if not b & 0x80: break
            t += dt
            if p >= end: break
            st = d[p]
            if st & 0x80: p += 1; run = st
            else: st = run
            if st is None: break
            hi, ch = st & 0xF0, st & 0x0F
            if st == 0xFF:
                p += 1; ml = 0
                while True:
                    b = d[p]; p += 1; ml = (ml << 7) | (b & 0x7F)
                    if not b & 0x80: break
                p += ml
            elif st in (0xF0, 0xF7):
                sl = 0
                while True:
                    b = d[p]; p += 1; sl = (sl << 7) | (b & 0x7F)
                    if not b & 0x80: break
                p += sl
            else:
                nd = 1 if hi in (0xC0, 0xD0) else 2
                pit = d[p]; vel = d[p+1] if nd == 2 else 0
                if hi == 0x90 and vel > 0:
                    open_notes[(ch, pit)] = t
                    if ch == 9: drumhits[pit] += 1
                    end_tick = max(end_tick, t)
                elif hi == 0x80 or (hi == 0x90 and vel == 0):
                    s = open_notes.pop((ch, pit), None)
                    if s is not None and ch != 9:
                        notes[ch].append((s, t - s, pit))
                p += nd
        pos = end
    return div, end_tick, notes, drumhits

def main(path):
    div, end_tick, notes, drums = parse(path)
    bars = end_tick / div / 4
    print(f"== {path.split('/')[-1]} :  {bars:.0f} bars, {div} ticks/quarter ==\n")
    # melodic channels: role by pitch range + density
    rows = []
    for ch, ns in notes.items():
        if not ns: continue
        pits = [n[2] for n in ns]
        rows.append((sum(pits)/len(pits), ch, min(pits), max(pits), len(ns)))
    rows.sort()
    print("Pitched source channels (low avg pitch -> high):")
    for avg, ch, lo, hi, n in rows:
        print(f"  ch{ch+1:2d}: {nm(lo)}..{nm(hi)}  {n:4d} notes  (avg {nm(int(avg))})")
    # propose roles
    if rows:
        bass = rows[0][1]
        lead = rows[-1][1]
        mids = [r[1] for r in rows[1:-1]]
        print(f"\nProposed melodic roles:")
        print(f"  BASS    <- ch{bass+1}")
        print(f"  LEAD    <- ch{lead+1}")
        if mids:
            print(f"  HARMONY <- ch{mids[len(mids)//2]+1}  (pick 1 of {[m+1 for m in mids]})")
    print(f"\nGM drum kit on ch10 ({sum(drums.values())} hits):")
    kit = Counter()
    for note, c in drums.items():
        kit[GM_DRUMS.get(note, f"perc{note}")] += c
    for name, c in kit.most_common():
        print(f"  {name:8s}: {c:4d} hits")
    print(f"\n-> SID drum map: kick=triangle pitch-drop, snare/clap=noise burst, "
          f"hihat/openhat=short noise")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else "/home/annejan/Projects/martin/assets/Village People In The Navy.mid")
