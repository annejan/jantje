# Jantje

Parametric **MIDI / stems → GoatTracker 2 `.sng`** arranger. Compose authentic
3-channel mono C64 SID tunes directly from source MIDIs — no MIDI-import
round-trip — then audition them live in the [goattracker2-Qt][gt2] editor.

> Named after Jantje Smit. Because it makes songs. 🐐

## What's here

| file | what |
| ---- | ---- |
| `midi_to_sng.py` | the arranger: MIDI (or named stem files) → `.sng` |
| `midi_arrange.py` | planner: print the proposed role/drum mapping for a MIDI |
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

See `AGENTS.md` for every knob (`--mode`, `--map`, `--kick-bass`, `--fill`,
`--tempo`, `--title`, …) and the live-audition RPC loop.

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
- **8580 vs 6581 voicing**, auto-wah bass, pitch-drop kicks — see `AGENTS.md`.

## Related

- **[goattracker2-Qt][gt2]** — the Qt editor this drives (live `--rpc`, an MCP
  bridge, `gt2reloc` for `.sid`/`.prg` export, `sid2sng` for `.sid` → `.sng`).
- Renders, source MIDIs and stems are **not** in this repo (regenerate them);
  `renders/` is git-ignored.

[gt2]: https://codeberg.org/Ranzbak/goattracker2-Qt
