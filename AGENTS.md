# camping-sid — parametric MIDI → C64 SID arranger

Compose **GoatTracker 2 `.sng`** files directly in Python from source MIDIs, no
MIDI-import round-trip. Built for arranging pop covers (Village People – *In The
Navy* = Ome Henk – *Op de Camping*, same tune) into authentic **3-channel mono
SID** with translated drums, then auditioning live in the GoatTracker Qt editor.

## Files
- `midi_to_sng.py` — the generator. MIDI → `.sng` (the main tool).
- `midi_arrange.py` — planner. Prints the proposed role/drum mapping for a MIDI
  without generating audio. Run this first when looking at a new source MIDI.
- Source MIDIs live in **`/home/annejan/Projects/martin/assets/`** —
  **do NOT write there** (it's the user's real project). Output goes elsewhere
  (the working `.sng`, currently `/home/annejan/op-de-camping.sng`).

## Quick start
```sh
python3 midi_arrange.py "/home/annejan/Projects/martin/assets/Village People In The Navy.mid"
python3 midi_to_sng.py  "/home/annejan/Projects/martin/assets/Village People In The Navy.mid" \
        /home/annejan/op-de-camping.sng --mode shared
```

### Generator knobs
- `--mode clean|shared` (default `shared`)
  - `clean`  = lead | bass | drums (each channel one role; full drums, no harmony)
  - `shared` = lead | harmony | bass+drums (fuller; kick/snare punch through the
    bass, hihats fill its rests — the iconic 3-voice SID layout)
- `--tempo HH` GoatTracker Fxx tempo, hex (default `06` ≈ 125 bpm on the 16th grid)
- `--rows-per-pat N` pattern length (default 64)
- `--hihat-div N` keep a hihat only every Nth row (default 2 = 8th-note feel)
- `--map LEAD,BASS,HARM` force 1-based MIDI channels to roles (`-` skips one);
  beats the average-pitch guesser when a combined MIDI has many channels
- `--kick-bass` put the four-on-the-floor kick on the bass channel (fills its
  rests + thickens low end); snare/hat stay on the harmony channel
- `--fill CHAN` (combined-MIDI mode) counter-melody from another channel into the
  lead's *long* holes only — **a dead end so far**: cramming a 2nd part onto a
  busy voice sounds wrong; only worth it on sections where the lead is FULLY
  silent (see friet notes). Off by default.

### Two ways to feed it
1. **Combined MIDI** (one file, parts on separate channels): `midi_to_sng.py in.mid out.sng [--map …]`.
   Without `--map`, voices are auto-assigned by **average pitch** (low=bass,
   high=lead, mid=harmony). Drums = MIDI channel 10 (GM kit); see `GM_DRUM`.
2. **Named stem files** (the clean way — one isolated part per file, all on the
   same grid): `midi_to_sng.py out.sng --lead vocal.mid --bass bass.mid
   --harm organ_stab.mid --drums drumkit.mid`. No channel-guessing; you pick
   each stem deliberately. This is preferred when stems exist.

## Live audition loop (the whole point — iterate by ear)
The editor has a JSON-RPC stdin/stdout interface. Drive a **visible** instance
via a fifo so commands can be sent across separate shell calls:

```sh
EDITOR=/home/annejan/Projects/goattracker2-Qt/qt/build/goattrk2-qt
pkill -x goattrk2-qt; pkill -x sleep        # NB: never `pkill -f` — it matches your own shell
rm -f /tmp/gtrpc.in /tmp/gtrpc.out; mkfifo /tmp/gtrpc.in; : > /tmp/gtrpc.out
setsid sh -c 'exec sleep 100000 > /tmp/gtrpc.in' &      # holder keeps the fifo's write end open
nohup "$EDITOR" --rpc /home/annejan/op-de-camping.sng < /tmp/gtrpc.in > /tmp/gtrpc.out 2>&1 &
```
Then per turn: regenerate the `.sng`, and reload without restarting:
```sh
printf '{"cmd":"load","path":"/home/annejan/op-de-camping.sng","id":1}\n' > /tmp/gtrpc.in
grep '^{' /tmp/gtrpc.out | tail -3        # responses are line-delimited JSON
```
Useful commands: `{"cmd":"state"}`, `{"cmd":"instr","num":N}`,
`{"cmd":"pattern","num":N}`, `{"cmd":"table","name":"wave|pulse|filter|speed"}`,
`{"cmd":"order"}`, `{"cmd":"action","name":"<menu text>"}`. The agent **cannot
hear** — the user is the ear; make one change, regenerate, ask.

