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

Default is **3-channel mono**. Opt into **dual-SID (6 voices)** by assigning
stems to voices — without `--voice` nothing changes:

```sh
python3 midi_to_sng.py out.sng \
  --voice 1=lead=vocal.mid    --voice 2=bass=bass.mid   --voice 3=harm=organ.mid \
  --voice 4=counter=piano.mid --voice 5=pad=strings.mid --voice 6=drums=kit.mid
```

`CH` 1-6 (1-3 = SID1, 4-6 = SID2); `ROLE` = lead|bass|harm|counter|pad|drums.
The editor auto-detects the 6 channels on load.

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
- Drop your own MIDIs / stems / `.prg` / `.sid` in **`sources/`** (git-ignored).
- Renders are **not** tracked either — regenerate them; `renders/` is git-ignored.

[gt2]: https://codeberg.org/Ranzbak/goattracker2-Qt
