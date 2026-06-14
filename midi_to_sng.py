#!/usr/bin/env python3
"""Parametric MIDI -> GoatTracker .sng arranger (v0).

Takes a multi-channel MIDI (melody/bass/harmony + GM drums on ch10) and writes
a GoatTracker .sng directly: melodic voices placed on a 16th-note tracker grid,
GM drums translated to SID noise/triangle drum instruments. Dual-SID (6 ch) by
default: ~3 melodic + ~3 drum voices. No ChiptuneSAK, no MIDI round-trip.

Usage: midi_to_sng.py <in.mid> <out.sng> [--tempo N] [--rows-per-pat N]
"""
import struct, argparse
from collections import defaultdict, Counter

# --- GoatTracker constants (src/gcommon.h) ---
FIRSTNOTE, LASTNOTE, REST, KEYOFF, KEYON, ENDPATT = 0x60, 0xBC, 0xBD, 0xBE, 0xBF, 0xFF
GT_LO, GT_HI = 24, 24 + (LASTNOTE - FIRSTNOTE)   # MIDI range that fits the note byte
MAX_PATTROWS = 128

GM_DRUM = {35:"kick",36:"kick",37:"rim",38:"snare",40:"snare",39:"clap",
           42:"hihat",44:"hihat",46:"openhat",49:"crash",51:"ride",
           41:"tom",43:"tom",45:"tom",47:"tom",48:"tom",50:"tom"}

# ---------------------------------------------------------------------------
def parse_midi(path):
    with open(path, "rb") as f:
        d = f.read()
    assert d[:4] == b"MThd"
    _, ntrks, div = struct.unpack(">HHH", d[8:14])
    pos = 8 + struct.unpack(">I", d[4:8])[0]
    notes = defaultdict(list)      # ch -> (start, dur, pitch)
    drums = []                     # (start, gm_note)
    end_tick = 0
    while pos < len(d) - 8:
        if d[pos:pos+4] != b"MTrk":
            pos += 1; continue
        tl = struct.unpack(">I", d[pos+4:pos+8])[0]
        p = pos + 8; end = p + tl; t = 0; run = None; opened = {}
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
                    if ch == 9:
                        drums.append((t, pit))
                    else:
                        opened[(ch, pit)] = t
                    end_tick = max(end_tick, t)
                elif hi == 0x80 or (hi == 0x90 and vel == 0):
                    s = opened.pop((ch, pit), None)
                    if s is not None:
                        notes[ch].append((s, t - s, pit))
                p += nd
        pos = end
    return div, end_tick, notes, drums

def clamp_oct(midi):
    while midi < GT_LO: midi += 12
    while midi > GT_HI: midi -= 12
    return midi

def note_byte(midi):
    return FIRSTNOTE + (clamp_oct(midi) - GT_LO)

# ---------------------------------------------------------------------------
def load_stem(path):
    """A named stem (one isolated part per file). Merge its melodic channels
    into one note list; keep its drums separately."""
    div, end_tick, notes, drums = parse_midi(path)
    melodic = sorted(n for lst in notes.values() for n in lst)
    return div, end_tick, melodic, drums


