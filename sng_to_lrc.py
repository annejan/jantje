#!/usr/bin/env python3
"""sng_to_lrc.py — build a synced .lrc for a SID cover.

The SID render (a GoatTracker .sng from midi_to_sng.py) plays the vocal melody as
the LEAD channel at a FIXED tempo (tempo/50 s per row) — it ignores the source
MIDI's own tempo. So lyric timing must come from OUR render, not the original
recording. This maps a karaoke MIDI's lyrics onto the rendered vocal-note onsets:

    karaoke vocal note[i]  <->  rendered lead onset[i]
    (same vocal line, same order; pair by index, fall back to nearest tick)

Usage:
    sng_to_lrc.py render.sng karaoke.mid out.lrc [opts]

Options:
    --vocal-channel N   1-based MIDI channel of the vocal (default: auto-detect =
                        the channel whose note count best matches the .sng onsets)
    --lead-instr N      .sng instrument number carrying the vocal (default 1 = Lead)
    --secs-per-row F    override row duration (default: read tempo from the .sng,
                        seconds = Fxx/50)
    --title/--artist/--album T   LRC header tags
    --offset MS         shift all timestamps by MS milliseconds (+later/-earlier)

The pairing only needs the vocal LINE structure to match; per-syllable melisma
(a held word over several notes) is tolerated by the nearest-tick fallback.
"""
import argparse
import bisect
import struct
import sys


# ---------------------------------------------------------------------------
# GoatTracker GTS5 .sng reader (mono, 3 channels, as written by midi_to_sng.py)
# ---------------------------------------------------------------------------
def read_sng(path):
    with open(path, "rb") as f:
        g = f.read()
    if g[:4] != b"GTS5":
        sys.exit("not a GTS5 .sng: " + path)
    p = 4 + 32 * 3                                  # songname/author/copyright
    p += 1                                          # subtune count
    orders = []
    for _ in range(3):                              # 3 orderlists (mono)
        n = g[p]; p += 1
        orders.append(list(g[p:p + n + 1])); p += n + 1
    ninstr = g[p]; p += 1
    p += ninstr * 25                                # instruments (25 bytes each)
    for _ in range(4):                              # wave/pulse/filter/speed tables
        ln = g[p]; p += 1; p += 2 * ln
    npat = g[p]; p += 1
    pats = []
    for _ in range(npat):
        rows = g[p]; p += 1
        data = g[p:p + rows * 4]; p += rows * 4
        pats.append([tuple(data[i * 4:i * 4 + 4]) for i in range(rows)])
    return orders, pats


def sng_tempo_secs(orders, pats):
    """Row duration in seconds from the row0/ch0 SETTEMPO (cmd 0xF). Fxx/50."""
    first = orders[0][0]
    note, instr, cmd, param = pats[first][0]
    if cmd == 0xF and param:
        return param / 50.0
    return 0.10                                     # fallback: tempo 05 @ 150bpm


def vocal_onsets(orders, pats, lead_instr):
    """Absolute rows where the LEAD (vocal) instrument plays a real note, in order."""
    order = orders[0]
    abs_row = 0; ons = []; i = 0
    while i < len(order):
        v = order[i]
        if v == 0xFF:
            break
        if v >= 0xD0:                               # transpose/repeat marker
            i += 1; continue
        for r, (note, instr, _cmd, _prm) in enumerate(pats[v]):
            if 0x60 <= note <= 0xBC and instr == lead_instr:
                ons.append(abs_row + r)
        abs_row += len(pats[v]); i += 1
    return sorted(ons)


