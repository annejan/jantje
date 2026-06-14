# Jantje

Parametric **MIDI / stems → GoatTracker 2 `.sng`** arranger. Compose authentic
3-channel mono C64 SID tunes directly from source MIDIs — no MIDI-import
round-trip — then audition them live in the [goattracker2-Qt][gt2] editor.

> Named after Jantje Smit. Because it makes songs and kloot fed me names like SNG-Smith . . 🐐🦙

## What's here

| file | what |
| ---- | ---- |
| `midi_to_sng.py` | the arranger: MIDI (or named stem files) → `.sng` |
| `midi_arrange.py` | planner: print the proposed role/drum mapping for a MIDI |
| `midi_inspect.py` | list a MIDI's tracks (name/GM-program/notes) to find the vocal |
| `AGENTS.md` | full tooling notes, `.sng` format, SID-synth cheat-sheet, lessons |

## Install

Nothing. Pure Python 3 standard library (`struct`, `argparse`, `collections`).
No `pip`, no `mido`, no ChiptuneSAK — the MIDI parser is hand-rolled. (Optional:
`mido` only if you want to script your own source inspection.)

## Use

```sh
# from one combined MIDI (parts on separate channels)
python3 midi_to_sng.py song.mid out.sng --map 4,2,3 --kick-bass

# or from deliberately chosen, isolated stem files (the clean way)
python3 midi_to_sng.py out.sng \
  --lead vocal.mid --bass bass.mid --harm organ_stab.mid --drums drumkit.mid \
  --mode shared --kick-bass
```

### Finding the right channels (do this first)

`midi_arrange.py` ranks channels by pitch and *guesses* roles — fine for clean
dance MIDIs, wrong for karaoke/GM files where the vocal is buried mid-stack.
Before mapping, read the **track names and GM programs** with `midi_inspect.py`,
because the channel you want is the one literally labelled the melody:

```sh
python3 midi_inspect.py song.mid             # list tracks: name / GM patch / notes
python3 midi_inspect.py song.mid --channel 5 # dump ch5's busiest bar as note names
                                             #   (eyeball it to confirm the hook)
```

A track named `CANTO` / `Melody` / `Vocal` (or a lead-register patch like Sax,
Flute, Lead) is your lead — *not* whichever channel sits highest. This is how
What Is Love (lead = `CANTO`, not the organ) and Ibiza (lead = the Flute, the
karaoke vocal) got mapped right.

### The reliable mono recipe