def build(path, out, tempo, rows_per_pat, hihat_div=2, mode="shared", chmap=None,
          kick_bass=False, fill=None, stems=None, title="In The Navy"):
    if stems:
        # Build from deliberately-chosen named stem files (one part each, all on
        # the same aligned grid) instead of guessing channels in a combined MIDI.
        div = None; end_tick = 0; notes = {}; drums = []
        for idx, role in ((0, "lead"), (1, "bass"), (2, "harm")):
            if stems.get(role):
                d, et, mel, _ = load_stem(stems[role])
                div = div or d; end_tick = max(end_tick, et); notes[idx] = mel
        if stems.get("drums"):
            d, et, _, dr = load_stem(stems["drums"])
            div = div or d; end_tick = max(end_tick, et); drums = dr
        lead_ch = 0 if "lead" in stems else None
        bass_ch = 1 if "bass" in stems else None
        harm_ch = 2 if "harm" in stems else None
    else:
        div, end_tick, notes, drums = parse_midi(path)
        if chmap:
            # explicit LEAD,BASS,HARM as 1-based MIDI channels (as printed); '-' skips
            def pick(tok):
                tok = tok.strip()
                return None if tok in ("", "-") else int(tok) - 1
            parts = (chmap.split(",") + ["-", "-", "-"])[:3]
            lead_ch, bass_ch, harm_ch = (pick(p) for p in parts)
        else:
            # choose melodic voices by average pitch
            ranked = sorted(((sum(n[2] for n in ns)/len(ns), ch) for ch, ns in notes.items() if ns))
            bass_ch = ranked[0][1]
            lead_ch = ranked[-1][1]
            mids = [c for _, c in ranked[1:-1]]
            harm_ch = mids[len(mids)//2] if mids else None

    tpr = div / 4.0                      # ticks per 16th note (one tracker row)
    total_rows = int(end_tick / tpr) + 8
    print(f"{(path or 'stems').split('/')[-1]}: {end_tick/div/4:.0f} bars -> {total_rows} rows "
          f"(16th grid), {sum(len(v) for v in notes.values())} mel notes, {len(drums)} drum hits")
    print(f"  lead=ch{lead_ch+1 if lead_ch is not None else '-'} "
          f"bass=ch{bass_ch+1 if bass_ch is not None else '-'} "
          f"harmony=ch{harm_ch+1 if harm_ch is not None else '-'}")

    # Authentic 3-channel mono SID: 0 lead, 1 bass, 2 drums.
    # Instruments: 1 Lead 2 Bass 3 (unused harmony) 4 Kick 5 Snare 6 Hihat 7 Tom.
    NCH = 3
    grid = [[(REST, 0) for _ in range(total_rows)] for _ in range(NCH)]  # (note, instr)

    def place_voice(ch_notes, sidch, instr):
        ev = sorted(ch_notes)
        for i, (start, dur, pit) in enumerate(ev):
            r = int(round(start / tpr))
            if not (0 <= r < total_rows):
                continue
            grid[sidch][r] = (note_byte(pit), instr)
            # gate-off at the note's end when a rest follows (otherwise the
            # next note simply retriggers = legato). Gives real note lengths.
            endr = r + max(1, int(round(dur / tpr)))
            nxt = int(round(ev[i+1][0] / tpr)) if i + 1 < len(ev) else total_rows
            if r < endr < nxt < total_rows + 1 and endr < total_rows \
                    and grid[sidch][endr][0] == REST:
                grid[sidch][endr] = (KEYOFF, 0)

    if mode == "shared":
        # lead | bass | harmony+drums : the bass keeps its own channel so it
        # stays solid, and drums punch through the *sparser* harmony so they're
        # audible the whole song. (Sharing the busy bass channel cut the drums
        # off after the intro — kick/snare were retriggered away by the bass.)
        if lead_ch is not None: place_voice(notes[lead_ch], 0, 1)
        if bass_ch is not None: place_voice(notes[bass_ch], 1, 2)
        if harm_ch is not None: place_voice(notes[harm_ch], 2, 3)
        drum_ch, drums_on_rest_only = 2, True
    else:
        # clean: lead | bass | drums (each channel one role)
        if lead_ch is not None: place_voice(notes[lead_ch], 0, 1)
        if bass_ch is not None: place_voice(notes[bass_ch], 1, 2)
        drum_ch, drums_on_rest_only = 2, False

    # ----- fill the lead's gaps with a soft counter-melody -----
    # We only use a few of the source's parts, so where the lead (vocal) rests
    # there's a hole. Drop another part (e.g. the piano comp) into the lead
    # channel's REST rows on a quiet instrument so it fills the air without
    # stepping on the vocal.
    if fill:
        # Counter-melody only in the lead's *real holes* (instrumental sections
        # where the vocal rests for a stretch) — NOT every little inter-note gap,
        # which would just cram a second part on top of the vocal. Different
        # holes want different parts (e.g. the "na na" saw hook vs the piano
        # comp), so `fill` is a PRIORITY POOL of channels: at each row take the
        # pitch of the first listed part that's sounding.
        MIN_GAP = 8                                # only gaps >= half a bar
        act = [None] * total_rows
        for src in reversed(fill):                 # first listed wins -> overwrite last
            for start, dur, pit in sorted(notes.get(src, [])):
                r0 = int(round(start / tpr))
                r1 = min(total_rows, r0 + max(1, int(round(dur / tpr))))
                for r in range(max(0, r0), r1):
                    act[r] = pit
        filled = 0; r = 0
        while r < total_rows:
            if grid[0][r][0] != REST:
                r += 1; continue
            j = r
            while j < total_rows and grid[0][j][0] == REST:
                j += 1
            if j - r >= MIN_GAP:
                prev = None
                for k in range(r, j):
                    if act[k] is not None:
                        if act[k] != prev:
                            grid[0][k] = (note_byte(act[k]), 9); filled += 1
                        prev = act[k]
                    elif prev is not None:
                        grid[0][k] = (KEYOFF, 0); prev = None
            r = j
        print(f"  fill: {filled} counter-melody notes from "
              f"ch{','.join(str(c+1) for c in fill)} into lead holes")

    # ----- fatten a thin intro (BEFORE drums, so the kick punches through) -----
    # The famous hook plays for a long stretch before the real bass enters
    # (here: bar 30). Until then, lay the harmony riff an octave down onto the
    # bass channel so the whole intro has a driving bass-register line; the
    # four-on-the-floor kick is placed afterwards and blips through it (with
    # resume), giving riff + kick together. Hands off when the real bass enters.
    if bass_ch is not None and harm_ch is not None:
        def first_row(ch):
            return min((int(round(s / tpr)) for s, _, _ in notes[ch]), default=0)
        intro_end = first_row(bass_ch)
        if intro_end > 8:
            # Lay the harmony stabs an octave down as proper NOTES (with a
            # keyoff at each note's end) — they ring with the bass's release
            # tail and then stop, instead of one held drone that sounds nothing
            # like the real bass riff that follows. (Sparser, but clean; filling
            # the breakdown-y holes is a separate TODO.)
            doubled = 0
            for start, dur, pit in sorted(notes[harm_ch]):
                r = int(round(start / tpr))
                if 0 <= r < intro_end and grid[1][r][0] == REST:
                    grid[1][r] = (note_byte(pit - 12), 2); doubled += 1
                    endr = r + max(1, int(round(dur / tpr)))
                    if endr < intro_end and grid[1][endr][0] == REST:
                        grid[1][endr] = (KEYOFF, 0)
            print(f"  intro: bass riff = {doubled} notes (harmony oct down) "
                  f"on the bass channel, rows 0..{intro_end}")

    # Only one drum can sound per row, so pick the
    # highest-priority hit (kick > snare/clap > hihat > tom) — the classic SID
    # single-channel drum track.
    drumdef = {  # name -> (instr, note_byte, priority)
        "kick":    (4, note_byte(36), 5),
        "snare":   (5, note_byte(60), 4),
        "clap":    (5, note_byte(60), 4),
        "rim":     (5, note_byte(60), 4),
        "hihat":   (6, note_byte(72), 2),
        "openhat": (6, note_byte(74), 2),
        "ride":    (6, note_byte(72), 2),
        "tom":     (7, note_byte(48), 3),
        "crash":   (8, note_byte(72), 6),   # SWELL: slow noise + filter sweep, wins its row
    }
    best = {}  # row -> (priority, instr, note_byte)
    for start, gm in drums:
        name = GM_DRUM.get(gm)
        if name not in drumdef: continue
        instr, nb, prio = drumdef[name]
        r = int(round(start / tpr))
        if not (0 <= r < total_rows): continue
        if r not in best or prio > best[r][0]:
            best[r] = (prio, instr, nb)

    # Long snare/clap rolls (eurodance pre-drop buildups) become a wall of
    # identical C-3 noise — machine-gun. Turn any run of >=8 near-consecutive
    # snares into a RISING noise riser (the note climbs over the run) so it
    # reads as a proper buildup instead.
    snare_rows = sorted(r for r, (p, i, nb) in best.items() if i == 5)
    runs, cur = [], []
    for r in snare_rows:
        if cur and r - cur[-1] > 2:
            runs.append(cur); cur = []
        cur.append(r)
    if cur: runs.append(cur)
    rolls = 0
    for run in runs:
        if len(run) >= 8:
            rolls += 1
            for k, r in enumerate(run):
                pit = 40 + int(48 * k / (len(run) - 1))   # climb ~4 octaves
                best[r] = (best[r][0], 5, note_byte(pit))
    if rolls:
        print(f"  rolls: {rolls} snare buildup(s) turned into rising noise risers")

    def place_drums(chan, rows):
        # Place the given row->(prio,instr,nb) drums on a melodic channel with
        # the "drum blip, note resumes" trick: a kick/snare that punches through
        # a melodic note re-asserts it on the next row so the voice keeps going.
        active = []
        cur = (REST, 0)
        for r in range(total_rows):
            n, ci = grid[chan][r]
            if n == KEYOFF: cur = (REST, 0)
            elif n != REST: cur = (n, ci)
            active.append(cur)
        cnt = Counter()
        swell_until = -1
        for r in sorted(rows):
            prio, instr, nb = rows[r]
            if instr == 6 and (r % hihat_div) != 0:    # thin busy hihats
                continue
            if instr == 6 and r <= swell_until:        # don't clip a ringing swell
                continue
            had_note = grid[chan][r][0] not in (REST, KEYOFF)
            if drums_on_rest_only and instr in (6, 7) and had_note:
                continue            # hihat/tom fill rests; kick+snare punch through
            grid[chan][r] = (nb, instr)
            cnt[instr] += 1
            if instr == 8:                             # swell: let it ring, no resume
                swell_until = r + 5
                continue
            if drums_on_rest_only and had_note and r + 1 < total_rows \
                    and grid[chan][r + 1][0] == REST and active[r][0] != REST:
                grid[chan][r + 1] = active[r]          # resume the note after the blip
        return cnt

    if kick_bass and bass_ch is not None:
        # Split the kit: the four-on-the-floor KICK goes on the bass channel
        # (fills its empty stretches + thickens the low end), snare/hat/tom stay
        # with the organ stab on the harmony channel. Distributes the kit over
        # two voices instead of crowding one.
        kick_rows  = {r: v for r, v in best.items() if v[1] == 4}
        other_rows = {r: v for r, v in best.items() if v[1] != 4}
        placed = place_drums(1, kick_rows) + place_drums(drum_ch, other_rows)
        print(f"  drums split: kick on ch2 (bass), snare/hat on ch3 — "
              f"kick={placed[4]} snare={placed[5]} hihat={placed[6]} tom={placed[7]}")
    else:
        placed = place_drums(drum_ch, best)
        print(f"  drums on ch3: {sum(placed.values())} hits "
              f"(kick={placed[4]} snare={placed[5]} hihat={placed[6]} tom={placed[7]}, "
              f"hihat/{hihat_div})")

    serialize_sng(out, title, tempo, grid, rows_per_pat)


# ---------------------------------------------------------------------------
# Arranger: stage a flat source loop into intro -> build -> drop -> full ...
#
# Some source MIDIs are a single bar-aligned loop with every part playing from
# bar 0 (e.g. cprato's Sandstorm: lead+bass+drums all on from the downbeat). As
# one pass that has no tension — the climax is the start, then it just repeats.
# Real eurodance/EDM develops by *revealing layers*. So instead of one pass we
# tile the loop into named sections, each exposing a subset of the four layers
# (k=kick, h=hat/snare, b=bass, l=lead), with an optional rising-noise riser on
# a section's last bar to lead into the next.
PRESETS = {
    #          bars:layers   (r in layers = riser on the last bar)
    # High-energy: the bass + drums pump from bar 0 (keeps the source loop's
    # drive), the LEAD is the only thing teased — held out for an 8-bar groove,
    # dropped in, then pulled for one 8-bar break before slamming back. Lead is
    # absent only ~20% of the song; everything else is full.
    "darude": "8:khbr,16:khbl,16:khbl,8:khbr,16:khbl,16:khbl",
    # Gentle reveal: near-silent kick-only intro that layers up slowly. Less
    # energy, more obvious "build" — use when the loop is meant to start sparse.
    "darude-build": "8:k,8:khr,8:khb,16:khbl,16:khbl,8:khr,16:khbl",
}

def parse_arrange(spec):
    """'8:k,8:khr,...' -> [(bars, layerset, riser_tail), ...]."""
    spec = PRESETS.get(spec, spec)
    out = []
    for tok in spec.split(","):
        bars_s, layers = tok.split(":")
        out.append((int(bars_s),
                    set(c for c in layers if c in "khbl"),
                    "r" in layers))
    return out

def build_arranged(path, out, tempo, rows_per_pat, sections,
                   hihat_div=2, chmap=None, title="Arranged", four_floor=False):
    div, end_tick, notes, drums = parse_midi(path)
    if chmap:
        def pick(tok):
            tok = tok.strip()
            return None if tok in ("", "-") else int(tok) - 1
        parts = (chmap.split(",") + ["-", "-", "-"])[:3]
        lead_ch, bass_ch, _ = (pick(p) for p in parts)
    else:
        ranked = sorted((sum(n[2] for n in ns)/len(ns), ch)
                        for ch, ns in notes.items() if ns)
        bass_ch, lead_ch = ranked[0][1], ranked[-1][1]

    tpr = div / 4.0
    ROWS_PER_BAR = 16
    base_bars = max(1, -(-end_tick // (div * 4)))     # ceil to whole bars
    base_rows = base_bars * ROWS_PER_BAR

    # ---- the four separable source layers, one bar-aligned base loop each ----
    def layer(ch_notes, instr):
        g = [(REST, 0)] * base_rows
        ev = sorted(ch_notes)
        for i, (start, dur, pit) in enumerate(ev):
            r = int(round(start / tpr))
            if not (0 <= r < base_rows): continue
            g[r] = (note_byte(pit), instr)
            endr = r + max(1, int(round(dur / tpr)))
            nxt = int(round(ev[i+1][0] / tpr)) if i+1 < len(ev) else base_rows
            if r < endr < nxt and endr < base_rows and g[endr][0] == REST:
                g[endr] = (KEYOFF, 0)
        return g

    gL = layer(notes[lead_ch], 1) if lead_ch is not None else [(REST, 0)] * base_rows
    gB = layer(notes[bass_ch], 2) if bass_ch is not None else [(REST, 0)] * base_rows

    # one drum per row (kick > snare/clap > hat > tom), reusing the main map
    drumdef = {"kick": (4, note_byte(36), 5), "snare": (5, note_byte(60), 4),
               "clap": (5, note_byte(60), 4), "rim": (5, note_byte(60), 4),
               "hihat": (6, note_byte(72), 2), "openhat": (6, note_byte(74), 2),
               "ride": (6, note_byte(72), 2), "tom": (7, note_byte(48), 3)}
    best = {}
    for start, gm in drums:
        name = GM_DRUM.get(gm)
        if name not in drumdef: continue
        instr, nb, prio = drumdef[name]
        r = int(round(start / tpr))
        if 0 <= r < base_rows and (r not in best or prio > best[r][0]):
            best[r] = (prio, instr, nb)
    gK = [(REST, 0)] * base_rows                      # kick layer
    gP = [(REST, 0)] * base_rows                      # snare/hat/tom layer
    if four_floor:
        # The source kit is too sparse for a dance floor (here 16 bars hold
        # ~16 hats). Ignore it and lay down a canonical house groove on the
        # 16-row bar: kick on every beat (0,4,8,12), clap on 2 & 4 (4,12),
        # open hat on every offbeat 8th, closed hat on the down 8ths.
        KICK, CLAP = note_byte(36), note_byte(60)
        OPENH, CLOSEDH = note_byte(74), note_byte(72)
        for r in range(base_rows):
            br = r % ROWS_PER_BAR
            if br % 4 == 0:
                gK[r] = (KICK, 4)
            if br in (4, 12):
                gP[r] = (CLAP, 5)
            elif br % 2 == 0:
                gP[r] = (CLOSEDH if br % 4 == 0 else OPENH, 6)
    else:
        for r, (_prio, instr, nb) in best.items():
            if instr == 4:
                gK[r] = (nb, 4)
            elif not (instr == 6 and r % hihat_div):  # thin busy hihats
                gP[r] = (nb, instr)

    def riser_bar(seg, lo):                           # climbing noise -> a build
        for k in range(ROWS_PER_BAR):
            seg[lo + k] = (note_byte(40 + int(48 * k / (ROWS_PER_BAR - 1))), 5)

    # ---- tile the sections into the final 3-channel grid ----------------------
    out0, out1, out2 = [], [], []
    for bars, layers, riser_tail in sections:
        n = bars * ROWS_PER_BAR
        s0 = [gL[r % base_rows] if "l" in layers else (REST, 0) for r in range(n)]
        s1 = [gB[r % base_rows] if "b" in layers else (REST, 0) for r in range(n)]
        s2 = [gP[r % base_rows] if "h" in layers else (REST, 0) for r in range(n)]
        if "k" in layers:                             # kick onto the bass channel
            active = []                               # with the blip-then-resume trick
            cur = (REST, 0)
            for n0, ci in s1:
                if n0 == KEYOFF: cur = (REST, 0)
                elif n0 != REST: cur = (n0, ci)
                active.append(cur)
            for r in range(n):
                k = gK[r % base_rows]
                if k[0] == REST: continue
                had = s1[r][0] not in (REST, KEYOFF)
                s1[r] = k
                if had and r+1 < n and s1[r+1][0] == REST and active[r][0] != REST:
                    s1[r+1] = active[r]
        if riser_tail:
            riser_bar(s2, n - ROWS_PER_BAR)
        out0 += s0; out1 += s1; out2 += s2

    total = len(out0)
    print(f"{(path or 'src').split('/')[-1]}: {base_bars}-bar loop -> "
          f"{len(sections)} sections, {total} rows ({total//ROWS_PER_BAR} bars)")
    print("  lead=ch{} bass=ch{}  layers per section: {}".format(
        lead_ch+1 if lead_ch is not None else "-",
        bass_ch+1 if bass_ch is not None else "-",
        " ".join("".join(sorted(ly)) or "-" for _, ly, _ in sections)))
    serialize_sng(out, title, tempo, [out0, out1, out2], rows_per_pat)


def serialize_sng(out, title, tempo, grid, rows_per_pat):
    """Write the grid (3 or 6 channels) + the shared instrument/table bank to a
    GTS5 .sng. 6 channels auto-load as dual-SID stereo in the editor."""
    NCH = len(grid)
    total_rows = len(grid[0])
    # ----- patterns + orderlists -----
    P = rows_per_pat
    npat_per = (total_rows + P - 1) // P
    patterns = []                          # flat list of pattern row-bytes
    order = [[] for _ in range(NCH)]       # per channel list of pattern numbers
    pidx = 0
    for ch in range(NCH):
        for pi in range(npat_per):
            rows = bytearray()
            for i in range(P):
                r = pi * P + i
                note, instr = grid[ch][r] if r < total_rows else (REST, 0)
                cmd, param = (0xF, tempo) if (ch == 0 and r == 0) else (0, 0)
                rows += bytes([note, instr, cmd, param])
            rows += bytes([ENDPATT, 0, 0, 0])      # endmark row
            patterns.append(rows)
            order[ch].append(pidx)
            pidx += 1

    # ----- instruments + tables -----
    bass_sid = 1                                   # bass is on SID voice 2 (index 1)
    # WAVE table (1-based steps):
    #  1 saw,2 stop | 3 tri,4 stop | 5 noise,6 stop | 7 pulse,8 stop
    #  9-12 saw arp (root,+7,+12 loop) | 13-16 kick (tri pitch-drop +12->0)
    wt_l = [0x21,0xFF, 0x11,0xFF, 0x81,0xFF, 0x41,0xFF,
            0x21,0x00,0x00,0xFF, 0x11,0x00,0x00,0xFF]
    wt_r = [0x00,0x00, 0x00,0x00, 0x00,0x00, 0x00,0x00,
            0x00,0x07,0x0C,0x09, 0x0C,0x06,0x00,0x00]
    # PULSE table: 50% then sweep up/down forever (available for pulse leads)
    pt_l = [0x88, 0x60, 0x60, 0xFF]
    pt_r = [0x00, 0x04, 0xFC, 0x02]
    # FILTER table: two programs.
    #  steps 1-5 (ftbl=1): AUTO-WAH low-pass on the bass voice — start fairly
    #    open ($70) and loop a slow up/down cutoff sweep ($70..$D0). Retriggers
    #    per note, so every bass note gets a little "wow" instead of a static
    #    tone. Stays high enough to remain clearly audible.
    #  steps 6-10 (ftbl=6): NOISE SWELL on the harmony/drum voice (voice 3) — set
    #    a low cutoff, ramp it up (L=ticks, R=+cutoff/tick) so the noise opens
    #    up, then clear the routing so it lets go of voice 3.
    swell_sid = 2                                  # harmony/drum channel = SID voice 3
    ft_l = [0x90, 0x00, 0x30, 0x30, 0xFF,
            0x90, 0x00, 0x20, 0x90, 0xFF]
    ft_r = [0x40 | (1 << bass_sid), 0x70, 0x02, 0xFE, 0x03,  # res $4 + route, cutoff $70, +2/tick, -2/tick, loop to sweep-up
            0x40 | (1 << swell_sid), 0x10, 0x07,   # res $4 + route v3, cutoff $10 -> +7/tick
            0x00, 0x00]                            # then clear routing (mask 0) so it lets go of v3
    # SPEED table: gentle vibrato for the lead
    st_l = [0x03]
    st_r = [0x20]

    def ins(ad, sr, wtbl, fw, name, ptbl=0, ftbl=0, stbl=0, vibdelay=0):
        nm = name.encode("latin1")[:16]; nm += b"\x00" * (16 - len(nm))
        return bytes([ad, sr, wtbl, ptbl, ftbl, stbl, vibdelay, 2, fw]) + nm
    instruments = [
        ins(0x09, 0xF8, 1, 0x21, "Lead", stbl=1, vibdelay=0x08),  # saw + vibrato
        ins(0x08, 0xF8, 1, 0x21, "Bass", ftbl=1),                 # saw + auto-wah (looping cutoff sweep, stays open)
        ins(0x12, 0x88, 9, 0x21, "Harmony"),                      # saw ARPEGGIO, louder sustain
        ins(0x08, 0x00, 13, 0x11, "Kick"),                        # punchy pitch-drop
        ins(0x0A, 0x00, 5, 0x81, "Snare"),                        # fuller noise
        ins(0x05, 0x00, 5, 0x81, "Hihat"),                        # short noise
        ins(0x0C, 0x00, 3, 0x11, "Tom"),                          # tri hit
        ins(0xA9, 0x00, 5, 0x81, "Swell", ftbl=6),                # slow-attack noise + opening filter sweep
        ins(0x09, 0x89, 7, 0x41, "Fill", ptbl=1),                 # pulse counter-melody (fills lead rests)
        ins(0x2A, 0xA8, 3, 0x11, "Pad", stbl=1, vibdelay=0x20),   # slow triangle pad (SID2 sustains)
    ]

    # ----- serialize .sng -----
    o = bytearray(); o += b"GTS5"
    o += (title.encode("latin1")[:31] + b"\x00").ljust(32, b"\x00")  # songname
    o += b"camping-sid\x00".ljust(32, b"\x00")     # author
    o += (b"\x00" * 32)                            # copyright
    o += bytes([1])                                # 1 subtune
    for ch in range(NCH):
        ol = order[ch]
        body = bytes(ol) + bytes([0xFF, 0])           # RST: loop orderlist to pos 0
        o += bytes([len(body) - 1]); o += body
    o += bytes([len(instruments)])
    for it in instruments: o += it
    o += bytes([len(wt_l)]) + bytes(wt_l) + bytes(wt_r)   # 0 wave
    o += bytes([len(pt_l)]) + bytes(pt_l) + bytes(pt_r)   # 1 pulse
    o += bytes([len(ft_l)]) + bytes(ft_l) + bytes(ft_r)   # 2 filter
    o += bytes([len(st_l)]) + bytes(st_l) + bytes(st_r)   # 3 speed
    o += bytes([len(patterns)])
    for pat in patterns:
        o += bytes([len(pat)//4]); o += pat
    with open(out, "wb") as f:
        f.write(o)
    print(f"  wrote {len(o)} bytes -> {out}  ({len(patterns)} patterns, "
          f"{npat_per}/channel)")

def build_stereo(out, voices, tempo, rows_per_pat, hihat_div=2, title="Stereo",
                 combined=None):
    """OPT-IN dual-SID. voices = list of (ch0, role, src); ch 0-5 map to the
    6 SID voices (0-2 = SID1, 3-5 = SID2). role assigns the instrument/treatment.
    src is a stem file, or '@N' to pull channel N (1-based) from the combined
    MIDI (`combined` = (div, notes, drums, end_tick)); '@' alone = its drum kit.
    Drum roles kick|snare|hihat|perc each take one GM subset onto their own voice
    so the whole kit sounds at once; 'drums' = the full kit on a single voice.
    Default path stays 3-channel mono build()."""
    ROLE_INSTR = {"lead": 1, "bass": 2, "harm": 3, "counter": 9, "pad": 10}
    DRUM_ROLE = {"drums": None, "kick": {4}, "snare": {5}, "hihat": {6}, "perc": {7, 8}}
    div = None; end_tick = 0; loaded = []
    for ch, role, f in voices:
        if combined is not None and f.startswith("@"):
            cdiv, cnotes, cdrums, cet = combined
            mel = cnotes.get(int(f[1:]) - 1, []) if f[1:] else []
            d, et, dr = cdiv, cet, cdrums
        else:
            d, et, mel, dr = load_stem(f)
        div = div or d; end_tick = max(end_tick, et)
        loaded.append((ch, role, mel, dr))
    tpr = div / 4.0
    total_rows = int(end_tick / tpr) + 8
    grid = [[(REST, 0) for _ in range(total_rows)] for _ in range(6)]
    print(f"stereo (dual-SID, 6 voices): {end_tick/div/4:.0f} bars -> {total_rows} rows")

    def place_voice(ch, notes, instr):
        ev = sorted(notes)
        for i, (start, dur, pit) in enumerate(ev):
            r = int(round(start / tpr))
            if not (0 <= r < total_rows): continue
            grid[ch][r] = (note_byte(pit), instr)
            endr = r + max(1, int(round(dur / tpr)))
            nxt = int(round(ev[i+1][0] / tpr)) if i + 1 < len(ev) else total_rows
            if r < endr < nxt and endr < total_rows and grid[ch][endr][0] == REST:
                grid[ch][endr] = (KEYOFF, 0)

    drumdef = {
        "kick": (4, note_byte(36), 5), "snare": (5, note_byte(60), 4),
        "clap": (5, note_byte(60), 4), "rim": (5, note_byte(60), 4),
        "hihat": (6, note_byte(72), 2), "openhat": (6, note_byte(74), 2),
        "ride": (6, note_byte(72), 2), "tom": (7, note_byte(48), 3),
        "crash": (8, note_byte(72), 6),
    }

    def place_drums(ch, drums, allow=None):
        best = {}
        for start, gm in drums:
            name = GM_DRUM.get(gm)
            if name not in drumdef: continue
            instr, nb, prio = drumdef[name]; r = int(round(start / tpr))
            if not (0 <= r < total_rows): continue
            if allow is not None and instr not in allow: continue
            if r not in best or prio > best[r][0]: best[r] = (prio, instr, nb)
        snare_rows = sorted(r for r, (p, i, nb) in best.items() if i == 5)
        runs, cur = [], []
        for r in snare_rows:
            if cur and r - cur[-1] > 2: runs.append(cur); cur = []
            cur.append(r)
        if cur: runs.append(cur)
        for run in runs:
            if len(run) >= 8:
                for k, r in enumerate(run):
                    best[r] = (best[r][0], 5, note_byte(40 + int(48 * k / (len(run) - 1))))
        cnt = Counter(); swell_until = -1
        for r in sorted(best):
            prio, instr, nb = best[r]
            if instr == 6 and (r % hihat_div) != 0: continue
            if instr == 6 and r <= swell_until: continue
            grid[ch][r] = (nb, instr); cnt[instr] += 1
            if instr == 8: swell_until = r + 5
        return sum(cnt.values())

    for ch, role, mel, dr in loaded:
        if role in DRUM_ROLE:
            n = place_drums(ch, dr, DRUM_ROLE[role]); print(f"  v{ch+1} {role}: {n} hits")
        elif role in ROLE_INSTR:
            place_voice(ch, mel, ROLE_INSTR[role]); print(f"  v{ch+1} {role}: {len(mel)} notes")
        else:
            print(f"  v{ch+1} UNKNOWN role '{role}' — skipped")
    serialize_sng(out, title, tempo, grid, rows_per_pat)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("inp", nargs="?", help="combined source MIDI (omit when "
                    "building from --lead/--bass/--harm/--drums stem files)")
    ap.add_argument("out")
    ap.add_argument("--tempo", type=lambda x: int(x, 16), default=0x06,
                    help="GoatTracker Fxx tempo (hex), default 06")
    ap.add_argument("--rows-per-pat", type=int, default=64)
    ap.add_argument("--hihat-div", type=int, default=2,
                    help="place a hihat only every Nth row (2 = 8th-note feel)")
    ap.add_argument("--mode", choices=("clean", "shared"), default="shared",
                    help="clean = lead/bass/drums; shared = lead/harmony/"
                         "bass+drums (fuller, drums fill the bass rests)")
    ap.add_argument("--map", default=None, metavar="LEAD,BASS,HARM",
                    help="force MIDI channels (1-based, as printed) to roles, "
                         "e.g. --map 4,2,3 ; use '-' to skip a role")
    ap.add_argument("--kick-bass", action="store_true",
                    help="put the kick on the bass channel (fills its rests, "
                         "thickens low end); snare/hat stay with the harmony")
    ap.add_argument("--fill", default=None,
                    type=lambda x: [int(t) - 1 for t in x.split(",")],
                    metavar="CHAN[,CHAN...]",
                    help="fill the lead channel's rests from these MIDI channels "
                         "(1-based, priority pool: first listed wins) on a soft "
                         "instrument, e.g. the brass hook / piano comp")
    ap.add_argument("--lead", help="stem file for the lead voice")
    ap.add_argument("--bass", help="stem file for the bass voice")
    ap.add_argument("--harm", help="stem file for the harmony voice")
    ap.add_argument("--drums", help="stem file for the drum kit")
    ap.add_argument("--title", default="In The Navy", help="song name in the .sng/.sid")
    ap.add_argument("--arrange", default=None, metavar="PRESET|SPEC",
                    help="stage a flat source loop into build/drop sections. "
                         "A preset name (" + "|".join(PRESETS) + ") or a spec "
                         "'BARS:LAYERS,...' where LAYERS subset khbl (k=kick "
                         "h=hat/snare b=bass l=lead) + optional r = riser on the "
                         "last bar, e.g. 8:k,8:khr,16:khbl")
    ap.add_argument("--four-on-floor", action="store_true",
                    help="(with --arrange) replace the sparse source kit with a "
                         "canonical dance groove: kick every beat, clap on 2&4, "
                         "open hat on every offbeat")
    ap.add_argument("--voice", action="append", default=[], metavar="CH=ROLE=SRC",
                    help="OPT-IN dual-SID: assign a part to a SID voice. CH 1-6 "
                         "(1-3=SID1, 4-6=SID2); ROLE lead|bass|harm|counter|pad|"
                         "drums|kick|snare|hihat|perc; SRC = a stem file or '@N' "
                         "to pull channel N from the combined input MIDI ('@' = "
                         "its drum kit). Repeatable. Any --voice -> 6-channel "
                         "stereo .sng (AUDITION ONLY: gt2reloc exports single-SID, "
                         "so .sid keeps just voices 1-3). Without it, 3-ch mono.")
    a = ap.parse_args()
    if a.arrange:                     # stage a flat loop into build/drop sections
        build_arranged(a.inp, a.out, a.tempo, a.rows_per_pat,
                       parse_arrange(a.arrange), a.hihat_div, a.map, a.title,
                       a.four_on_floor)
    elif a.voice:                     # opt-in dual-SID; default path is mono
        voices = []
        for v in a.voice:
            ch, role, f = v.split("=", 2)
            voices.append((int(ch) - 1, role.strip().lower(), f))
        combined = None               # '@N' voices slice the combined input MIDI
        if a.inp and any(f.startswith("@") for _, _, f in voices):
            cdiv, cet, cnotes, cdrums = parse_midi(a.inp)
            combined = (cdiv, cnotes, cdrums, cet)
        build_stereo(a.out, voices, a.tempo, a.rows_per_pat, a.hihat_div, a.title,
                     combined)
    else:
        stems = {k: v for k, v in (("lead", a.lead), ("bass", a.bass),
                                   ("harm", a.harm), ("drums", a.drums)) if v}
        build(a.inp, a.out, a.tempo, a.rows_per_pat, a.hihat_div, a.mode, a.map,
              a.kick_bass, a.fill, stems or None, a.title)