## .sng binary format (GTS5, from src/gsong.c savesong)
```
"GTS5"
songname[32] author[32] copyright[32]
u8 nsubtunes
  per subtune, per channel (3 mono / 6 stereo, auto-detected on load):
    u8 len(=songlen+1); (len+1) bytes orderlist  (pattern nums <0xD0; ends 0xFF,looppos)
u8 highest_used_instr
  per instr: ad sr wtbl ptbl ftbl stbl vibdelay gatetimer firstwave, name[16]
per table (wave,pulse,filter,speed): u8 len; ltable[len]; rtable[len]
u8 npatterns
  per pattern: u8 len(=rows+1); rows*4 bytes (note,instr,cmd,param), ends ENDPATT row
```
Constants (src/gcommon.h): FIRSTNOTE 0x60 (C-0) .. LASTNOTE 0xBC, REST 0xBD,
KEYOFF 0xBE, KEYON 0xBF, ENDPATT/loop 0xFF, REPEAT 0xD0, MAX_PATTROWS 128,
MAX_INSTR 64, MAX_TABLES 4. Note byte = FIRSTNOTE + (midi - 24), octave-clamped.

## SID synthesis cheat-sheet (for designing instruments/drums)
- **Waveforms** (firstwave / wavetable L, all +gate $01): triangle `$11`, saw
  `$21`, pulse `$41`, noise `$81`. Pulse needs a pulse-width (pulse table) or it
  is silent. `firstwave` should be the real waveform (+gate) so frame 1 sounds —
  a `$09` (gate+test) first frame plops unless the wavetable sets a waveform next.
- **Wave table**: L = waveform ($10-$DF) / `$00` hold / `$FF` jump (R=target step,
  $00=stop). R = relative note (`$00-$5F` = +semitones) → use for **arpeggios**
  (root,+7,+12 loop = neutral chord) and **pitch-drop kicks** (+12,+6,0).
- **Pulse table**: `$8X`,R = set 12-bit width $X_RR; `$01-$7F`,R = modulate L
  ticks at signed speed R (PWM sweep); `$FF` jump.
- **Filter table**: `$00`,R = set cutoff; `$8X`,R = passband ($90 lowpass) +
  R=(resonance hi-nyb | channel-mask lo-nyb, bit per voice); `$FF` hold.
- **Speed table** (vibrato): L = ticks before direction flip, R = pitch delta;
  instrument `stbl` points here, `vibdelay` delays its onset.
- ADSR: `ad` = attack|decay nibbles, `sr` = sustain|release. Drums = decay-to-
  silence (`sr` sustain nibble 0). One SID master volume → balance voices by
  envelope/sustain level, not a per-voice volume.

## Current arrangement recipe (what's in midi_to_sng.py now)
- Lead: saw + vibrato (`stbl`), sustained.
- Bass: **saw, NO filter** (full volume) — the low-pass made it nearly inaudible.
  Instrument 1 + filter table `ftbl=1` still exists if you want it back.
- Harmony (shared mode): saw **arpeggio** (root/+7/+12), sustain nibble 8.
- Drums: kick = triangle pitch-drop, snare/hihat = noise bursts.
- **Drums + harmony share ch3 via "interrupt-and-resume"**: a kick/snare punches
  through for 1 row, then the harmony note it replaced is re-asserted on the next
  row so it keeps sounding. Hihats only fill rest rows.
- **Snare rolls → rising noise risers**: any run of ≥8 near-consecutive snares
  (eurodance buildups) climbs in pitch ~4 octaves instead of a machine-gun C-3.
- **Crash → "Swell" (instr 8)**: slow-attack noise + a filter table (`ftbl=4`)
  that ramps the cutoff up then *clears its routing* (mask 0) so it lets go of
  voice 3 instead of leaving it heavily filtered.
- **Thin-intro fill**: while the real bass hasn't entered, the harmony root is
  laid an octave down on the bass channel (held through gaps) so it isn't empty.

## Exporting a real .sid (F9 / gt2reloc)
Works now: the Qt build generates the C64 playroutine blob (`goatdata.c`) from
`src/goattrk2.seq` and links it into `gt2reloc`, so F9 packs a playable PSID.
CLI: `cd src && qt/build/gt2reloc your.sng out.sid` (run from `src/` so the
relocator finds player.s). Earlier this died with "COULD NOT OPEN PLAYROUTINE"
because upstream's Qt port shipped an empty `datafile[]` stub.