For a karaoke/GM dance track, the layout that consistently lands a clear vocal +
a floor beat with no grit is: **lead = vocal, clean bass, drums on their own
voice** (drop the busy comp/riff so the kit isn't squeezed):

```sh
python3 midi_to_sng.py song.mid out.sng --map VOCAL,BASS,- --mode clean
# clean mode: lead | bass | drums — bass keeps its own voice (no kick blip = no
# grit), the kit gets a full channel (kick+snare+hat) instead of fighting a comp.
```

Miss the signature riff once the comp is gone? Drop it into the **vocal's rest
holes** with `--fill` (priority pool, first listed wins) — the riff plays the
instrumental gaps, the vocal owns the choruses. Each source is **either a
1-based MIDI channel** (from a combined input) **or a stem file path**:

```sh
# channel out of a combined MIDI
python3 midi_to_sng.py song.mid out.sng --map VOCAL,BASS,- --mode clean --fill RIFF

# a stem file into a stem build — e.g. the "na na" hook into the vocal's holes
python3 midi_to_sng.py out.sng --lead vocal.mid --bass bass.mid --drums kit.mid \
  --mode shared --fill na_na_hook.mid
```

### Dual-SID (6 voices) — audition only

Opt into **dual-SID** by assigning parts to voices. From isolated stems, or
`@N` to pull channel N (1-based) straight from the combined input MIDI (`@`
alone = its GM drum kit). Drum roles `kick|snare|hihat|perc` each take one kit
subset onto their own voice, so the whole kit sounds at once:

```sh
# from stems
python3 midi_to_sng.py out.sng \
  --voice 1=lead=vocal.mid    --voice 2=bass=bass.mid   --voice 3=harm=organ.mid \
  --voice 4=counter=piano.mid --voice 5=pad=strings.mid --voice 6=drums=kit.mid

# straight from one combined MIDI (kit split across SID2)
python3 midi_to_sng.py song.mid out.sng \
  --voice 1=lead=@4 --voice 2=bass=@2 --voice 3=harm=@1 \
  --voice 4=kick=@  --voice 5=snare=@ --voice 6=hihat=@
```

`CH` 1-6 (1-3 = SID1, 4-6 = SID2); `ROLE` = lead|bass|harm|counter|pad|drums|
kick|snare|hihat|perc. The editor auto-detects the 6 channels on load.

> ⚠️ **6-voice `.sng` is audition-only.** The bundled `gt2reloc` only emits
> **single-SID** PSID, so exporting to `.sid`/`.mp3` keeps just the first 3
> voices (drums on SID2 get dropped). For a playable file use the 3-voice mono
> path; use dual-SID for live audition in the Qt editor.

### Staging a flat loop into build/drop (`--arrange`)

Some source MIDIs are a single bar-aligned loop with every part on from bar 0
(e.g. cprato's Sandstorm: lead+bass+drums all play the downbeat). One pass has
no tension — the climax is the start, then it just repeats. `--arrange` tiles
the loop into named sections, each revealing a subset of the four layers
(`k`=kick `h`=hat/snare `b`=bass `l`=lead), with an optional rising-noise riser
(`r`) on a section's last bar:

```sh
python3 midi_to_sng.py sandstorm.mid out.sng --map 8,4,- --arrange darude
# darude preset = 8:k,8:khr,8:khb,16:khbl,16:khbl,8:khr,16:khbl
#   intro(kick) -> build(+hat+riser) -> groove(+bass) -> DROP(+lead) -> ...
```

Pass a custom `BARS:LAYERS,...` spec instead of a preset name for any shape.

Add `--four-on-floor` when the source kit is too thin for a dance floor (some
loops hold only ~1 hat/bar): it ignores the source drums and lays a canonical
house groove — kick on every beat, clap on 2 & 4, open hat on every offbeat.

See `AGENTS.md` for every knob (`--mode`, `--map`, `--kick-bass`, `--fill`,
`--tempo`, `--title`, …) and the live-audition RPC loop.

## Cookbook (the exact commands that worked)

Sources are git-ignored — drop your own `.mid` in `sources/` and re-run.

```sh
# Sandstorm — a flat 16-bar loop, staged into a build/drop with a synth beat
python3 midi_to_sng.py "sources/Sandstorm ….mid" renders/sandstorm.sng \
  --map 8,4,- --arrange darude --four-on-floor --title "Sandstorm"

# Dance Monkey — combined MIDI, classic 3-voice with kick on the bass
python3 midi_to_sng.py "sources/… Dance Monkey ….mid" renders/dance_monkey.sng \
  --map 1,3,9 --kick-bass --title "Dance Monkey"

# What Is Love — karaoke MIDI; lead = the CANTO vocal track (ch4), not the organ
python3 midi_to_sng.py "sources/Haddaway ….mid" renders/what_is_love.sng \
  --map 4,2,- --mode clean --title "What Is Love"

# Going to Ibiza — karaoke MIDI; lead = the Flute (the vocal), brass hook in the gaps
python3 midi_to_sng.py "sources/VENGA BOYS ….mid" renders/ibiza.sng \
  --map 5,2,- --mode clean --fill 1 --title "Going to Ibiza"

# All That She Wants — karaoke MIDI; lead = ch5 Melody, whistle+flute hook in the gaps
python3 midi_to_sng.py "sources/… All That She Wants.MID" renders/all_that_she_wants.sng \
  --map 5,2,- --mode clean --fill 8,6 --title "All That She Wants"

# Freed From Desire ("friet") — from named stems; na_na hook fills the vocal's
# holes (a stem --fill), and the real bass riff is tiled back across the intro
S=/path/to/friet/stems
python3 midi_to_sng.py renders/freed-from-desire.sng \
  --lead $S/vocal.mid --bass $S/bass.mid --harm $S/organ_stab.mid --drums $S/drumkit.mid \
  --mode shared --kick-bass --fill $S/na_na_hook.mid --title "Friet met Desire"
```

Export each `.sng` to a playable `.sid` (and capture an `.mp3`):

```sh
( cd /path/to/goattracker2-Qt/src && qt/build/gt2reloc out.sng out.sid )
sidplayfp -w/tmp/o.wav -t200 out.sid && ffmpeg -y -i /tmp/o.wav out.mp3
```

## Lessons baked in (the hard way)

- **4 elements, 3 mono voices.** Sharing drums with the bass kills the drums;
  sharing with the harmony kills the harmony. The fixes: kick on the bass
  channel (four-on-the-floor doubles as low end), and "interrupt-and-resume" —
  a drum blips for one row, the melodic note re-asserts the next row.
- **Snare rolls → rising noise risers** instead of a machine-gun C-3.
- **Crash → a real swell** (slow-attack noise + a filter table that ramps the
  cutoff up, then clears its own routing so it lets go of the voice).
- **Don't cram a counter-melody onto a busy voice** — only fill a voice across
  sections where its part is fully silent.
- **The vocal is the channel that's *labelled* the vocal**, not the highest one.
  Read track names / GM programs before mapping a karaoke or GM file.
- **Clean bass = no kick on it.** The kick-blip-and-resume trick thickens a
  sparse mix but adds grit; give the bass its own voice when the kit can live
  elsewhere.
- **A flat all-parts-from-bar-0 loop has no song in it** — stage it with
  `--arrange` (reveal layers) so it builds instead of starting at the climax.
- **gt2reloc is single-SID only** — 6-voice renders are for editor audition, not
  `.sid` export.
- **8580 vs 6581 voicing**, auto-wah bass, pitch-drop kicks — see `AGENTS.md`.

## Development

Runtime is stdlib-only; the dev tooling (lint + tests) is optional:

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"        # ruff + pytest
ruff check .                   # lint  (config in pyproject.toml)
pytest                         # smoke tests (synthesize a tiny MIDI, drive every build path)
```

[GitHub Actions](.github/workflows/ci.yml) runs `ruff check` + `pytest` on
Python 3.9/3.11/3.13 for every push and PR. A `.pre-commit-config.yaml` mirrors
both if you want them on `git commit` (`pip install pre-commit && pre-commit install`).

The code is deliberately **dense** (multiple statements per line); ruff is
configured to keep that style (E7xx/E401/E501 off) and only flag real problems
(pyflakes, bugbear, simplify, pyupgrade). Don't reformat with black.

## Related

- **[goattracker2-Qt][gt2]** — the Qt editor this drives (live `--rpc`, an MCP
  bridge, `gt2reloc` for `.sid`/`.prg` export, `sid2sng` for `.sid` → `.sng`).
- Drop your own MIDIs / stems / `.prg` / `.sid` in **`sources/`** (git-ignored).
- Renders are **not** tracked either — regenerate them; `renders/` is git-ignored.

[gt2]: https://codeberg.org/Ranzbak/goattracker2-Qt