# ---------------------------------------------------------------------------
# Karaoke MIDI reader: lyric/text events + per-channel note-on ticks
# ---------------------------------------------------------------------------
def read_midi(path):
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"MThd":
        sys.exit("not a MIDI: " + path)
    _, ntrk, _div = struct.unpack(">HHH", d[8:14])
    pos = 14

    def rvar(b, p):
        v = 0
        while True:
            c = b[p]; p += 1; v = (v << 7) | (c & 0x7F)
            if not c & 0x80:
                break
        return v, p

    syl = []                                        # (tick, text) lyric/text events
    chan_notes = {}                                 # channel -> [tick, ...] note-ons
    for _ in range(ntrk):
        ln = struct.unpack(">I", d[pos + 4:pos + 8])[0]
        p = pos + 8; end = p + ln; tick = 0; rs = 0
        while p < end:
            dt, p = rvar(d, p); tick += dt
            st = d[p]
            if st == 0xFF:
                mt = d[p + 1]; p += 2; ll, p = rvar(d, p)
                data = d[p:p + ll]; p += ll
                if mt in (0x01, 0x05):              # text or lyric
                    s = data.decode("latin1")
                    if not s.startswith("@"):
                        syl.append((tick, s))
            elif st in (0xF0, 0xF7):
                p += 1; ll, p = rvar(d, p); p += ll
            else:
                if st & 0x80:
                    rs = st; p += 1
                else:
                    st = rs
                ch = st & 0x0F
                if (st & 0xF0) == 0x90 and d[p + 1] != 0:
                    chan_notes.setdefault(ch, []).append(tick)
                p += 1 if (st & 0xF0) in (0xC0, 0xD0) else 2
        pos = end
    syl.sort()
    for ch in chan_notes:
        chan_notes[ch].sort()
    return syl, chan_notes


def pick_vocal_channel(chan_notes, target, forced):
    if forced is not None:
        return forced - 1
    # the channel whose note count is closest to the rendered onset count
    return min(chan_notes, key=lambda c: abs(len(chan_notes[c]) - target))


def group_lines(syl):
    """Group syllables into lines on KAR markers (\\ = paragraph, / = line)."""
    lines = []; cur = None
    for tk, s in syl:
        new = s[:1] in ("\\", "/")
        txt = s.lstrip("\\/")
        if new or cur is None:
            if cur:
                lines.append(cur)
            cur = [tk, txt]
        else:
            cur[1] += txt
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Build a synced .lrc for a SID cover.")
    ap.add_argument("sng"); ap.add_argument("midi"); ap.add_argument("out")
    ap.add_argument("--vocal-channel", type=int, default=None)
    ap.add_argument("--lead-instr", type=int, default=1)
    ap.add_argument("--secs-per-row", type=float, default=None)
    ap.add_argument("--title", default=""); ap.add_argument("--artist", default="")
    ap.add_argument("--album", default=""); ap.add_argument("--offset", type=int, default=0)
    a = ap.parse_args()

    orders, pats = read_sng(a.sng)
    spr = a.secs_per_row if a.secs_per_row else sng_tempo_secs(orders, pats)
    onsets = vocal_onsets(orders, pats, a.lead_instr)
    if not onsets:
        sys.exit("no vocal onsets found (try --lead-instr)")

    syl, chan_notes = read_midi(a.midi)
    if not syl:
        sys.exit("no lyric/text events in the MIDI")
    vc = pick_vocal_channel(chan_notes, len(onsets), a.vocal_channel)
    voc = chan_notes[vc]
    n = min(len(voc), len(onsets))                  # pair i-th note <-> i-th onset
    voc = voc[:n]; ons = onsets[:n]

    def onset_for(tick):
        j = bisect.bisect_left(voc, tick)
        cand = [k for k in (j - 1, j) if 0 <= k < len(voc)]
        k = min(cand, key=lambda k: abs(voc[k] - tick))
        return ons[k]

    def ts(row):
        s = row * spr + a.offset / 1000.0
        s = max(0.0, s); m = int(s // 60)
        return f"[{m:02d}:{s - 60 * m:05.2f}]"

    hdr = []
    if a.title:  hdr.append(f"[ti:{a.title}]")
    if a.artist: hdr.append(f"[ar:{a.artist}]")
    if a.album:  hdr.append(f"[al:{a.album}]")
    last = onsets[-1] * spr
    hdr.append(f"[length:{int(last // 60):02d}:{last % 60:05.2f}]")
    hdr.append("[re:sng_to_lrc.py — karaoke lyrics on the SID render's vocal onsets]")
    hdr.append("")

    prev = -1; body = []
    for tk, txt in group_lines(syl):
        r = onset_for(tk)
        if r <= prev:
            r = prev + 1
        prev = r
        body.append(f"{ts(r)} {txt.strip()}")

    with open(a.out, "w") as f:
        f.write("\n".join(hdr + body) + "\n")
    print(f"vocal ch{vc + 1} ({len(chan_notes[vc])} notes) <-> {len(onsets)} render "
          f"onsets, {spr:.3f}s/row -> {len(body)} lines -> {a.out}")


if __name__ == "__main__":
    main()