## Rendering an MP3 (the agent can't hear — capture live editor audio)
For a quick listen you can also `sidplayfp -w out.wav out.sid`. To capture the
editor's exact libresidfp output, record its monitor:
```sh
MON=$(pactl get-default-sink).monitor          # e.g. bluez_output.*.monitor
parec --device="$MON" --format=s16le --rate=48000 --channels=2 \
      --file-format=wav /tmp/cap.wav &          # start recorder, THEN press F1
# user presses F1 in GoatTracker (play from beginning), let it loop once, F4 to stop
pkill -x parec
# find where audio starts, trim the lead-in + the loop tail, normalise:
ffmpeg -hide_banner -nostats -i /tmp/cap.wav -af silencedetect=noise=-50dB:d=0.3 -f null -  # -> start ts
ffmpeg -y -ss <START> -t <SONGLEN> -i /tmp/cap.wav \
  -af "afade=t=in:st=0:d=0.08,afade=t=out:st=<SONGLEN-2>:d=2.0,loudnorm=I=-14:TP=-1.5:LRA=11" \
  -codec:a libmp3lame -b:a 320k renders/out.mp3
```
Song length ≈ `total_rows × tempo_ticks ÷ 50` s (PAL). Snapshot the matching
`.sng` next to each render for reproducibility.

## Latest render (resume point — In The Navy)
`renders/in-the-navy_8580_full.{mp3,sng}` — full 3:21, 8580 voicing, harmony
interrupt-and-resume. User: "begint in de buurt te komen". Mix is close; harmony
no longer drops out, only minimally choppy.

## Freed From Desire (friet) — WORK IN PROGRESS (resume here)
Building from the **named stems** in `/home/annejan/Projects/friet/midi/` and
especially `/home/annejan/Projects/friet/stems/` (all aligned, 120bpm, tpq=240).
Stem inventory: vocal (lead, bars 5-93), bass (bars 30-102!), organ_stab (hook,
bars 2-102 but gappy), drumkit (four-on-floor), piano_comp (bars 14-85, dense),
na_na_hook (bars 46-62), strings, sweep_pad, reverse_cymbal.

Working file `/home/annejan/freed-from-desire.sng`, snapshot
`renders/freed-from-desire_wip.{sng,cmd}`. Generate command is in the `.cmd`.
Deliberate stem mapping (user-chosen): vocal=lead, bass=bass, organ_stab=harmony,
drumkit=drums; `--kick-bass` on.

What works: kick-split fills the bass channel + thickens low end; snare rolls →
rising risers; crash → swell; the **unfiltered saw bass is good** ("tegen het
einde lekker"); intro lays the organ root an octave down as ended notes.

Open TODOs (user feedback, newest first):
- **Empty sections / "leeg op plekken"** — bars 0-32 the bass channel is thin
  (real bass enters bar 30; there's a drum breakdown bars 16-24). The ONLY clean
  fill is to use a stem on a section where a voice is FULLY free — e.g. drop
  `na_na_hook.mid` into the lead during bars ~46-62 where the vocal rests. Do NOT
  cram a 2nd part onto a busy voice (tried; sounds wrong).
- The very first note's instrumentation differs from when the section repeats —
  make the intro read more like the real riff.
- Bass audibility was the saga: triangle+lowpass = inaudible; unfiltered saw =
  audible but "gaar" only as the intro *drone* (now ended notes). Tone is OK now.
- Decide if a gentle bass low-pass ($D0 cutoff, res $2, `ftbl=1` still defined)
  is wanted back, or keep it unfiltered.

## Constraints / decisions (don't re-litigate)
- **3-channel mono only** — the user rejected stereo/dual-SID. No native "digi"
  4th channel exists in the GoatTracker player; drums are SID-synth (noise/tri).
- **Don't cram two parts onto one busy voice** — a counter-melody jammed into the
  lead's note-gaps sounds wrong. Fill a voice only across sections where its part
  is fully silent, from a deliberately chosen stem.
- **Prefer named stem files over channel-guessing** when stems exist (the friet
  redo uses them; In The Navy still uses a combined MIDI + `--map`).
- Goal vibe: a rough, fun **C64 demo** soundtrack.

## Open next steps (user-requested directions)
- Chord-derived arpeggios (real chord tones, not fixed intervals).
- Make percussion louder / more present without crowding bass.
- Tame the busy intro drums.
- Song structure / proper looping; tempo from the MIDI's own tempo meta.
