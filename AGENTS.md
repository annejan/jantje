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
  rests + thickens low end); snare/hat stay on the harmony channel. Thickens a
  sparse mix but the kick-blip adds **grit** to the bass — skip it when the bass
  can have its own clean voice (`--mode clean`, drums on their own channel).
- `--fill CHAN[,CHAN…]` (combined-MIDI mode) counter-melody from these channels
  (1-based, priority pool: first listed wins) into the lead's *long* holes only
  (≥ half a bar). **Now the recommended way to keep a signature riff** once the
  comp is dropped: the riff plays instrumental gaps, the vocal owns the choruses
  (e.g. Ibiza `--fill 1` = the brass hook in the flute-vocal's rests). Still
  wrong to use on *every* little inter-note gap — it only fires on real holes.
- `--arrange PRESET|SPEC` stage a flat all-parts-from-bar-0 loop into named
  build/drop sections; each reveals a layer subset `khbl` (k=kick h=hat/snare
  b=bass l=lead) + optional `r` = riser on the section's last bar. Presets:
  `darude` (high-energy: bass+drums from bar 0, lead teased) and `darude-build`
  (slow kick-up reveal). Custom: `8:khbr,16:khbl,…`.
- `--four-on-floor` (with `--arrange`) ignore a too-sparse source kit and
  synthesize a house groove: kick every beat, clap on 2&4, open hat every
  offbeat. Use when the loop holds ~1 hat/bar.

### Two ways to feed it
1. **Combined MIDI** (one file, parts on separate channels): `midi_to_sng.py in.mid out.sng [--map …]`.
   Without `--map`, voices are auto-assigned by **average pitch** (low=bass,
   high=lead, mid=harmony). Drums = MIDI channel 10 (GM kit); see `GM_DRUM`.
2. **Named stem files** (the clean way — one isolated part per file, all on the
   same grid): `midi_to_sng.py out.sng --lead vocal.mid --bass bass.mid
   --harm organ_stab.mid --drums drumkit.mid`. No channel-guessing; you pick
   each stem deliberately. This is preferred when stems exist.
3. **Dual-SID (6 voices), `--voice CH=ROLE=SRC`** — opt-in stereo. `SRC` is a
   stem file or `@N` to pull channel N (1-based) from the combined input MIDI
   (`@` alone = its GM drum kit). Roles: lead|bass|harm|counter|pad|drums and the
   kit-split roles kick|snare|hihat|perc (each takes one GM subset onto its own
   voice → the whole kit sounds at once). Example straight from one MIDI:
   `--voice 1=lead=@4 --voice 2=bass=@2 --voice 3=harm=@1 --voice 4=kick=@
   --voice 5=snare=@ --voice 6=hihat=@`. **Audition-only — see export note.**

### Identifying the vocal/lead channel (do this before `--map`)
`midi_arrange.py` guesses roles by average pitch — wrong for karaoke/GM files
where the vocal sits mid-stack. The vocal is the channel *labelled* the melody,
so read the track names + GM programs first:
```sh
python3 - "song.mid" <<'PY'
import struct,sys
d=open(sys.argv[1],"rb").read()
_,ntrk,div=struct.unpack(">HHH",d[8:14]); pos=8+struct.unpack(">I",d[4:8])[0]
def vlq(p):
    v=0
    while True:
        b=d[p];p+=1;v=(v<<7)|(b&0x7f)
        if not b&0x80: break
    return v,p
ti=0
while pos<len(d)-8:
    if d[pos:pos+4]!=b'MTrk': pos+=1; continue
    tl=struct.unpack(">I",d[pos+4:pos+8])[0]; p=pos+8; end=p+tl; run=None
    name=""; prog={}; chans=set(); nn=0
    while p<end:
        dt,p=vlq(p)
        if p>=end: break
        st=d[p]
        if st&0x80: p+=1; run=st
        else: st=run
        hi,ch=st&0xf0, st&0x0f
        if st==0xff:
            mt=d[p]; p+=1; ml,p=vlq(p)
            if mt in (1,3,4): name+=d[p:p+ml].decode('latin1','ignore')+" "
            p+=ml
        elif st in (0xf0,0xf7): sl,p=vlq(p); p+=sl
        else:
            nd=1 if hi in (0xc0,0xd0) else 2
            if hi==0xc0: prog[ch]=d[p]
            if hi==0x90 and d[p+1]>0: chans.add(ch); nn+=1
            p+=nd
    if name.strip() or chans:
        print(f"trk{ti:2} ch{sorted(c+1 for c in chans)} prog{ {c+1:prog[c] for c in prog} } n={nn} '{name.strip()}'")
    ti+=1; pos=end
PY
```
A track named `CANTO`/`Melody`/`Vocal` or a lead patch (Sax/Flute/Lead) is the
lead — not the highest channel. Worked for What Is Love (`CANTO`=ch4, *not* the
organ ch1) and Ibiza (Flute=ch5 = the karaoke vocal). To confirm a channel
carries the hook, dump its densest 4-bar block as note names and eyeball the
phrase shape.

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

⚠️ **gt2reloc is single-SID only** (no `-stereo`/`-2sid` flag; it emits PSID v2
with `sid2addr=0`). A **6-voice dual-SID `.sng` exports as just its first 3
voices** — voices 4-6 (typically the SID2 drums) are silently dropped. So
dual-SID (`--voice`) is for **live audition in the Qt editor only**; for a
playable `.sid`/`.mp3` use the 3-voice mono path. Verified: every dual render
here (incl. freed-from-desire) packs to a single-SID file.

## Recovering a .sng from a GoatTracker .sid (reverse — hard-won)
A GT-exported `.sid`/`.prg` embeds the song data verbatim, so exact recovery is
possible — but `qt/build/sid2sng` is a heuristic that must be told which pack
optimisations were used:

- **Flag lottery.** 5 bool flags (`-nopulse -nofilter -noinstrvib -fixedparams
  -nowavedelay`) = 32 combos; the wrong combo shifts the read pointer and you
  get a *remix* (plausible but wrong notes), or `ERROR: speed table`. Brute-force
  all 32, keep the ones that parse AND re-pack (`gt2reloc`) cleanly.
- **Verify by BYTE-DIFF, not by ear.** Re-pack each candidate, align both `.sid`s
  on the freq-table signature (`08 09 09 0a 0a 0b 0c 0d …`), diff from there.
  Exclude pure *relocation* diffs: a newer player is N bytes bigger, so pointer
  lo-bytes differ by `-N` and page-crossing hi-bytes by `±1`. **NON-reloc diffs
  == 0 ⇒ byte-faithful song data.** For Dippy's *Satellite One* the faithful
  combo was **`-fixedparams -nowavedelay`** (0 non-reloc diffs).
- **Audio xcorr is misleading.** Identical data played by a *different player
  version* drifts in micro-timing → sample cross-correlation ≈ 0 even though the
  notes are identical. Trust the byte-diff. A bit-identical round-trip `.sid`
  would need the song's *original* player version (usually unavailable).
- **Multispeed?** Search the `.prg`/`.sid` for the CIA speed-code
  `A2 xx 8E 04 DC  A2 xx 8E 05 DC` ($dc04/$dc05 timer). Absent ⇒ packed at 1×;
  the editor "speed multiplier" won't add back missing notes.
- **Don't "fix" sid2sng's speed-table parse leniently.** Its leading-0 / extend
  logic is load-bearing; making it lenient *truncates* the speed table (cost me
  the only 2 wrong bytes in an otherwise-perfect recover).
- **ChiptuneSAK `.sid` import** (the editor's `load_song` on a `.sid`) is a lossy
  6502-emulation reconstruction AND fails *silently* if the module isn't
  importable — it keeps the previous song and only updates the path. Always
  verify the load actually changed the buffer (songname/songlen/a pattern dump).

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

## Dance-cover batch (approved by ear — exact recipes)
All from `sources/` (git-ignored). Each `.sng`/`.sid`/`.mp3` in `renders/`.
- **Sandstorm** — flat 16-bar loop → `--arrange darude --four-on-floor`, map
  `8,4,-`. The `--arrange`/`--four-on-floor` knobs were *built for this*: the
  cprato loop has everything on from bar 0 (no build) and only ~16 hats/16 bars
  (no floor). User: energy/beats now right.
- **Dance Monkey** — `--map 1,3,9 --kick-bass` (combined MIDI, classic 3-voice).
- **What Is Love** — karaoke MIDI; the vocal is the **`CANTO`** track (ch4), NOT
  the organ. `--map 4,2,- --mode clean` (clean bass, drums own voice). Earlier
  org-as-lead render had "no vocals"; the GM-program dump fixed it.
- **Going to Ibiza** — karaoke MIDI; the vocal is the **Flute** (ch5). `--map
  5,2,- --mode clean --fill 1` — the ch1 brass "whoa-oh" hook fills the vocal's
  rest holes. User picked the `--fill` version over riff-on-its-own-voice.
- The older `What Is Love.MID` (2010 GM, ch5 "Melody"=thin sax) is a weaker
  source than the `Haddaway_-_…` karaoke one; prefer karaoke MIDIs with a clear
  vocal track.

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
- **Default is 3-channel mono.** Dual-SID is OPT-IN via `--voice CH=ROLE=SRC`
  (CH 1-6; roles lead|bass|harm|counter|pad|drums|kick|snare|hihat|perc; SRC =
  stem file or `@N`/`@` from the combined MIDI) → a 6-voice stereo `.sng`
  (`build_stereo`); the editor auto-detects 6 channels on load. Without any
  `--voice`, everything stays 3-channel mono. No native "digi" 4th channel;
  drums are SID-synth (noise/tri). **Dual-SID does NOT export** (gt2reloc is
  single-SID) — audition only.
- **Don't cram two parts onto one busy voice** — a counter-melody jammed into the
  lead's note-gaps sounds wrong. `--fill` only fires on the lead's *long* holes
  (≥ half a bar), which is fine and is the Ibiza recipe; the failure mode is
  filling *every* gap. Fill from a deliberately chosen channel/stem.
- **For karaoke/GM dance MIDIs the winning mono layout is** lead=the *labelled*
  vocal channel, `--mode clean` (clean bass, drums own voice), optional
  `--fill RIFF` for the signature hook in the vocal's gaps. Channel-guessing by
  pitch picks the wrong lead — read track names/programs first.
- **Prefer named stem files over channel-guessing** when stems exist (the friet
  redo uses them; In The Navy still uses a combined MIDI + `--map`).
- Goal vibe: a rough, fun **C64 demo** soundtrack.

## Open next steps (user-requested directions)
- Chord-derived arpeggios (real chord tones, not fixed intervals).
- Make percussion louder / more present without crowding bass.
- Tame the busy intro drums.
- Song structure / proper looping; tempo from the MIDI's own tempo meta.
