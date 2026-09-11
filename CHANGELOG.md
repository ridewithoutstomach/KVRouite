# Changelog

All notable changes to KVRouite are listed here, newest version first.
The GitHub release page is shorter and written for users; this file is the
detailed record.

Versions up to and including 5.0 are documented in the GitHub releases only.

---

## 7.01 - 2026-09-11

A small follow-up to 7.0 for the application without the Voice add-on.

### Fixed

**Audio track and damper could not be saved without the Voice add-on**

In the Encoder Setup the whole page Audio was locked when the Voice add-on
was missing: OK wrote "Audio track in the exported video" and "Damp passing
vehicles" as off whatever was ticked, and a preset could not switch them on
either. Both are pure GStreamer and belong to the application - only
"Remove voices" needs the add-on. Now only the voice group stays grey;
audio track and damper are saved and applied as set.

**Console reported "Encoder-Setup canceled" after OK**

The main window compared the dialog result with the `accepted` signal
instead of `QDialog.Accepted`, so the debug line in the console was always
the cancel line, even after a save.

---

## 7.0 - 2026-09-11

Sound. Up to 6.14 the Encode-Mode wrote videos without a sound track; now
the track goes into the export, with the same crossfades as the picture,
and two tools work on it: a damper for passing vehicles and a voice
remover. The voice remover brings PyTorch and friends, about 900 MB that
most users do not need - so the Windows download comes in two parts, the
application ("Lite") and the "Voice" add-on. Around it: a view button on
the timeline, an "Audio Zoom" module, an export dialog that shows what it
is about to do, and a second page on the video control for marking where
someone talks.

### Added

**Sound track in the export**

Encoder Setup has a page "Audio": "Audio track in the exported video" and
its bitrate (AAC, 32-320 kbit/s, default 128). The crossfade of a cut
applies to the sound as well - the outgoing side goes to silence while the
incoming side comes up, so the mixer never adds two full tracks - and so
does the Merge-Fade at a file join. The AAC encoder is the first GStreamer
offers, avenc_aac ahead of voaacenc: voaacenc mangled the 6-7 kHz band of
wind noise into an audible squeal, avenc_aac at the same bitrate stays
clean (fdkaacenc, where a distribution builds it, comes before both,
mfaacenc last). Pure GStreamer, nothing to install; the preview still
plays the original sound (see Known).

**Damp passing vehicles**

The treatment of Kinotomo Audio by benilerouge.org - the method only, no
code: a stretch with a passing car or motorbike is turned down ("volume
original", here "Damper (dB)", 3-30, default 12 = a quarter) and the ride
noise from right next to it is laid over it ("volume added", here "Fill
level" 0-100 %, default 100), one continuous piece of the same length, so
wind and tyres stay and the vehicle recedes. With the fill at 100 the
stretch stays about as loud as before and only the vehicle is gone; at 0
it gets quieter by the damper, an audible dip. "Filter the fill" (off by
default) keeps only the low part of the copied piece, in case the mount
squeaks.

Which stretches are treated is decided by ear, not by a scanner. Mark
them on page A of the video control - `[-` and `-]` around the vehicle,
then **Vehicle** - and they appear as blue bands in the timeline and the
Audio Zoom. Right-click a band: **Listen …** renders 10 s before the
stretch, the stretch as it will be exported and 10 s after, small and
fast, and plays it in a window with Play, Stop and "Jump to stretch"
(3 s before it);
**Fill** chooses where the ride noise comes from - from before the
stretch (default), from after it, or none; "Start and end …" moves it,
"Remove" takes it away. Every change is on the Undo stack, the stretches
are stored per file under `vehicle_regions` in the project file. Without
marked stretches nothing is damped. **Detect** with "Passing vehicles" can
propose stretches from the sound level - dashed suggestions to check and
take over, or bands right away with the "mark" switch. It finds loud
passes, but on a windy or busy road it proposes most of the ride, so
nothing it finds is treated until taken over: what is treated stays a
decision by ear.

**Remove voices**

"Remove voices" on the page Audio separates the voice from the sound with
a trained model and keeps the rest: MDX-Net (the Ultimate Vocal Remover
model, default) or Demucs v4 by Meta, which was measured to leave more of
the ride noise. Runs on the CPU through python-audio-separator, roughly as
long as the audio it processes, in passes with a progress line and a
heartbeat; only the material that ends up in the video is read and
separated, and the result is cached per file and range. With marked
stretches (next item) it separates only there, with a 2 s margin.

**Detect and mark where someone talks - page A of the video control**

Encode-Mode with the Voice add-on and "Remove voices" on: the video
control gets a button at its left end, a film strip that turns into a
speaker. Page V is the control as it was. Page A shows [-, -], x and three
new buttons: **Voice** marks the area between [- and -] as a stretch with
voices (like "Ovl" makes an overlay of it), **Detect** opens a dialog, and
**Sens** sets the voice sensitivity 1-7 (1 clear speech only, 7 everything
that might be, default 3). In the Detect dialog you choose what to search
for - voices, passing vehicles or both, whichever the encoder setup allows
- and per kind a switch "also mark them for filtering (otherwise only
suggest them)". Only suggested finds are dashed frames - orange for
voices, blue for vehicles - and do nothing on export until taken over;
marked finds are solid bands, filtered right away, and a warning says that
marked finds are treated without another look. Voices come from Silero VAD
(run with ONNX Runtime; a 250 Hz high-pass in front of it for wind on the
microphone - for the search only, the exported sound is untouched);
vehicles from the sound level. Detection is never exact, so the finds are
meant to be checked. Marked stretches are orange (voices) or blue
(vehicles) bands in the timeline and the Audio Zoom; right-click one on
page A for "Listen …" (the stretch rendered as it will be exported, 10 s
before and after, played in a small window), "Start and end…", "Remove
stretch" and "Remove all". Right-click a dashed suggestion instead for
"Take over", "Listen …" (rendered as it would sound after taking it over)
or "Dismiss". **Vehicle** marks a stretch for the traffic damper by hand,
in blue - see "Damp passing vehicles". Right-click on page V still means
cut, overlay and join, nothing else.
Every change is on the Undo stack ("Voices marked", "Voices removed",
"Voices detected"…). Stored per file in seconds of that file under
`voice_regions` in the project file; exported as `voice_regions`, and the
voice remover then separates only the kept parts of these stretches. The
detection is never complete - a conversation in the wind can be missed, a
bird taken for a voice - so the bands are meant to be checked; without any
band the whole kept material is separated, as it says in the export
dialog. Without the add-on, or with "Remove voices" off, none of this is
shown.

**Audio Zoom - a module for the sound**

Selectable in any switchable window like Chart-Flow: the level of the
sound track around the playing position, a 60 s window (mouse wheel 8-900
s) that follows the video while the mouse is outside. Drag with the left
button to mark a stretch with voices, right-click a band to remove it,
click to jump. Cuts are drawn dark and hatched over it, and what lies
under a cut is neither shown nor counted. The `[-` and `-]` marks of the
timeline show here too, and Detect suggestions as dashed frames. Add-on
only.

**Timeline: a view button instead of a menu item**

A small button at the top left of the timeline cycles through "-" (nothing),
"Video" (the thumbnail strip), "Audio" (the sound level) and "V+A" (the
level, half transparent, over the thumbnails). The height of the timeline
does not change; the level fills to the bottom edge. The level comes from
the same scan as the traffic damper. With "Audio track" on in the encoder
setup the scan runs in the background as soon as videos are loaded - no
dialog, the curve grows file by file, with a line in the status bar and a
note in the timeline while it reads (it can take a while from a slow
drive). With "Audio track" off, choosing "Audio" scans on the spot
instead. Lite has this too - the scan is GStreamer. The setting
"Thumbnails in Timeline" in the Config menu is gone; its value is taken
over once.

**Export: the dialog shows the settings and the three sound switches**

Export in Encode-Mode no longer asks "Are you sure?" and nothing else. The
dialog lists the encoder settings as saved and has the three switches of
the sound track - Audio, Damp passing vehicles, Remove voices - to flip
right there, with a line under each saying what it will cost (the voice
remover: roughly as long as the audio, and whether that is the marked
stretches or everything). What is flipped here is written to the settings,
as OK in the Encoder Setup would; "Encoder Setup…" opens the full setup.

**Lite and the Voice add-on**

The Windows download comes as "KVRouite_<ver>_Win_x64" - the application,
with sound track, damper and the audio view - and
"KVRouite_<ver>_Voice_Win_x64", the voice remover and its detection (about
900 MB unpacked). The Voice zip carries the same folder name and is
unpacked over the KVRouite folder; the Voice installer does the same into
an existing installation of the same version and refuses any other.
Without it, "Remove voices" is locked with a note saying which file to get;
the self-test (`--selftest`) reports which of the two is installed. From
source it is the same split in three files: `requirements.txt` (the
application), `requirements-voice.txt` (the voice remover; PyTorch's CPU
build, no CUDA download) and `requirements-build.txt` (PyInstaller).
`build_with_pyinstaller.py` builds the application twice - once without
the voice packages, only to learn which files belong to them - and splits
the full build into the two zips and, with `--build-installer`, the two
installers. The macOS bundle is Lite. One package the library asks for,
diffq-fixed, is licensed CC BY-NC and is never shipped: the requirements
install KVRouite's own GPL stand-in under that name
(`tools/diffq_platzhalter`), and the build script refuses the original.

**Licenses**

All new components are named and their texts ship with the program:
python-audio-separator (MIT), the UVR models (MIT per the UVR README), Demucs
(Meta, MIT), the model architectures of tsurumeso, kuielab and ZFTurbo
(MIT, notices restored in `LICENSE.UVR-upstreams`), Silero VAD (MIT), and
the fifty-odd Python packages the library pulls in, inventoried per build
by `tools/lizenzen_sammeln.py` into `third-party-licenses/voice/`. Kinotomo
Audio is mentioned as a courtesy.

### Changed

**Python: 3.12.10 or newer, or 3.14**

The voice remover's packages have wheels for 3.12 to 3.14; 3.10 is no
longer supported. Building the executable needs at least 3.12.1: 3.12.0
has a bug (CPython issue 110543) that breaks scipy inside a PyInstaller
build, and the build script refuses it.

**Help > Copyright + License is a dialog of its own**

A scrollable text instead of a message box that grew with its content and,
since the voice remover, filled the whole screen. The sentence "By clicking
'I Accept'" is gone from it - it belongs to the disclaimer at the first
start, which now has to be scrolled to its end before it can be accepted.

### Fixed

**New Project left the last frame in the player**

The player stopped, but the last picture stayed and the drop hint did not
come back. Now the video area shows "Drag & Drop video file(s) here" again,
and the audio view and the Audio Zoom are emptied too.

**A squeal in the exported sound track**

On wind noise the AAC encoder voaacenc, first choice in the bundles,
mangled the 6-7 kHz band into an audible high squeal - measured 30 dB
below the source there but swinging wildly, and clearly heard. avenc_aac
is now preferred; at the same bitrate it reproduces the source cleanly.

**Undo of a cut did not refresh the Audio Zoom**

The darkened cut region stayed in the Audio Zoom after Ctrl+Z. Now it
clears with the cut, as in the timeline.

### Known

The preview plays the original sound: no damper, no voice removal, and the
crossfade snippets are silent. Only the export has the treated track.

---

## 6.14 - 2026-09-09

The join between two video files gets a transition that costs nothing: no
frame, no millisecond, no GPX point. Around it, the things that came up
while testing it - snippets that stood on their head when the playlist
mixed rotated and unrotated files, a chart that could not show a 20 cm
step at any zoom, a preview that seemed to hang while it pulled still
frames. And two conveniences long overdue: a library of encoder settings,
and Goto Start that walks backwards from edge to edge.

### Added

**Merge-Fade: a transition at a file join that loses nothing**

A crossfade needs overlap, and at a join between two files there is none:
the first video has ended, the second is only starting. A fade "centred on
the join" in the existing model would blend frame X into frame X - nothing
visible - and overlapping the two would eat a second of ride. So the
Merge-Fade blends stills: in the last half of its length before the join
the FIRST frame of the next video fades in as a still from 0 to 50 %, after
the join the LAST frame of the previous video fades out from 50 to 0 %. On
the join both sides show the same mixed picture - no jump, no black, no
slow motion, and the output is exactly as long as the sum of both files.
Nothing is cut, the GPX track stays untouched, there is nothing to undo.

Set it per join: right-click the blue join line in the timeline - the hit
zone is 10 px either side, checked in pixels so it is the same width at
any zoom; the line is highlighted under the pointer and the cursor becomes
a hand. The menu offers "Merge-Fade", "Hard join" and "Merge-Fade length…"
(default from Encoder Setup, capped at what fits up to the next cut or
the ends of the video). A join with a Merge-Fade is drawn in its own
colour, green, line and fade wings alike - white belongs to the crossfade
of a cut, orange to the hard cut, blue to overlays and to a hard join.
Whether a join gets nothing, a Merge-Fade or a cut is entirely the user's
choice - there is no rule that interferes.

Stored per join number under `merge_fades` in the project file, exported
as `merge_fades` in the encoder configuration, rendered on an own layer
between overlays and crossfade halves (`managers/ges_encoder_manager.py`).
The preview renders the same construction through the fade cache
(`core/fade_cache.py`) and inserts it as a zero-width entry at the join
(`core/ges_backend.py`). The still frames come from the new
`core/standbild.py`. Encode-Mode only, like every crossfade.

**Encoder Setup: presets**

One set of encoder settings used to be all there was; changing a field for
one export lost the previous values. The Encoder Setup now has a "Preset"
row at the top: choosing a saved set fills in the fields (OK makes them
active, as before), "Save…" stores the fields under a name (replacing
after a question), "Delete" removes one. The dialog opens with the preset
that matches the fields exactly, otherwise "(none)". A preset holds
resolution, container, hardware, CRF, preset, bitrate, FPS and X-Fade; the
source frame rate is not part of it. Stored in the settings under
`encoder_presets/<name>` with the same keys as `encoder/`
(`core/encoder_presets.py`).

**Close Gaps (Directions): elevation from Mapbox, or a straight line**

The transport-mode dialog has a checkbox "Get elevation from Mapbox",
checked by default and remembered. Unchecked, no terrain tiles are
fetched: the new points on the road get their height in a straight line
from the first to the last point. Because the points are spread evenly by
distance (constant speed), that is one constant gradient along the road -
what Close Gaps without Directions does on the straight line. Inserting a
point on the map with Directions on uses the last choice made in the
dialog.

**Goto Start: right-click jumps back to the previous edge**

The counterpart of the right-click on Goto End: to the previous cut start,
cut end or file join before the current time; with nothing before it, to
0.000 s; standing at the start, it wraps to the end, as the forward jump
wraps from the end to the start. Backwards the tolerance is 0.1 s, because
after a jump playback usually sits one frame behind the target and the
next right-click should reach the edge before, not the same one again.
Both buttons say so in their tooltips.

**Chart: axes follow the visible window when zoomed**

The height axis was always scaled over the whole track - 0 to 2757 m on
340 pixels is 8 m per pixel, and a 0.2 m step was invisible at every zoom;
zoom only worked horizontally. At zoom 1 the overview stays as it was.
Zoomed in, height scales over the visible points with 10 % margin and at
least 2 m of span; speed keeps 0 at the bottom and follows the window at
the top, so the 0 km/h line stays in the picture. The upper and lower
values of the window are written at the right edge (one decimal below
20 m of span). Points are drawn as small circles once they are 4 px or
more apart, as in the mini chart. The zoom limit follows the point count -
40 px per point at full zoom, about 25 points across the chart, never
less than the previous 50.

**Preview preparation says what it is doing**

Before a Merge-Fade snippet can be rendered, two still frames are pulled
from the sources - two to three seconds each with 4K material. That used
to happen before the preparation window appeared, so the application stood
still with nothing on screen. The fade renderer now starts one tick after
being asked, so the window is up first, and it reports "Taking the last
frame of … for the merge-fade…" in the window and the status bar before
each still.

### Changed

**Window title is just the name and the version**

"KVRouite v6.14" - the slogan after it is gone. With a project loaded, its
file name still comes first.

### Fixed

**Preview: crossfade snippets stood on their head when the playlist mixed rotations**

The fade cache rendered every snippet raw and the preview applied the
playlist's fixed rotation to it - which only worked while all files had
the same rotation. With one rotated file (GoPro mounted upside down,
`rotate-180`) and one without, the preview leaves the rotation to GES per
file, and a snippet, having no rotation tag, stayed raw: upside down. This
hit the Merge-Fade first, but an ordinary cut crossfade inside the rotated
file lay just as wrong. Snippets are now rendered upright, each piece with
its own file's rotation (`_RENDER_VERSION` 4, old snippets are rendered
anew), and the preview inserts them with `identity`. Verified headless
with rotate-180 test clips in both a uniform and a mixed playlist.

**Merge-Fade: the last frame of a GoPro file could not be taken**

The container of a GoPro file runs about 0.1 s longer than its video
track (the GPMF data tracks), and a seek to "duration minus half a frame"
landed behind the last picture. `core/standbild.py` now seeks one second
before the end and runs to the end of the video track, taking the last
frame delivered.

Note for anyone cutting test clips with `ffmpeg -ss … -c copy`: such
clips carry an edit list with a few discard frames at the start, and
GStreamer then drops the first frames after EVERY seek into the file -
three frames for a clip with four discard packets. Every stack change in a
GES timeline is such a seek, so a Merge-Fade showed three dark frames at
the join with those clips, while a plain concatenation did not. Cut test
clips with `-avoid_negative_ts make_zero`; measured, that removes the edit
list and the loss.

**Chart: edits in place were not drawn until the chart was scrolled**

The chart keeps its drawing as an image and redraws when a key changes;
of the data the key only knew the list's identity and length. Fix speed
spike, chT and smoothing change values inside the same list - same
identity, same length, old picture, until scrolling changed the offset.
`set_gpx_data()` now discards the kept image explicitly.

**Open Recent: an entry whose file is gone is removed**

The error message stays; after it the path leaves the list and the menu is
rebuilt. Entries are only removed on click, not at start-up, so a drive
that is merely unplugged keeps its entries.

---

## 6.13 - 2026-09-08

One day, one theme: the work of syncing a track against its video. The
same GPX point has to be looked at again and again, and every edit moved
it - so bookmarks remember it by coordinates, which nothing moves. The GPX
bar that does the marking sat under the table, far from the map where the
point is found; it can now sit under or over table or map, or float with
a grip. And the tools around the seam of a cut say more about what they
do. Two dark-theme faults and the browser menu on the map went on the way.

### Added

**Command line: `-?` lists the options**

`KVRouite.exe -?` (also `-h`, `--help`) prints the usage line and every
option with one sentence each, then exits with code 0. The list is the same
one the "Unknown option" message shows. It is printed before anything else
happens - before Qt, before the console is cleared and hidden for normal
operation - so it also appears in the packed exe started from a command
prompt.

**Command line: `-menuup` opens the `...` menu upwards**

Wanted for a tutorial recording: the `...` menu of the GPX bar sits at the
bottom of the window, and opened downwards Qt has no room, so it slides the
menu up over the button and the taskbar. With `-menuup` (or `--menu-up`) the
menu opens with its last entry directly above the button; measured, the
menu's bottom edge equals the button's top edge. Nothing else changes and
nothing is stored - the flag lives in `config.MORE_MENU_OPENS_UPWARD` for
the run and `_on_more_button_clicked()` in `widgets/gpx_control_widget.py`
reads it.

**GPX: Bookmarks - find the same point again without searching**

Syncing a track means looking at the same GPX point again and again, and
finding it again each time: before a cut it was row 1304, after it 1296,
and chT or "Cut GPX to video" move its time. What no edit touches are the
point's coordinates - only deleting removes it. A bookmark therefore stores
lat/lon and a name, nothing else. New menu **Bookmarks** (between GPX-Info
and Help) and the same menu on right-click in the map and in the GPX table.
On the map it replaces the browser menu (Back, Reload, Save page...) that
WebEngine showed until now, and it offers the point last clicked on the map
- the blue one - so a point found on the map goes straight into the
bookmarks. The table had no context menu before; chart and timeline keep
theirs. "Add bookmark for row N..." asks for a name, default `Row N`;
"Bookmarks..." lists them with Go to, Rename, Delete; below that one entry
per bookmark. Menu and dialog list
them in track order, not in the order they were set: each bookmark is
resolved to its current row first and the list is sorted by that, so a
bookmark set later on an earlier point comes first, the order still holds
after a cut, and every entry shows its current row. `Ctrl+B` bookmarks the
selected row, `Ctrl+1`..`Ctrl+9` jump to the first nine in that order
(`1`..`9` without Ctrl remain the playback speed). A jump selects the row the way a
click does, so map, chart and - with "Sync all with video" - the video
follow, and the status bar shows row and time. If the exact point was cut
out, the jump lands on the nearest point within 5 m and says the distance;
nothing within 5 m, and it says so instead of jumping anywhere. Bookmarks
belong to a GPX slot, because Slot 2 holds a different track with different
coordinates; loading a new track into a slot clears them. They go into the
project file (`gpx_bookmarks`, per slot). Search and defaults are in
`core/lesezeichen.py` without Qt; menu, dialog and jump in
`views/mainwindow.py`. Checked on 2026-09-08 with a harness on the real
window: set, jump back, point deleted -> neighbour at 4.5 m, far point ->
not found, json round trip, per-slot lists.

**Config: the GPX bar can sit under or over the table, under or over the map, or float**

Config > "GPX Bar Position" has five places for the GPX bar - the buttons
from `[-` to Smooth and Slot, and the info line with video time, GPX
length, elevation and the slope, zero and gap counts: Under GPX Table (as
before, the default), Over GPX Table, Under Map, Over Map, and Floating.
It is the same widget, only re-parented, so every signal, the red mark
buttons and the info values stay as they are. Docked, it is the first or
last element of the table's or the map's container; the map got the same
container the table has, and the module swap between the four windows
treats that container as the map. At the map and floating the bar is drawn
compact: buttons 22 px instead of 26, Kinomap logo 24 px instead of 48,
tighter margins - measured 58 px at the table, 44 px at the map.

Floating, the bar gets a grip on its left, like the Chart Flow in the
video picture, and can be dragged anywhere inside the window - over map,
table, chart or video; it is clamped to the window edges. It lives as a
child of the central widget, which Qt makes native there; measured with
WindowFromPoint on 2026-09-08, it lies visibly above the WebEngine map. It
starts where it used to be, at the bottom of the table, and stays on top
after a module swap. Its position is stored in pixels together with the
window area it was set in: at the same window size it comes back to the
pixel after a restart, at another size it is scaled. (A first version
stored only a fraction and applied it while the window was still tiny at
start-up; after a restart the bar sat somewhere else.) When it covers the bottom edge of the GPX table,
the table gets an empty margin of that height so the last row still
scrolls into view. Checked on 2026-09-08 with a harness: all five places
(parent, position in the container, height), drag by the grip, clamping,
stored position, back to the table with grip and margin gone.

### Changed

**markB / markE in the GPX bar: the point under the video, on request**

With AutoCutVideo+GPX off, markB and markE took the selected table row -
and only that. While the video runs, only the yellow bar moves with it;
the selection stays where it was last clicked. So markB landed on a row
that had nothing to do with the picture, or nowhere when nothing was
selected. Now, when the yellow row differs from the selected one, the app
asks: "The video is at row N (time), but that row is not selected. Set
markB on row N?" Yes selects that row the way a click does - blue on the
map, table and chart follow - and sets the mark; No leaves the marks as
they are, the old selection is not marked silently. When the yellow row is
the selected one, nothing changes; with nothing selected and no yellow
row, the status bar says what to do. With AutoCutVideo+GPX on the video
sets the marks itself, as before. `_gpx_zeile_fuer_marke()` in
`views/mainwindow.py`; checked on 2026-09-08 with a harness: yes, no,
same row, nothing selected.

**Fix speed spike: the ten points next to the seam, and a chart**

The dialog's table showed one row per 60 points on each side, and a mean
over 60 points can mislead: "60..1 before 19.3 km/h" next to a seam that
gets 15.0 km/h looked as if the seam came out too slow - until the GPX
table showed that the points right before and after the seam ride 15 km/h
themselves, and the faster stretch sat further away. The table now has a
row for the ten points nearest the seam on each side ("10..1 before",
"1..10 after"), the wider blocks follow ("60..11 before"). Below the table
a chart draws the speed of every point in the range, grey before and
coloured after, with the seam as a dashed line and its values as text; the
spike itself is clipped at the top of the chart so the rest keeps its
scale. Both recalculate when the ranges are changed. `zeilen()` and the new
`verlauf()` in `core/naht_glaetten.py`, `NahtDiagramm` in
`widgets/gpx_control_widget.py`.

**Shortcuts list moved from Edit to Help**

The shortcut overview sat in the Edit menu under Undo and Undo history,
where nobody looks for a help page. It is now Help > Shortcuts, right
after Show Documentation. The manual follows: the section with the picture
of the dialog moved from Menu Edit to Menu Help, with a fresh picture that
shows the two bookmark lines.

### Fixed

**Dark theme: the header row of the Shortcuts dialog was invisible**

The table header had a fixed light background (`#f3f3f3`), and in the dark
theme the light font stood on it: Action, Shortcut, Notes could not be read.
Header background, header font and the row lines now come from the theme
table (`kopfzeile`, `text`, `gitter`), so the dialog matches the GPX table
in both themes.

**Dark theme: a clicked GPX row turned black after leaving it**

Click a row, click the next one, and the first row's text was black on the
dark table. The yellow bar sets a black font on the row and remembers the
font it replaced, to put it back when the bar moves on. A click painted the
bar twice: `_on_table_selection_changed()` paints and reports the row, the
MainWindow answers with `select_row_in_pause()` on the same row, and the
second paint remembered the first paint's black as "the font before". The
memory is now taken only when the row does not carry the bar yet; a second
paint of the same row leaves it alone. In the light theme the same thing
happened and was invisible: black on white. Measured with a harness on
2026-09-08: after leaving, the row has no font of its own again, and a
dimmed row (point before the sync point) gets its grey back.

## 6.12 - 2026-09-07

6.11 went out as a pre-release; 6.12 is the release that followed two days
later, and most of what it adds came from one ride where the camera had
failed twice. Cutting the failures out of the video left three things
behind. In the preview, a crossfade at a GoPro chapter boundary was replaced
by a hard cut while the export rendered it; the preview now splits the fade
across files the way the export does. In the GPX track, each cut left a
speed spike at the seam, and where the camera had been off the track kept
running while the video did not; two new menu entries fix the seam and take
the missing time out of the track.

A second strand is the heights. In a half-open gallery even a barometric
recording is nonsense and no terrain model helps, so a section can now be
rebuilt by hand against what the video shows; Smooth works on a marked
range and says what it does; the Mapbox elevation no longer comes in
stairs. Along the way came an undo history with names, an export that can
be stopped, and videos that load in recording order.

### Added

**GPX: fix the speed spike a cut seam leaves behind**

When a camera failure is cut out of the video, the GPX points of that time
go with it, but the distance ridden in the meantime stays as one segment -
100 m in one second at the seam. New entry in the `...` menu of the GPX
bar: **Fix speed spike (cut seam)**. It works on the selected row, or lists
the spikes found in the track (segment longer than 20 m, at least three
times faster than the surroundings) and lets the user pick one.

The seam gets the missing time (distance divided by the surrounding speed),
and the same time is taken back from a range of points before and after by
dividing every step there by one factor. Speeds in the range rise by that
factor in their real proportions; positions, elevations and gradients are
untouched, and no point after the range moves, so the video stays in sync.
The range starts at 60 points per side and grows while the factor is above
15 % and the gradient stays within 2 percentage points of the seam; it can
be changed in the dialog, which shows before and after. Applying takes a
GPX undo snapshot; as with chT, video cuts can no longer be undone
afterwards. The computation lives in `core/naht_glaetten.py` without Qt.

**Export: a running encode can be stopped**

There was no way to stop an export once it ran: Close only closed the
window, the encoder kept the machine busy until it was done, and closing
the main window did not help either. Close on the encoder window now asks
"Stop the export?"; Yes stops the pipeline within 200 ms, deletes the
incomplete output file and closes the window, No leaves it running. The
main window's close button goes through the same question while an export
runs. The encoder window also reacts while rendering - it used to wake up
only with each percent line.

**Import: several videos go into the playlist in recording order**

The file dialog hands the files over in the order they were clicked, and
sorted by name GoPro chapters come out wrong: GX020039 after GX010042.
Several files are now ordered by the recording time from the container
(the same value ffprobe shows as creation_time; read in a millisecond),
and GoPro chapters of one recording by their chapter number - all
chapters carry the recording's time, chapter 2 of GX0042 even two seconds
before chapter 1. Where the container has no time, the file's creation
time stands in; the modification time is the copy time and is not used.
The order is printed to the console. Applies to the file dialog and to
drag and drop. `core/videoreihenfolge.py`, without Qt.

**GPX: right-click on `[-` / `-]` marks the gap of the last cut**

After a cut the marks are gone, and the next step is usually on the gap it
left - chT or the seam fix over the two neighbours. Right-click on `[-`
marks the point before the removed range, right-click on `-]` the point
after it, and shows it: row selected, map centred on it, chart on it, and
with "Sync all with video" the video too - the same as clicking the row.
The gap comes from Cut and Remove in the GPX bar as well as from
the video cut with V&G on; marking it is done in the GPX bar with V&G off,
the buttons are hidden otherwise. The gap is remembered as long as the
track keeps its point count; after another cut, Undo or a new track it is
forgotten.

**GPX: "Cut GPX to video (B..E)" - the camera was off, the track went on**

At a merge edge where the camera had been off, the video cut takes only
the seconds around the edge out of the track; the time the camera was off
is still in it, and from the seam on the track runs ahead of the video.
New entry in the `...` menu, V&G off: markB on the seam (right-click `[-`
after the cut), drive the video to a landmark, mark its GPX point as
markE. The entry takes the table time of markE minus the current video
time - the time the camera was off - and removes exactly that much track
after markB; everything behind moves up. markE then sits on the video
time. The seam keeps the distance ridden meanwhile, so the two right-clicks
and "Fix speed spike" follow. Refused when the point is not later than the
video or the cut would reach markE.

**GPX: Height profile editor (B..E)**

In a half-open gallery or on a viaduct even a barometric bike computer
records nonsense (Wahoo, 8 m downhill where the road climbs), and no
terrain model helps there: it measures the roof or the slope under the
bridge. What is known: the heights at both ends, the distance, and what the
rider sees in the video. New entry in the `...` menu: a window with the
profile of markB..markE, distance against height, the recording grey in
the background, B and E fixed, and a stretch of the recording before B
and after E with its grade, so one sees how the road enters and leaves
the section. A click on the line adds a support point,
dragging changes its height - snapping the grade before the point to
0.1 %, ten times finer with Ctrl held, and the arrow keys step it by
0.1 % (Shift 1 %, Ctrl 0.01 %) - right-click removes it, double-click on a
section types its grade. Two support points keep at least 5 m apart, and
the first half of a double-click no longer leaves a point behind. Every section shows its grade, the last one what
is left to E - so the first point already shows whether the rest can work
out. The kink at each support point is replaced by a vertical curve whose
length is set per point - long where the grade changes slowly, short where
it changes fast - by the mouse wheel over the point or the field below;
"Apply to all points" sets one length everywhere.
The window does not block: the video position is a dashed line in the
profile, a button adds a point there, and a click on a support point
drives the video to it. Apply writes the heights of B..E only, one undo
step; the calculation is in `core/hoehenprofil.py` without Qt.

**Edit: Undo history**

Ctrl+Z went back one step, but nothing said which step, or where to stop.
Every undo step now carries a name and a time - "Cut 1952.118-1954.118 s
(video + GPX)", "chT rows 1890..1893 (00:32:30.011 - 00:32:33.011)",
"Fix speed spike row 1892 (00:32:32.118)", "Smooth (whole track)" - and
Edit > Undo history lists them, newest first. Selecting an entry and pressing
"Undo to here" undoes that step and every step above it, after a
confirmation that says how many. The stack holds states, not actions, so a
single step cannot be taken out of the middle; taking back one cut on its
own remains what the timeline's right-click offers.

### Changed

**Smooth: a range when marked, and it says what it does**

Smooth always took the whole track, ignored markB and markE, said nothing
about it, and rebuilt the heights from point 0 - so the end of the track
drifted, and every further run flattened the track a little more without
anyone noticing. Now: with markB and markE set, only that range is
smoothed; the neighbours outside go into the averaging so the edges do not
kink, and the height of E stays - what the rebuild leaves over is spread
evenly along the distance. Without marks it is still the whole track, but
the dialog says so in its first line, with the point count, and the end
point stays too. The app remembers the last smooth: run it again on the
same heights and it warns, with time, parameters and the climb before and
after; change some heights in between - profile editor, chEle - and it
finds those rows itself and offers to smooth only them. The result message
shows the climb before and after. The summary goes into the project file
(not the heights), so the warning survives a reload; the changed-rows
offer needs the heights and does not. The calculation lives in
`core/hoehen_glaetten.py` without Qt.

**Elevation from Mapbox: between the pixels, at zoom 15**

The elevation fetch read the nearest pixel of a zoom-14 terrain tile. At
46° a pixel is 6.6 m wide, the points 3.3 m apart: two or three points got
the same value, then a step of 1.5 m, and the step became 50 to 130 %
slope. The height is now interpolated between the four neighbouring
pixels, and the tiles are zoom 15, the finest the tileset has. The result
is a continuous line without stairs; the resolution of the source itself
is unchanged, and an offset against the recorded track is still shifted
with Set height B..E.

### Fixed

**Project load: markB and markE came back invisible**

The project file stores markB and markE, and loading put only the two
indices back into the list widget: no red rows, no red buttons, no red
points on the map. Smooth, chT, ch% or Cut then worked on a range nobody
could see. Loading now sets the marks the same way as clicking does, after
the table and the map are built, so they show everywhere.

**Clicking the seam point of a video cut said "inside a cut segment"**

The point a video cut interpolates at the seam sits exactly on the cut
edge, but after the round trip through `datetime` it comes back up to half
a microsecond off. The jump from the GPX row to the video treated "exactly
at the segment end" with 1 ns tolerance, so depending on the direction the
point counted as just before the cut, was rounded to the cut start and
refused. The tolerance is now 1 µs, the resolution of the GPX times, and
the cut check compares on milliseconds like the jump time itself. Only the
jump changed; track and export are untouched.

**Preview: a crossfade at a file boundary was silently dropped**

The preview renders each crossfade once as a small clip
(`core/fade_cache.py`). A job knew one source file per side, and
`_make_fade_job()` gave up as soon as the 2 s window of either side ran into
the next file - a `[DEBUG]` line in the console, a hard cut in the preview,
no message. The export has no such limit: it splits every range across files
(`_Quellen.stuecke`) and renders the fade. So at exactly these places the
preview did not show what the export produces.

Seen on 2026-09-06 in the Stelvio project: a cut from 1 s before to 1 s
after the boundary between two GoPro chapters, default 2 s. The incoming
window started 0.3 ns before the boundary, was assigned to the first file,
and "ran into the next file". With 1 s it fit, so the fade only appeared
after shortening it.

A `FadeJob` now carries a list of pieces `(file, in-point, duration)` per
side, and `_make_fade_job()` splits each window across files the way the
export does. `_ges_start()` lays the pieces back to back on their layer; the
opacity ramp runs over the whole fade, each piece of the incoming side gets
the section of the ramp that falls on its place (support points in media
time, as `_alpha_rampe()` in the encoder). A piece without a whole frame - a
nanosecond remainder at a boundary - is dropped at rasterisation; a piece
whose source is a frame shorter than the playlist duration says is clamped,
and the next one follows without a gap. The cache key includes every piece;
the render version is bumped to 3.

## 6.11 - 2026-09-05 (pre-release)

Published as a pre-release only (tag `v6.11pre`); the finished release is
6.12 above.

Two strands. One is precision in the timeline: a cut or overlay could be
dragged, but nobody could see by how much, and a few milliseconds are not a
mouse movement. Dragging now shows the times, and after letting go the new
position stays as a preview that can be nudged by the millisecond and is
applied once. Along the way, moving a cut no longer throws away its crossfade
setting.

The other strand is the size of what ships. The bundles carried all of Qt -
Quick3D, Charts, Multimedia, the QML tree - because PyInstaller collects the
QML tree once WebEngine is involved, and the QML plugins pull the rest in. The
application never loads any of it. Both packers now keep only what the
imported Qt modules reach through their import tables, and check afterwards
that nothing left behind points into a hole. GStreamer is deliberately left
complete: which decoder a user's camera needs cannot be measured here.

### Added

**Timeline: the numbers while dragging a cut or an overlay**

While a cut edge, a cut block or an overlay is dragged, a label floats next to
the pointer: the moved edge to the millisecond (`Start 1765.123 s`, `End
1800.456 s`, or both for a block) and the difference to where it was, with
sign (`+0.005 s`). Three decimals match `round(a, 3)` at release - the cut is
not stored more precisely. The label sits at pointer height, to the right of
the pointer or to the left when there is no room; the timeline is 84 px high,
so a label above the pointer collided with the yellow line at the top.

**Timeline: fine adjustment after dragging, applied once**

Letting go no longer moves the cut. The yellow preview stays, and a bar next
to the moved edge offers `[<] [>]`, the position, the shift, `[tick] [cross]`.
Arrows and arrow keys nudge by 1 ms, with Shift 10 ms, with Alt 100 ms; Ctrl
is left alone because Ctrl+arrow pans the 360 view. Tick or Enter applies the
move - one `cutMoveRequested`, one undo step, one jump ahead of the edge as
before; cross or Esc discards it. Clicking an edge without dragging opens the
bar too, so no mouse tremor is needed to get in; clicking into the middle of
a block still only sets the marker. The edge can be grabbed again from the bar
and dragging continues from the current preview. A click elsewhere does
nothing but show a hint - accidental discarding was the thing to avoid. Shift
+ drag still pans a zoomed timeline while the bar is open.

Why not one move per click: a move is undo-and-recut, rewrites the GPX track,
takes an undo snapshot and seeks. Thirty clicks for 30 ms would be thirty of
those and thirty undo steps.

Overlays get exactly the same: label, bar, keys, and `overlayMoveRequested`
once on apply. Their fade-in and fade-out survive, because they hang on the
overlay, not on its position.

**Loading a project says which cuts are fixed**

Moving and undoing a cut need the record of what it removed from the GPX
track (`cut_points`, since 6.03) and a track fingerprint that still matches.
Until now the user learned that a cut is locked when the edge was already in
hand. `_alte_schnitte_melden()` runs after loading, only when a GPX track is
present, and reports one of three states: an old project with no records at
all, a mix (listing the cuts without record - this also happens in new
projects when a cut was set with AutoCutVideo+GPX off), or records whose
track no longer matches. Nothing is changed; the same text goes to the log
under `[CUT-REC]`.

### Changed

**Crossfade dialog steps in 0.1 s**

The spin box stepped by 0.5 s while 1.3 s could be typed. 0.1 s is the
resolution everything else uses (`_blende_abrunden`, one decimal in the
project file), so the arrows and the wheel now step 0.1 s; Page Up/Down step
ten times that, 1.0 s. The hint under the field says so. The other three
0.5-s fields (Move Cut, Overlay fade, Overlay start and end) are untouched.

**Build: Qt is cut down to what the application reaches**

Measured on the 6.01 Windows build: 130 Qt DLLs, 322 MB, of which the import
tables of the eight imported modules (QtCore, QtGui, QtWidgets, QtNetwork,
QtPrintSupport, QtWebChannel, QtWebEngineCore, QtWebEngineWidgets) reach 25.
`qt_abspecken()` in `build_with_pyinstaller.py` starts from those modules,
shiboken, `QtWebEngineProcess.exe`, `opengl32sw.dll` (the software renderer
behind `use_soft_opengl`) and the plugins of eight folders, follows the
import tables with pefile - PyInstaller's own dependency - and removes what
is never reached: 104 DLLs, the `qml/` tree, `qmltooling` and
`platforminputcontexts`, 157 `.qm` translations and the `.debug` variants of
the WebEngine resources that only a debug Qt loads. 179.8 MB less. All 53
WebEngine locales stay; which one Chromium loads depends on the user's
system. `check_qt_payload()` then walks every remaining DLL, module and
executable under `PySide6/` and verifies that each import resolves inside
the bundle or in `System32`; one unresolved import aborts the build.

The result: 903 MB became 718 MB, `PySide6/` 536 MB became 350 MB, the
portable ZIP 355 MB became 298 MB. Verified by starting the built exe with a
PATH of only the Windows folders and no Python or Qt variables, then listing
every module in the process: 462 from the bundle, 188 from Windows, none from
a venv or an installed Python. Map and WebEngine process ran; the selftest
passed with x264, NVIDIA H264 and HEVC.

`build_macos.py` does the same for `Contents/Frameworks/PySide6`, reading
load commands with `otool -L` through the functions of
`tools/pruefe_macos_buendel.py`. PyInstaller rewrites the references to
`@rpath/QtCore` with `@rpath` = `Contents/Frameworks` and resolves them via
symlinks it plants both in `Contents/Frameworks` and in `Contents/Resources`
- the latter through the directory symlink `Resources/PySide6/Qt/lib`. After
removing the unreachable frameworks those links point nowhere and sit in the
seal; `codesign --verify --deep` then says "No such file or directory" and
names only the bundle. The first GitHub run failed exactly there. Dangling
symlinks are now swept across the whole bundle before signing, and if the
seal check still fails, `siegel_diagnose()` lists every dangling link and
verifies each embedded part on its own. Removed per bundle: the unreachable
frameworks, the QML tree on both sides, two plugin folders and the Qt
translations. Workflow 3 passed on macOS 15 for both architectures and on
macOS 26 for arm64.

GStreamer stays complete on purpose. The largest plugins are WebRTC, AWS and
AI services that nothing here uses, but which decoder a user's file needs is
decided at runtime by GES and cannot be measured on this machine.
`qt/COMPONENTS.txt` records the new footprint.

**GStreamer plugin cache: one file per installation**

The plugin registry in the user's cache folder stores plugins with absolute
paths, and GStreamer keeps every entry whose file still exists - even in
another installation. Measured on 2026-09-05: a freshly built exe under
`dist/` loaded `gstpython.dll` from `C:\Program Files\KVRouite` on its first
start, because the installed version had filled the same registry file.
Anyone running the portable ZIP next to the installer mixed two versions.
`_registry_datei()` in `core/gst_umgebung.py` now appends eight hex digits of
the program folder's path (`gstreamer-registry-AMD64-fd5e690e.bin`), so each
installation has its own list. Counter-check: installed version started
first to refill the old list with Program Files paths, then the new exe -
it created its own file and loaded 462 modules from its bundle, none from
Program Files.

### Fixed

**Moving a cut kept the crossfade setting**

The crossfade length and the hard-cut flag hang on the key `(start, end)`. A
move is undo-and-recut, so the new cut had no entry and fell back to the
Encoder Setup default - the user who nudged a cut by a few milliseconds then
had to set 1.0 s again. `_schnitt_verschieben()` reads the setting before
the move and writes it under the new key afterwards. For the "not enough
room" question the carried-over length is placed under the new key for the
duration of the check, so the same calculation also asks whether *it* still
fits at the new place; nothing is shortened silently. A cut without its own
setting is not touched and keeps following the default.

## 6.10 - 2026-09-04

Why 6.10 and not 6.04: version numbers are compared part by part - by the
updater in the program, by GitHub, by pip. Under that rule `6.1` is the same as
`6.01` and *older* than `6.03`, which is exactly what the update check said
when a build was labelled 6.1. From here on the minor number always has two
digits: 6.10, 6.11, ... - never 6.1.

Two strands again. One is the window: the timeline could lose its own left
edge and never find it again, the right mouse button was doing two jobs at
once, the map forgot its route when moved to the other row, and the layout you
arranged was gone after every restart. All four are fixed, and the last one is
now saved.

The other strand is the macOS bundle. A user reported that 6.03 crashes; there
was no log, no version, no Mac to test on. What came out of a day of chasing
it is not the cause - that still needs one answer from the user - but a build
that proves properties of the file instead of assuming them, a second workflow
that runs the delivered bundle on a machine that never built it, and one hard
fact: the bundle needs macOS 15, not 13 as the README promised.

### Fixed

**Timeline: zooming all the way out shows the whole timeline again**

The visible part of the timeline is `[offset, offset + width]` of a strip
`width * zoom` wide. For nothing dead to show, `0 <= offset <= width*zoom -
width` must hold; at zoom 1.0 that means `offset == 0`. The lower bound was
checked in three of the five places that write `_horizontal_offset`, the upper
bound in none. `_center_marker_at_ratio()`, called after every zoom step, sets
the offset so the marker sits at 30 % of the window - after playing to 60 %
that is `0.3 * width` even at zoom 1.0, positive, so it passed: the timeline
was shifted left by a third although it fitted the window, the beginning was
cut off and the right side was black. Dragging with the mouse had no bound at
all, so the strip could be pulled into the middle of the window with dead time
left of 0. And nothing ever forced the offset back to 0.

One method, `_offset_begrenzen()`, clamps the offset into the allowed range
and is called after each of the five writes. At zoom 1.0 the range is `[0, 0]`.
Measured on the widget offscreen: zoom 1.0 after playing to 60 % gives 0
(was 300), dragging past either end stops at the edge.

**Timeline: the right mouse button only opens the menu now**

Since 6.03 a right-click on a cut or overlay opens a menu - and the right
button was also the way to drag the timeline. Qt sends the context-menu event
on *release* on Windows and on *press* elsewhere (documented), so the two
collided differently per platform: on Windows the menu popped up after a drag,
on macOS the menu came at once and the drag never started. Dragging is now
Shift + left button. Shift already meant "move horizontally" in this widget
(Shift + wheel), Ctrl means zoom (Ctrl + wheel), and each button has one job.
Measured with real mouse events: Shift+left pans and is clamped, left alone
moves the marker, right alone moves nothing.

**The elevation-profile handle no longer looks like a menu**

The handle in the video image was 18 px with three horizontal lines - the
universal sign for a menu. A left-click did nothing visible unless dragged, and
a right-click fell through the handle to the window frame behind it, which
showed its module menu (Video / Map / Chart ...). Two unrelated things at the
same spot. The handle is now a 2x3 dot grid, and it swallows right-clicks
(`contextMenuEvent` with `accept()`). The window frame's own right-click menu
is unchanged.

**The map keeps its route when moved to the other row**

`_modul_wechseln()` reloads the map's `QWebEngineView` when the map changes
row - on purpose, because reparenting gives it a new native window and the
compositor stays attached to the old one, leaving a white page. But a reload
starts `map_page.html` from scratch, so everything pushed into the page by
JavaScript was gone: route, points, current marker, B/E, zoom. Nothing sent it
again; `_on_map_page_loaded` only re-applies point sizes and API keys. The
result was Europe with no track. The data was never lost - `_gpx_data` in the
main window was intact - the map had merely forgotten what to show.

`MapWidget` now remembers the last GeoJSON it was given and restores it after
a reload it asked for itself (`neu_laden_und_wiederherstellen()`), together
with B/E and the current point, with `do_fit=True` so the map zooms to the
track instead of its start view. Done via `QTimer.singleShot(0)` so it runs
after the other `loadFinished` receivers. The empty reload for *New Project*
does not set the flag and stays as it was. Measured against the real page:
after the reload the widget sends `loadRoute(..., true)`, `set_markB_point`,
`set_markE_point` and the blue highlight.

**macOS: the bundle requires macOS 15, not 13**

Read from the delivered 6.03 archives, 940 Mach-O files each: 18 of them -
`QtGui.abi3.so`, `QtWidgets.abi3.so`, `libshiboken6.abi3.6.11.dylib` among
them - declare `LC_BUILD_VERSION minos 15.0.0`. The program itself says 11.0,
the Qt libraries 13.0; the PySide6 bindings set the floor. The wheels are
tagged `macosx_13_0_universal2`, the files inside are built against SDK 15.0.
On macOS 13 or 14 `pip install` succeeds and the application does not start.
README, release notes and the build check now say 15. This is the one lead
with evidence for the reported crash; whether it is the cause depends on the
user's macOS version.

### Added

**The window layout is remembered - which module sits where**

Size and position of the main window and all three splitters were already
saved. Which module lay in which of the four windows was not; every start put
map, video, chart and table back in their default places. A new key
`ui/module_layout_grid` (`ol:video,or:gpx,ul:flow,ur:map`) is written in
`_save_window_layout()` next to the splitter keys and applied in `__init__`
right after the default placement, before the window is shown - no native
window exists yet, so reparenting costs nothing. The splitter sizes follow in
`showEvent` and apply to positions, not modules, so they fit any placement.
*Reset Window Layout* removes the key and restores the default placement.

`_modulbelegung_anwenden()` refuses anything unusable rather than applying it
halfway - a missing window, an unknown module from another version, a module
twice, the video outside the top row - and the default stays. Measured on a
stand-in: the video side is switched first, then the three other windows via
`_modul_wechseln()`, the fourth module lands in the reserve by itself.

**Build: the bundle is checked for what only a user would find**

`tools/pruefe_macos_buendel.py` runs after the build against the finished
`KVRouite.app`: is it ad-hoc signed and fully sealed, does the architecture
match the archive name, does any of the ~940 Mach-O files reference a path
outside the bundle (`/opt/homebrew`, `/usr/local`, `Python.framework`), and
what is the highest minimum-macOS the bundle declares. Every one of these is
a property of the file and therefore true on every Mac. A finding aborts the
build. A check that examines nothing (no Mach-O found, `otool` missing) exits
2, never 0. The `otool` output parsing was tested against real samples.

**Workflow "3 - Fertiges Programm testen": the delivered bundle on a fresh Mac**

The build machine is useless as a test bench - Python, Qt and GStreamer lie
around there anyway, so a missing library is never noticed. The new workflow
takes the archive from a release or a build run, on a runner that did not
build it, with no `pip`, no `setup-python` and only `tools/` checked out. It
unpacks with `ditto` like the Finder, sets `com.apple.quarantine`, logs
`spctl`, removes the attribute again (the step the README asks the user for),
seeds the first-start dialogs via `defaults` (the ffmpeg hint comes *before*
the disclaimer, and Qt stores `hints/ffmpeg_missing_shown` as the flat key
`hints.ffmpeg_missing_shown` - read in `qsettings_mac.cpp`), then runs the
static check, a double-click via `open`, `--selftest`, and `--screenshot`
three times **with a real window** - not offscreen, which is where every hang
of the day turned out to live (Gatekeeper prompt, `NSAlert`, IconServices).
If a run hangs for 120 s, `sample` records where every thread stands before
the step goes red. Crash reports are always collected. The run ends at the
first error.

Result on the delivered 6.03: arm64 on macOS 15 and 26 clean, x86_64 on
macOS 15 clean, x86_64 on macOS 26 hangs in an XPC call to the IconServices
daemon on the runner (`actions/runner-images` #13882 lists macOS 26 Intel as
unstable). Zero external library references on either architecture.

### Changed

**All three macOS workflows run on demand only**

"1 - Quelltest" used to run on every push on four macOS runners; "2 - Bauen"
whenever a build file changed. Both are `workflow_dispatch` now, numbered so
they appear in order in the Actions tab. `gh workflow disable` / `enable`
switches them without editing files.

**Config menu regrouped**

*Window Headers* and *Elevation Profile in Video* moved from *View* to
*Config* - they are settings made once, like *Thumbnails in Timeline* next to
them, not views one flips. The bottom of the menu is now *Window Headers*,
*Lock Window Width*, a separator, *Reset Window Layout*, *Reset Config*. The
overlay's status tip said "lower left of the video image"; it has been
draggable since 6.03, and the text says so now.

**README: run from source is the recommended way on macOS**

The bundle is marked experimental. The source path has no packaging, no code
signing and no Gatekeeper between the user and the program, and it is the one
exercised by the source-test workflow. Both need macOS 15; the paragraph
telling macOS 14 users to right-click is gone, because on 14 nothing starts.

---

## 6.03 - 2026-09-03

Two strands. Taking a cut back arrived in 6.02 and only half worked. It was gone
after every *Open Project*, it produced a silently wrong track if cuts were
taken back in the wrong order, and it existed for middle cuts only. All three
are fixed, and the first and the last cut can now be taken back as well. On
that foundation the rest became possible: every cut can now be moved and
resized with the mouse, selected and removed with *Del*, and given its own
crossfade length. Overlays got the same treatment.

The second strand comes from two user reports. One found that the macOS bundle
had been changed after signing; the other could select his GPU in the encoder
setup and never export with it. Both were real, both are fixed - and both got
away because nothing was checking. The build plan now proves what it used to
assume, down to a counter-test that damages a copy on purpose to show that the
check has teeth.

### Fixed

**Undo Cut survives Open Project**

What a cut removed from the GPX track was recorded beside the cut list - but
only in memory. `save_project()` never wrote it and `process_open_project()`
never read it, so a loaded project started with an empty record and the first
check in `ruecknahme_moeglich()` greyed out every single cut. The message it
showed was written for older project files and said so, but it fired for every
file, including one saved a minute earlier.

The record now goes into the project file as `cut_points`. As a list and not as
a dict, because the key is a pair of numbers and JSON only has text keys; start
and end sit inside each entry and the key is rebuilt from them when loading.
Times travel as text (`json.dump(default=str)`) and come back with
`datetime.fromisoformat()` - the same route `gpx_data` has always taken.
Measured: `2025-01-01 12:00:00.123456` returns to the microsecond. Entries
without a start or without removed points are not taken over at all; they would
offer something in the menu that cannot deliver.

Older project files have no such key and behave exactly as before - and the
message about a project saved before this function existed is finally true for
them.

**The fingerprint of the track is saved, not recomputed**

This is the part that decides whether the record above may be trusted, and it is
easy to get wrong in the obvious way. Computing the fingerprint from the track
that was just loaded would always match, and every record would be released
unchecked - including in a project where `chT`, *Close Gaps* or *Resample* ran
between the last cut and saving. What is saved is therefore the fingerprint of
the last own action (`gpx_fingerabdruck`). If the loaded track does not match
it, the existing blocks in `ruecknahme_moeglich()` do their work, exactly as in
the session the cut was made in.

A check against the track itself was built first and then thrown out again: the
idea was that every middle cut leaves a seam at its start, so a missing point at
`beginn_dt` would betray shifted times. Measured, it does not - after a shift by
whole seconds a *different* point sits on the seam and the check passes. The
fingerprint from the file catches that case; see `check_cut_undo.py`.

**Cuts can be taken back in any order**

A record stands in the time frame the track had when the cut was made. Take an
earlier cut back and everything behind it moves - the records of the later cuts
then point into the void, and the track comes back silently wrong. Measured on a
track of 60 points with two cuts: taking the front one back first left 11 of 60
points off, with no complaint anywhere.

`aufzeichnungen_nachfuehren()` now moves the records that lie behind a change by
the same amount. It runs in three places: after a cut is taken back, after a new
cut is made in front of existing records, and after a start cut - which moves
the whole axis and therefore moves every record, not only those behind it. The
one exception is a start cut's own record: it lives in the frame from *before*
its rebasing and must stay put when a cut behind it is taken back, otherwise its
`beginn_dt` no longer points at the seam.

**AutoCutVideo+GPX is remembered**

Two causes, and they hid each other. The state was never saved; it was derived
when loading from whether a GPX/video shift stood in the file. That missed two
cases - switched on without a shift, and switched off with one, where loading
even turned it back on. And the derivation ran too early: it stood about fifty
lines ahead of the point where the edit mode is restored, and
`enableVideoGpxSync()` asks the edit mode:

    self._on_auto_sync_video_toggled(enable and self._edit_mode != "off")

At program start `_edit_mode` is `"off"`, so the wanted `True` became `False` -
the switch was not merely left alone, it was actively turned off. Loading a
project into a running session that was already in encode mode worked, which is
why it looked erratic. The state is now saved as `auto_sync` and restored behind
the edit mode. Older files fall back to the old derivation.

**Undoing the first cut switched AutoCutVideo+GPX off**

The first cut sets the GPX/video shift to zero, so taking it back has to put
the old value back. That was done with `enableVideoGpxSync(...)` - and that
function runs through `_on_autocut_toggle_clicked()`, which *toggles*. With
AutoCut already on, which is the normal case when a first cut can be taken back
at all, it therefore switched it off. The switch is now only touched when no
shift is set at all, exactly as `register_gpx_undo_snapshot()` has always done
it.

**A second `keyPressEvent` made the first one unreachable**

`MainWindow` had two methods of that name. In Python the later definition wins,
so the first one - roughly twenty lines - had never run. Nothing was lost with
it: `+`, `-` and `1` to `9` for the playback speed come from `QShortcut` with
`Qt.ApplicationShortcut` in `video_editor_widget.py`. Those work regardless of
which widget has the focus and also cover the numeric keypad and the `=` of
some layouts. The unreachable method is gone, together with the state only it
used (`vlc_speeds`, `speed_index`, `current_rate`), and the remaining one says
in its docstring where the keys actually live.

**The macOS bundle broke its own signature - twice**

A user analysed the 6.02 bundle and reported `a sealed resource is missing or
invalid`, followed by a list of files. The list was, line for line, our own copy
list: `build_macos.py` let PyInstaller build and sign the bundle and only
afterwards copied `ol.css`, `map_page.html`, `icon/` and the licence texts into
it. Everything that arrives after signing is outside the seal.

It went unnoticed because a build server cannot see it. Gatekeeper only looks at
files carrying `com.apple.quarantine`, which a browser sets while downloading -
a bundle built and started on the same machine has no such mark. And a broken
resource seal does not prevent starting: macOS checks the signature of the main
executable, which was untouched. The run was green and the bundle was broken.

Signing is now the last step that touches the bundle, followed immediately by
`codesign --verify --deep --strict`.

The second cause only showed up because of the new check: GStreamer wrote its
plugin list into `Contents/Frameworks/registry.bin` on first start, so the
bundle destroyed its own seal at the first double-click. Nobody in this project
asked for that path - PyInstaller does, in its own start-up script
`PyInstaller/hooks/rthooks/pyi_rth_gstreamer.py`:

    os.environ['GST_REGISTRY'] = os.path.join(sys._MEIPASS, 'registry.bin')

`sys._MEIPASS` is `Contents/Frameworks` in a macOS bundle. The first attempt at
a fix changed nothing, because it kept an existing value out of respect for the
user - and that value came from PyInstaller. A value now stands only if it does
*not* point into the program itself; the plugin list goes to the user's cache
directory (`~/Library/Caches/KVRouite`, `~/.cache/KVRouite`,
`%LOCALAPPDATA%\KVRouite`), where a cache belongs.

Windows was affected as well, and there the change fixed a second thing:
`GST_REGISTRY` and `GST_REGISTRY_1_0` held different values afterwards, because
the GStreamer wheel overwrites the second one. In that state the built EXE wrote
no plugin list at all and rebuilt it at every start. Measured on the 6.03 EXE:
before, no file anywhere; after, 1.69 MB in `%LOCALAPPDATA%\KVRouite`.

**GPU encoders were offered and could not be used**

A user with a VAAPI card reported `[ERROR] Render settings were rejected` -
before a single frame had run. *Detect HW* had offered `vaapi_h264`, and the
export refused it.

Both are right, and that is the point. Our detection builds a pipeline by hand
and names the element (`videotestsrc ! videoconvert ! vah264enc ! fakesink`);
naming an element ignores its rank. The export hands an encoding profile to
`encodebin`, and encodebin picks its elements from the registry, considering
only those from rank *marginal* (64) upwards. The VA elements ship with rank
*none* - deliberately, so that no software grabs a GPU unasked (Igalia, the
plugin's authors, on release 1.20: "GstVA elements are ranked NONE"). Our name
then acts as a filter on a list the element is not on, and the whole profile is
rejected.

Measured on 03.09.2026 with GStreamer 1.28.6, no GPU involved, by setting the
rank by hand:

    encoder        rank as shipped   rank 0      rank 64
    x264enc        256  -> works     rejected    works
    openh264enc     64  -> works     rejected    works
    x265enc        256  -> works     rejected    works

"rejected" is word for word the message the user reported. With ffmpeg this
could not happen: `-c:v h264_vaapi` is the choice, and there is no second way.
The chosen encoder is therefore registered before the profile is handed over -
raised to *marginal* for this program run only, nothing is stored. Verified on
an NVIDIA card put artificially into the same position: without the step the
export aborts, with it the same file comes out as with the original rank, byte
for byte (42815 bytes).

That also covers `d3d12h264enc`, `nvd3d11h264enc` and `nvautogpuh264enc`, which
carry rank 0 on an ordinary Windows machine.

**Detect HW tested a route the export does not take**

The gap above was possible because the two used different mechanisms. In the
ffmpeg era that could not drift apart. *Detect HW* now runs through
`_profil()` and `_rendern()` - the same two functions every export uses - and
writes half a second into a real MP4 file. What passes the test can export.
A GES test clip serves as material, so no source file is needed: 1.10 s for all
eight candidates (the hand-built pipeline took 0.65 s, the old ffmpeg test
6.90 s).

**No silent fall back to the CPU**

If the GPU encoder set in the encoder setup is missing, the export used to
switch to the CPU and say so only in the log. Whoever chooses a GPU wants the
GPU; a half-speed export behind the user's back is not a service. Since the
detection really exports, a missing element can only mean the machine changed -
card removed, driver gone, package uninstalled. That now produces a clear
message and no file.

**Why a profile was rejected is now readable**

`set_render_settings()` returns nothing but true or false. On failure the
encoder window now lists what the registry says about the three requirements:
target sink, muxer, and every encoder that can produce the wanted format, with
its rank, the selected one marked. The reason also travels in the error message
itself. This is what `gst-inspect-1.0` would show - without a terminal, and
without the `gstreamer1.0-tools` package, which Linux users are not asked to
install.

**Failed to load module: giolibproxy**

Printed at every start, on every platform. No file is missing; a search path is:
`giolibproxy.dll` needs `proxy-1.dll` (in `bin/`, found) which needs
`pxbackend-1.0.dll` in `lib/libproxy/`, and that subdirectory is not on the
search path. Two otherwise identical processes: without that directory error
126, with it the module loads. A packaging fault of the GStreamer wheels, not
ours - and the module is not needed, it reads the system proxy settings for
network access through GIO, while KVRouite reads local files and the map has its
own network stack. It is left out of the build now. Its neighbour `gioopenssl`
stays; that one loads fine.

**The Linux setup instructions were wrong**

`README.md` showed `python3 -m venv venv` as the active line and the correct
`--system-site-packages` variant commented out beside it - while three other
places in the project call that flag mandatory. Without it `import gi` fails and
the application does not start at all.

Also missing everywhere: `pip install --upgrade pip setuptools`. Python 3.12
removed `distutils` from its standard library, `fitparse` still needs it while
being installed, and since 3.12 `venv` no longer places setuptools in a new
environment. Debian-derived systems additionally ship a setuptools patched to
use the stdlib distutils - which no longer exists. Reproduced in a throwaway
environment with Python 3.12.0: without setuptools the install aborts; with
`SETUPTOOLS_USE_DISTUTILS=stdlib` it produces exactly the reported
`ModuleNotFoundError: No module named 'distutils'`; with a fresh setuptools it
runs through. The line is now in all five setup blocks.

### Added

**The first and the last cut can be taken back as well**

Both branches now record what they remove. The end cut was the small case: it
shifts nothing, it only cuts off the tail, so with `dauer_s = 0` the existing
`spur_ohne_schnitt()` handles it unchanged. One detail did need care - if the
cut falls exactly on an existing point, the seam point created there is a copy
of it and the track ends with two identical times. Undoing removes every point
on the seam, so the existing one has to be recorded too, or it is missing
afterwards. Both positions are checked separately.

The start cut needed two more fields, because it does two things more than the
others: it rebases the whole time axis onto the track's old starting timestamp
(`achsen_versatz_s`) and it sets the GPX/video shift to zero
(`video_shift_vorher`). Both are undone when the cut is taken back; without the
second the track would sit beside the video by the old shift.

Until now the start cut deliberately did not renew the fingerprint, which
blocked every undo afterwards - that was the safeguard against the shifted axis
producing silently wrong results. The shift is now compensated for, so the
safeguard could be replaced by the compensation.

**check_cut_undo.py**

Runs without a window and without video:

    python3 check_cut_undo.py

The question it answers is not "does something crash" but "does the GPX track
come back exactly as it was". That cannot be settled by looking: a track off by
fractions of a second looks right in the chart and only shows up when video and
track drift apart in the export. Twenty checks over five areas - order of undo,
the way through the project file, the block after changed times, the end cut and
the start cut.

Real is everything that matters: the recording, the undo, the following-up, the
reading and writing of the project file and the release check. Rebuilt are the
things that need Qt and a loaded video - applying the three kinds of cut to the
track, and the places where the program calls the following-up. Each of those
carries a note saying so.

**Cuts can be moved - with the mouse, and every kind of cut**

Grab the edge of a cut in the timeline to make it longer or shorter, grab the
block to move it as a whole. While dragging, nothing is computed: the black
block stays where it is and the new position appears as a frame with both
times. Only on release is the move carried out - it costs a recalculation of
the GPX track and possibly a freshly rendered crossfade, and doing that per
pixel would not be usable. Afterwards the player jumps to two seconds before
the new edge, so the result can be judged straight away. The same is available
as numbers through the right-click menu.

A move works the way one would do it by hand: **take the old cut back, then cut
again at the new place.** Both steps run through the functions that already
exist - the undo through `_ruecknahme_ausfuehren()`, the cutting through
`on_cut_clicked_video()` or, for the first cut, `_startschnitt_setzen()`. That
was the decision that mattered. A separate calculation for moving would have
been a second code path for the same thing, and it would have drifted away from
the first one; this way every improvement to cutting applies to moving as well.

For Ctrl+Z a move is one step. A flag holds back two things during the two
sub-steps: the inner undo snapshots, and the rebuilding of the preview - the
intermediate state would otherwise have crossfades rendered that nobody sees.

A cut keeps its kind. A middle cut cannot be dragged onto 0 or onto the end of
the video, because there it would turn into a first or last cut - and those are
trimmed away before encoding and treat the GPX track differently. The first and
the last cut each have one fixed edge for the same reason.

**A cut can be selected, and *Del* takes it back**

Click a cut and it is framed; *Del* takes it back through exactly the same path
as the menu entry, with the same checks and the same question. *Esc* drops the
selection, as does a click on empty space. A click that does not drag still
sets the marker, so nothing was taken away.

**Every cut can have its own crossfade length**

The value from the Encoder Setup is now a default. A cut can carry its own
length instead - right-click, *Crossfade length …* - and the menu entry shows
which of the two is in effect. This changes the video only; the GPX track is
not touched, because a crossfade lies centred on the cut and moves no times.

Little was needed for it, because the transport was already per cut: the
exporter writes `[start, end, xfade]` per cut, the preview receives
`(start, end, fade, path)` per cut, and `FadeJob.key()` contains the duration,
so different lengths get their own cached files by themselves. Only the source
was global - three places read `encoder/xfade` directly. Those three are now
one function, so preview, the handing over of finished crossfades and the
export cannot drift apart.

**A crossfade is only offered where there is room for it**

A crossfade lies centred on the cut: half of it comes from the kept material
before it, half from the material after it, and the other halves from the cut
itself. The upper limit is therefore
`2 x min(gap before, gap after, length of the cut)`.

What matters is that a gap has to serve **two** crossfades - the one of the cut
before it and the one of the cut after it. A gap therefore only counts half as
soon as there is another cut at its other end. With five seconds between two
cuts neither crossfade may be longer than five seconds; each then uses 2.5 s
and they touch without overlapping.

This is checked before every change to the cuts, not only when the length is
set - placing a cut next to an existing crossfade takes its room away. Nothing
is shortened silently: a set length is a decision of the user. Instead a window
names the affected cut, says how long its crossfade is and how much would still
fit, and offers exactly two ways out - shorten it to that value, or cancel. On
cancel nothing at all happens: no cut, no undo step, no changed length, so the
cut in question can be adjusted by hand first.

After loading a project the same check only reports. A project was consistent
when it was saved; if it no longer is, the default in the Encoder Setup was
changed in the meantime - and then it is even less our place to alter the
lengths.

**The timeline shows what a crossfade actually occupies**

Left and right of a cut block there is now a bright gradient over half the
crossfade length each, strongest at the edge and fading outwards, with a dotted
line at its outer end. That is exactly the material the crossfade takes from
the *kept* part. One sees why the question above appears - and does not get the
idea of placing another cut there in the first place.

Hard cut and crossfade are told apart by the hatching, not by the border. A cut
of a few tenths of a second is only a few pixels wide; a heavier border would
be almost the whole block and would make it look bigger than it is. The
hatching is scaled down with the block and stays honest in every width:
crossfade `/` light and wide apart, hard cut `\` orange and close together.

The opacity was measured, not guessed. A one-pixel diagonal is antialiased, so
roughly half of the set value arrives: at 105 the orange came out at 40 of 255
in the rendered image and was hard to see, at 160 it is a good 60 and reads
immediately.

The first and the last cut are now always drawn - and named in the menu - as a
hard cut. They are trimmed away before encoding and never had a crossfade; the
menu used to tick *With Crossfade* for them and then refuse the click.

**Overlays can be moved and resized on the timeline**

The same grammar as for cuts: grab an edge to change start or end, grab the
block to move the whole overlay, applied on release. The stops are the kept
segment it sits in, minus the room the crossfades next to it need. Selecting
and *Del* work as they do for cuts, and only ever one of the two is selected -
*Del* has to be unambiguous.

`update_overlay()` used to refuse changing the times, with the note that they
"have to be checked against cuts and crossfade margins, which this method
cannot do". That check sat inside `add_overlay()`; it is now `zeiten_pruefen()`,
and creating, moving and dragging all go through it. Two hard rules: the overlay
has to fit completely inside **one** kept segment, and the room for the
crossfades at both ends of that segment has to stay free. That check also had to
learn about the per-cut lengths - it was still asking the global value.

**Fade in and fade out of an overlay**

Right-click an overlay, *Fade in … / out …*. Unlike a cut these fades lie
*inside* the bar - an overlay fades in at its own beginning - so the timeline
draws them as ramps rising and falling within the blue bar. At a glance one
sees how much of the overlay is fully visible at all; with a short overlay and
long fades that is surprisingly little.

Together they can never be longer than the overlay. If an overlay is dragged
shorter than its fades, they are scaled down with it - a fade lasting longer
than the overlay could not be rendered.

**The build plan proves the macOS bundle instead of assuming it**

Everything below runs against the *unzipped shipping archive*, not against the
build directory - so the order cannot be wrong by accident: signed last, packed
after that, and only the unpacked result is touched.

  * the signature and the completeness of the seal, as a hard stop
  * a counter-test: a copy is deliberately damaged the way it happened to us -
    a file added afterwards. If `codesign` does not report that, the run stops,
    because then the check above proves nothing
  * what Gatekeeper will say to a user: the quarantine mark is set by hand and
    `spctl` is asked. Without notarisation it says no - the point is *what* it
    says
  * the self-test in the shipped bundle
  * three proof pictures of the running window
  * whether running changed the bundle - the check that found the plugin list

**--screenshot: three pictures of the running program**

The build plan could show two things: that the self-test passes, and that the
process is still alive after 25 seconds. Neither says whether a window stands or
whether anything moves.

`nachweis.py` now does what a user does: load a GPX track and a video, press
play, and take three pictures two seconds apart. Side by side, the ball in the
test video and the playhead show that playback really ran; a single still could
be a frozen window. The pictures are taken by Qt itself (`QWidget.grab()`), not
by a screen recorder, so they also work with `QT_QPA_PLATFORM=offscreen` where
there is no screen at all. That only works because the application paints the
video itself - GStreamer delivers the frames through appsink.

Two obstacles on the way. Loading a video asks three questions (edit mode,
output frame rate, video/GPX sync), each with `exec()` waiting for a click.
Rebuilding the steps around them was tried and dropped - the second question
sits one level deeper, and every rebuild moves the proof away from the route a
user actually takes. The real route is taken now and the questions are answered
automatically, "Edit video" explicitly with *Encode*.

And the window: without a screen Qt reports a tiny virtual display, and the
application sizes its window from it - 796x428 on the build server, at which the
grid squeezes everything together and the map gets no room at all. The pictures
looked like a broken program when only the window was too small. The proof mode
sets 1920x1200, which produces the same picture as on a normal machine. This
affects the proof mode only.

**The self-test really uses the hardware encoders**

Step 6 sends every encoder that *Detect HW* reports through `ges_xfade_main()`
once and measures the result. Until now only `hardware_encode: "none"` ever ran
there - the user's route was never tested.

### Changed

**Derived values no longer go into the project file**

`recalc_gpx_data()` writes `delta_m`, `speed_kmh` and `gradient` for every point
unconditionally and reads none of them, so in the record they are lost bytes.
Measured on `maptest2.KVRouiteproj`: the records shrink from 3384 kB to 1922 kB,
43 percent. The track itself is untouched - this is only about the recorded
points.

**Right-clicking an overlay opens a menu**

It used to ask *"Remove Overlay?"* straight away. Since an overlay can be moved
and has its own fade lengths, removing is only one of several things one might
want. Removing still asks - it is one step further in.

**Set Begin no longer reports success**

After a first cut a window said *"Video and GPX cut at 140.66s"*. It only
stated what the timeline shows anyway and had to be clicked away every time.
The message for a marker sitting at zero, where nothing happens, stayed -
without it the button would look broken.

**Call options take one dash or two**

`-v` has been there from the start, `--selftest` came later; whoever got used to
one should not trip over the other. `-v`, `--v`, `-verbose`, `--verbose` are now
the same, as are `-selftest` and `--selftest`. The previous check searched the
whole command line for the text `" -v"`, so `-verbose` slipped through
unnoticed.

An unknown option is now reported with the list of known ones and return code 2,
instead of being swallowed while the program starts normally - a typo like
`--seftest` used to open the window and say nothing.

**The encoder table exists once**

`_HW_ENCODER` in `managers/ges_encoder_manager.py` was a word-for-word copy of
`GST_HW_ENCODER` in `core/hardware_detect.py`, while the comment on the latter
claimed it was the only one. Exactly the kind of duplication where the two sides
drift apart and the detection ends up checking something other than the export.

**English in the self-test and in the encoder window**

`selftest.py` printed German throughout - it is the output of
`KVRouite --selftest`, which reaches users. Four more German fragments in the
encoder window are gone as well: `... bei 1920x1080`, `noch ca. 12s`,
`Fertig in 41.2s` and `Encoder x265enc fehlt. Unter Linux: ...`.

---

## 6.02 - 2026-09-02

The window was rebuilt. Until 6.01 the layout was fixed: video and map on the
left, chart and GPX table on the right, and the timeline squeezed in beside the
video. It is now three rows, and what sits in each of the four windows is up to
the user.

### Changed

**The timeline runs across the full width**

It used to live in the left column and was therefore tied to the width of the
video - about 920 of 1900 pixels. On a 35 minute video that is 2.3 seconds per
pixel. Across the full width it is 1.1. The widget itself needed no change at
all: it computes everything from `self.width()`, so moving it was enough.

**Four windows, contents of your choosing**

The layout is now a grid: two windows on top, the timeline across the middle,
two windows below. Each window holds one module - Map, Chart, Chart-Flow or GPX
Table - and you switch it with the small handle that appears while the mouse is
over the window, or by right-clicking it. Picking a module that currently sits
somewhere else swaps the two windows.

Four modules share three switchable windows, so one is always out of sight; at
startup that is the chart flow.

The video is the exception. It stays in the top row and only changes sides,
because it renders into a native window handle (`winId()`): moving it to another
row re-creates that window and the picture is gone. Swapping sides is a change
of index within the same splitter and costs nothing. The map has the same
problem for a different reason - it is a `QWebEngineView` - and reloads itself
after a row change.

**Every module carries its own controls**

The player buttons sit under the video, the GPX button bar under the table. Both
used to sit elsewhere, and a module that changes place would have left its
controls behind. It also keeps the top edge of each window free, which is where
the switch handle appears.

**The mini chart became a module of its own: "Chart-Flow"**

It was a strip beside the timeline and is now a full window. It is not a zoomed
version of the big chart, and cannot be: the big chart scales its elevation axis
across the whole track, so a five metre crest is a flat line. The flow scales
only over the points currently visible, which is why a crest fills the frame -
exactly what you need in order to see whether the video is going over the hilltop
at the moment the profile says it is.

The marker stays at 70% of the width and the points travel underneath. Ctrl and
the mouse wheel set how many GPX points are in view (8 to 400, 40 by default).

It also follows along while the video is paused. Clicking a point in the chart,
in the map or a row in the table moves it - previously it only tracked during
playback.

**Elevation figures are gone from the flow**

Only the gradient is shown at the current point. That is the value you compare
against the picture; metres above sea level say nothing about what you are
looking at.

**Every text in the program is English again**

The features built on 31 August and 1 September were written in German: the
View and Config menu entries "Fenster-Kopfzeilen", "Höhenprofil im Video" and
"Vorschaubilder in der Timeline", the right-click menu on a cut, the dialogs of
the cut undo, both overlay dialogs, the messages drawn into the video picture in
360 mode, several tooltips and the export log. All of them are English now. The
German wording only remains in comments, docstrings and console output, none of
which reaches a user.

**A new icon for the video/GPX sync button**

The old one packed a map pin, a video frame and two arrows into 25 pixels and
was taller than every other button in the bar. It is now a map pin inside the
two sync arrows at 20 pixels, the same height as the cut buttons beside it.
The red background that marks "no sync point set yet" is unchanged.

**The hint about the sync point shows the button**

Answering "No" to the sync question used to end with "click on the red button",
which left the user searching a bar of a dozen buttons. The hint now carries a
picture of the button underneath the text. The picture is taken from the live
button when the hint opens, so it stays correct if the icon changes again.

**GSync button 5 pixels wider**

It was fixed at 45 pixels while the label needs more, so the G was clipped.

**Button symbols follow the colour scheme**

The symbols are single-colour drawings on white or transparent ground - black
lines that vanish on a dark button. They are now recoloured at runtime: the
darkness of a pixel becomes its opacity, so only the drawing is left and it is
painted in the colour that fits. Whether a symbol is recoloured is decided by
its measured saturation, not by a list: below 60 it counts as a line drawing,
above it stays as it is. That is why the red and green VG marks are untouched.

The same applies to Play, Pause, forward and back. Those are not files at all
but symbols of the Qt style, which draws them black regardless of the palette.

Two buttons in the GPX bar carried emoji: the scissors as U+2702 followed by
variation selector 16 - the explicit request for the emoji rendering, which
Windows paints in its own colour and which ignores the text colour. With the
text variant (U+FE0E) the colour disappears: 63 coloured pixels became 0. The
minus sign U+2796 stays an emoji even then, so it is a plain em dash now.

**Chart position marker is quieter**

The marker was a 2 pixel line in pure white across the full height. Against the
chart ground that is a contrast of 15.9:1 - it read as a bar rather than a
marker, especially at the very left where it sits while the position is at
zero. It is 1 pixel now and slightly transparent, which brings it to 7.8:1.

It disappears where it crosses the yellow elevation curve, but that was true
before as well: white on yellow is 1.07:1 either way.

**ffmpeg is looked for the same way on every system**

There were two functions with different order and different places, and Linux
had no list of its own at all. There is one now: the folder set by hand, then
the PATH, then the usual places of the system - `/opt/homebrew/bin` and
`/usr/local/bin` on macOS, the Program Files folders on Windows, `/usr/bin` and
`/snap/bin` on Linux.

**Fallback fonts for macOS and Linux**

The help and version windows asked for Segoe UI and Consolas, which exist on
Windows only. On a Mac the request fell through to a generic name Qt does not
know under that alias. The lists now continue with Helvetica Neue and Menlo,
then DejaVu, then the generic family. Windows is unaffected - measured: Qt picks
the same font as before, because Segoe UI and Consolas still come first.

### Added

**A cut can be taken back - any cut, not just the last one**

Right-click a cut in the timeline. The menu names it by its time, switches it
between a crossfade and a hard cut, and offers *Undo Cut*.

Taking a cut back has to put the GPX track back too, and that is where the work
was. What a cut removed is recorded beside the cut list, under the same rounded
(start, end) key that `_hard_cuts` already uses - `_cut_intervals` stays a plain
list of time pairs, because it is unpacked at around 18 places in the program
and must not change shape. Recorded per cut: the removed points with their
original times, the points the ordering check additionally dropped (they would
otherwise be gone for good), the point interpolated at the seam if there was
one, and how far everything behind it moved forward.

The keys stay valid because cuts are stored in RAW time. If an earlier cut is
taken back, only the place where a later one ends up in the finished video
moves - not its key.

Whether taking it back is still safe is decided by a **fingerprint of the
track**, not by a counter. A counter would have to be maintained in every
editing function, and a single overlooked place would produce a false promise;
a fingerprint cannot overlook anything. There are two of them, because not
every change weighs the same:

- **Times** decide the structure. The undo works purely by comparing times, so
  if those have moved the points would land in the wrong place. Hard block.
- **Values** - position and elevation - change nothing structurally. The points
  come back in the right places but carry the state from before the cut, so
  after a smoothing or an elevation change there would be a step in the
  profile. That is visible in the chart, so a warning is enough.

Measured, not assumed: `_apply_smoothing()` only works over elevation and the
distances and never touches `time`. Changing times, Close Gaps and Resample do -
exactly the cases that belong behind the block.

**Adjacent cuts make one crossfade, not two**

Where two cuts touch or overlap, the video has one hole. Two crossfades were
built for it, and the inner one faded onto material the neighbouring cut had
already removed - a brief freeze at the joint. The preview now works on the
merged ranges, which is what the export has always done
(`_compute_keep_intervals()` merges them itself), so the export was never
affected.

**The cut you clicked is highlighted**

Brightened slightly, with a dashed border, for as long as its menu or the
confirmation is open. With several cuts close together there was otherwise no
way to tell which one was meant.

**A filmstrip in the timeline - Config > Thumbnails in Timeline**

Single frames of the video drawn along the timeline, so that a cut can be
placed by looking at the picture rather than at the clock.

**Off by default**, deliberately: the images are pulled out of the video files,
and with large material that costs time and disk access. Whoever wants them
switches them on.

Two things make it fast enough to be usable, and both have to stay that way
(`core/thumb_cache.py`): the seek goes to KEYFRAMES (`Gst.SeekFlags.KEY_UNIT`),
otherwise the decoder has to work through everything up to the target frame;
and the pipeline stays OPEN per file, because rebuilding it for every image
costs several times the actual work. Measured on a 4K GoPro file - 11.9 GB, 35
minutes, on an external disk: 24 images at 160 px wide in 3.4 s, 111 ms each on
average.

Fetching runs in a thread of its own and reports back by signal; the timeline
only ever asks for what it wants to draw. Zooming and panning change which
timestamps are needed, but reloading waits until the movement stops - otherwise
the disk rattles on every notch of the wheel.

The timeline row now has a fixed height rather than a minimum, because the size
of the images depends on it. Dragging it to 300 px would mean re-fetching
everything and drawing huge images. The edges above and below still drag.

**Elevation profile inside the video picture**

*View - Elevation Profile in Video*. The flow can be shown over the video, bottom left,
dark and translucent. Drag it anywhere in the picture by the small handle in its
top left corner; the position is remembered between sessions.

It is positioned against the picture, not against the window: if the aspect
ratio of the video does not match the window there are black bars, and the
profile stays inside the image rather than sitting on a bar. Only the handle
accepts the mouse - the profile itself lets clicks through, so dragging the view
in 360 mode still works underneath it.

**Everything drawn over the video sits in the picture, not in the window**

The status texts in the video - "Copymode" while copy mode is encoding, "V&G:On"
for the video-and-GPX cut - used to be laid out against the edge of the widget.
When the aspect ratio of the video does not match the window there are black
bars, and the texts ended up sitting in them. They are now placed against the
image itself, each on a fixed line of its own, the same way the elevation
profile is. The 360 view can still be dragged underneath them.

**"Video before cuts" in the GPX summary**

The length of the original video, next to the length after cuts.

**A dark colour scheme - Config > Theme**

Until now the program set neither a style nor a palette; it took whatever
Windows handed it. That was the reason for the dated look, and for a mismatch:
chart `#222222`, timeline `#333333` and the video picture black have always
been dark, while the frame around them was light.

Two entries, Light and Dark, stored per user. Light is the default, so nobody
gets a different program without asking for it, and it is identical to what was
there before - checked by comparing the rendered window pixel by pixel.

The window title bar belongs to Windows, not to Qt, and has to be told
separately (`DWMWA_USE_IMMERSIVE_DARK_MODE`). Dialogs and message boxes are
separate windows too, so a watcher colours each one as it appears; otherwise
only the windows open at the time of switching would have followed.

What is deliberately NOT dark: the map. It is content, like the video picture,
and a dark map makes roads, contour lines and the GPX track harder to read.

**The loaded project in the window title**

`myproject.KVRouiteproj - KVRouite v6.01 - …`. The name comes first because
the taskbar and the window switcher cut from the right.

**macOS: there are binaries**

KVRouite is now built for the Mac, for both architectures:

    KVRouite_6.02_macOS_arm64.zip     Apple Silicon, M1 to M4
    KVRouite_6.02_macOS_x86_64.zip    Intel

Each carries `KVRouite.app` with everything it needs inside it, GStreamer
included. Nothing has to be installed first. `build_macos.py` builds it and
`.github/workflows/build-macos.yml` runs that build on Apple hardware.

The architecture is part of the file name, and it is not taken from the name of
the build machine - it comes from `platform.machine()`, so it states what was
actually built. The workflow then reads the architecture back out of the
finished binary with `lipo` and refuses to publish a bundle whose name does not
match its contents. Both names used to be identical, which meant the two could
overwrite each other and the checksum file would point at the wrong archive.

**macOS: the bundle proves itself**

`selftest.py` is new, and it runs inside the finished bundle - started from a
foreign working directory, the way a double-click starts it. Five checks:

    1  the bundled files are found        map, OpenLayers, icons, logo
    2  the icons load                     light and dark
    3  GStreamer and GES answer           x264enc, mp4mux, qtdemux, timeline
    4  GPX read, written, read back       values unchanged
    5  a video is cut and encoded         8s source, cut 3-5s, 6.00s h264 out

All five pass on Apple Silicon and on Intel. Cutting and export on a Mac are
therefore no longer an assumption; step 5 measures the result and checks its
length, codec and frame size against what the cut arithmetic predicts. Run it
yourself with `KVRouite --selftest`; it works on Windows and Linux too.

What this still does NOT establish: nobody has operated the application by hand
on a Mac. The runs are headless (`QT_QPA_PLATFORM=offscreen`), so the map, copy
mode and every mouse interaction remain untested. The bundle is also neither
signed nor notarised - Apple charges a yearly fee for that, and KVRouite is
free. Gatekeeper will call it unverifiable; opening it goes through System
Settings, then Privacy & Security, then *Open Anyway* - the right-click route
was removed in macOS 15 (Sequoia). Since 6.03 the bundle is ad-hoc signed with
a complete seal; the unknown-developer warning is what remains.

Defects found and fixed on this path: the ffmpeg menu wrote to a key the search
never read; the help windows asked for fonts that exist on Windows only; the
bundle could not find its own GStreamer, because the wheels work out their
paths from `site-packages` and a bundle has none (`core/gst_umgebung.py` now
rebuilds that environment from what is actually there).

### Removed

**Detach for video and map**

*Video (detach)* and *Map (detach)* are gone, along with `DetachDialog`. Both
moved a widget into a second top-level window, and both needed hand-written care
to survive it - the video renders into a native window handle, the map is a
Chromium view whose compositor texture belongs to the old window. The comment in
the old reattach code says as much: close the dialog in the wrong order and the
picture is gone.

With windows whose contents can be swapped, the feature has lost its purpose on
a single screen. 313 lines went with it.

A message filter in `KVRouite.py` that swallowed "belongs to QRhi" warnings is
gone too - those only ever appeared when the map was detached.
`AA_ShareOpenGLContexts` stays: its original reason is gone, but whether it
steadies anything else has not been measured, and it costs nothing.

**The two running times in the video picture**

The length of the original and the length after cuts were drawn over the bottom
left of the picture, in white and red on whatever happened to be there - on
bright asphalt they were barely readable. Both are in the GPX summary now, as
"Video before cuts" and "Video Duration".

**The mini chart beside the timeline**

Replaced by the Chart-Flow module, see above.

**The mpv source archive in `third-party-src/`**

4 MB of ZIP that no longer had to be there. KVRouite has not shipped an mpv or
FFmpeg binary since 3.25, so there is nothing left to supply the corresponding
source for; both build scripts now refuse to package a build that contains
either. What the versions up to 3.25 did ship is documented instead:
`third-party-src/README.txt` says which file belongs to which version, and the
BUILDINFO files record how those binaries were configured and built. Anyone who
received them can still ask for the source, which is what the GPL requires.

### Fixed

**Exported GPX files were signed "MyApp"**

The `creator` attribute in the GPX header, which says which program wrote the
file, carried a placeholder. It now reads `KVRouite v6.02`.

**GPX button bar sat above the table**

It now sits below it, matching the player. Beside being consistent, it keeps the
top edge free for the window switch.

**6.01 and 6.02 fought over the window layout**

Until 6.01 there was ONE horizontal splitter in the window (left | right);
since 6.02 it is a vertical one with three rows and two horizontal ones inside.
Both wrote their state under the same key, `ui/splitter_state`. Anyone starting
6.01 and 6.02 in turn got the other version's layout applied to their own
structure - the window stood wrong afterwards, and "Reset Window Layout" helped
only until the next switch.

The four layout keys are now called `ui/*_grid`. The old names are left alone
and belong to 6.01; both versions run side by side. Everything else in the
settings stays shared on purpose - encoder setup, map keys, ffmpeg path, file
history. It is the same machine and the same preferences.

**The ffmpeg menu did nothing on macOS**

The search at startup read `paths/ffmpeg_mac` there, but the menu
Config > FFmpeg wrote to `paths/ffmpeg` on every system. A folder set by hand
was therefore gone at the next start, "Show current path" displayed a value
nobody used, and "Clear ffmpeg Path" removed the wrong entry. Both sides now go
through the same four functions in `path_manager.py`, which know the name for
the system they are on.

**A folder with only ffmpeg was accepted**

Copy mode needs both programs - ffmpeg cuts on the keyframes, ffprobe indexes
them and measures the segment lengths. Only ffmpeg was checked, so such a folder
was taken and added to the PATH, and copy mode stayed off regardless. To the
user it looked as if setting the folder had done nothing.

Both are required now, and the message says which one is missing, with the file
name of the system it is on: "ffprobe.exe not found in: … Copy mode needs
ffmpeg.exe and ffprobe.exe in the same folder."

---

## 6.01 – 2026-08-31

Nothing was added and nothing moved. This release is about the application
getting out of the way, plus three defects that shipped with 6.0.

### Fixed

**Cut Begin cut too far into the video from the second file onwards**

`get_current_position_s()` returns the GLOBAL time across all files, but the
caller in `on_set_begin_clicked()` treated it as a time within the current clip
and added the offset of the preceding files a second time. From the second video
on, the cut was placed too late by the summed length of everything before it.
With two files and the marker in the second one, the computed cut end could
exceed the total length and the whole timeline went black.

`EndManager.go_to_end()` and the sync path were never affected - they use the
value directly. The same block sits commented out in `on_sync_clicked()`, so it
had been noticed there once before and fixed only in that one place.

**Cut End left the last frame of the raw video behind**

Cut marks come from `real_total_duration`, which is read from the mdhd box of
the file. The preview computes its keep ranges against `asset.get_duration()`
from GES. The two disagree by a fraction of a millisecond, so an end cut ended
just short of the raw end - and `_compute_keeps()` appended what was left as a
keep range of its own. That sliver was the very last frame of the raw video, and
because it was the final piece of the preview, *Go to End* and playback landed
on it instead of on the frame before the cut.

Keep ranges shorter than 10 ms are no longer created. At any frame rate up to
100 fps a range that short cannot hold a single complete frame, so it can only
ever be a rounding remainder between the two sources.

**An end cut could leave the map unusable**

See the map entry below - it is the same cause.

### Changed

**The map**

`ol.interaction.Modify`, the machinery behind the map's `Move` button, was
created at startup with `source:` and therefore listened to the point source for
the whole session, whether or not `Move` was ever pressed. Every change and
every removal of a point is reported to it, and its bookkeeping walks its entire
internal index for each one - `removeFeatureSegmentData_()` in `ol.js` builds a
full copy of the index and scans it linearly.

With a five-hour track at 1 Hz - about 17,000 points - that meant:

- reloading the map after a cut, a deletion or a GoPro extraction: **14 to 17
  seconds**, measured inside the map itself
- an end cut, which recolours every point after the cut through
  `mark_range_in_red()`: 16,000 of those scans, one after another. The map
  stopped responding.

It is now created when `Move` is switched on, over its own feature list rather
than over the source, and discarded when `Move` is switched off. In normal use
that index does not exist at all.

Two further changes to the map, both in `map_page.html`:

- Point styles are shared instead of built per point. OpenLayers caches the
  rendered circle image on the style OBJECT, so 17,000 individual styles meant
  the cache never applied and 17,000 circles were drawn separately - at load and
  again on every pan and zoom. There are only a handful of distinct styles.
- Features are inserted with one `addFeatures()` call instead of `addFeature()`
  per point.

**The elevation and speed chart no longer stutters the video**

`ChartWidget.paintEvent()` recomputed everything on every repaint - collecting
elevation and speed for all points, finding minima and maxima, building two
point lists, then drawing one line per point. At 17,000 points that is about
35,000 drawing calls, five times a second, in the same thread that paints the
video frames. Measured offscreen: **25 ms at 17,329 points, 42 ms at 28,800**.
A video frame lasts 33 ms at 30 fps.

While the video plays, none of the curves change - only the marker moves. The
curves are now drawn once into an image and reused; each tick copies that image
and draws the marker on top. Measured: **0.06 ms**. The image is rebuilt when
the data, size, zoom, offset, thresholds, sync range or GPX-video shift change.

**One timing loop instead of two**

The time display had its own 200 ms timer in `VideoEditorWidget` that queried
the player position a second time and ran against the marker timer. Marker and
time display could therefore show two different points in the same video. The
display is now refreshed from the marker tick with the position already
determined there.

**The stepper goes straight to its target**

Three things made stepping unsteady, all of them left over from the playlist
model of the previous video engine:

- `_position_ns()` returned `0` when the position query failed - which happens
  regularly during a seek or a state change. `0` is also a valid position,
  namely the beginning, so the caller could not tell the two apart, and that `0`
  reached the timeline marker. It now returns `None`, and callers fall back to
  the last known position.
- `seek_global()` split the target into clip index plus local second, compared
  that with the player's live index and, when they differed, first seeked to the
  START of the clip - position 0.000 s for the first clip - and only 100 ms
  later to the actual target. That was the visible jump to the beginning when
  stepping across a clip boundary. GES has one continuous timeline; the seek now
  goes straight there. `show_first_frame_at_index()` and *Go to Start* did the
  same thing twice as well, both times to the identical position.
- `get_current_global_time()` combined two separate position queries - the
  offset from one, the local time from the other. If they drifted apart, the
  result jumped by a whole clip length. It is one query now.

**A 200 ms timer from the mpv era is gone**

`VideoCutManager` checked five times a second whether the player had wandered
into a cut range and pushed it out. GES removes cut ranges from the timeline
physically, so a cut position cannot be reached at all - the timer could only
fire on a distorted position reading, and then it moved the picture on its own.
Its repair mechanisms went with it, including a monkey patch that disabled the
timeline marker for 50 ms at a time. About 150 lines.

**Seeks no longer block the interface**

Every seek waited for its own completion with a one second cap, in the GUI
thread. It now records that a seek is running and clears that on `ASYNC_DONE`
from the bus; while it runs, the position query answers with the seek target
instead of a measurement that would still return the old position. A seek that
would overtake a running one still waits - GStreamer rejects it otherwise and
the picture stays where it was.

*Go to End* and the end-cut handler fired the same seek three times, at 10, 100
and 250 ms. Once is enough.

**Dragging the timeline marker**

Every mouse movement triggered its own seek. At most one per 60 ms now; the last
position is always reached.

**Single-frame stepping above 30 fps**

The preview is capped at 30 fps. `step_frame()` computed its step from the
SOURCE frame rate, so with 50 or 60 fps material a step was less than one
visible frame and only every second press changed the picture. The stepper now
works in the frame rate of the preview - as does the edge arithmetic in
`StepManager`, so both use the same duration. At 25, 29.97 or 30 fps nothing
changes.

**Finding the nearest GPX point**

`get_closest_index_for_time()` scanned all timestamps on every call, twice per
200 ms tick - 0.74 ms at 17,329 points. The timestamps are ascending, so a
binary search does the same in 0.0004 ms. Whether they really are ascending is
checked while the list is built; points without a timestamp get 0.0, and if that
breaks the order the linear scan is used as before. 24,020 cases were checked
against the old search with no difference in result.

---

## 6.0 – 2026-08-30

### Changed

**The video engine was rebuilt on GStreamer Editing Services**

Up to 5.01 there were two playback paths and a separate render engine. Preview
and export now build the same GES timeline, so the preview shows what the
render will produce - cut ranges are gone from the picture and the crossfades
sit at the cuts.

- Crossfades are pre-rendered in the background while you keep working
  (`core/fade_cache.py`). Finished ones are reused; a cut without a rendered
  fade shows as a hard cut until it arrives.
- `core/player_backend.py` - the backend interface, the second implementation
  and the factory - is deleted. `VideoEditorWidget` builds `GesPlayerBackend`
  directly.
- Gone from the menus: *Config -> Video Backend* and *Config -> libmpv*.
- `path_manager.py` keeps only the ffmpeg helpers.
- The old render engine - `xfade_main()` with its pre-cutting, keyframe search,
  `copy_cut`, `crossfade_2`, concat, overlay encode and the VAAPI/NVENC
  parameters - is deleted, about 1200 lines. What remains of
  `managers/encoder_manager.py` is the export dialog and the segment length
  check that copy mode needs.
- **GStreamer is a startup requirement.** If it cannot be loaded, KVRouite says
  so with the exact reason and the install command for the platform, and points
  at `check_ges.py`, instead of failing later somewhere in the user interface.

**Rendering is much faster**

The old export ran in several passes over the material: pre-cutting the
segments, searching keyframes, rendering each crossfade on its own, joining
everything back together and, if overlays were used, encoding the result a
further time - with intermediate files at every step. GES builds one timeline
and renders it in a single pass.

Measured on the reference project - two GoPro files, 3840x2160 H.265 at
29.97 fps, 11.9 GB each, 70 minutes of raw material cut down to 4.4 minutes
with five cuts, three of them with a crossfade, and two overlays. Both renders
used NVENC hardware encoding on the same machine: about 15 minutes before,
about two minutes now.

That is a rough indication of the new engine, not a benchmark - the time
depends on the machine, the material and the encoder settings. The gain grows
with the number of cuts, because every cut used to add work of its own.

The Windows build is also about 100 MB smaller, since it no longer carries a
second video runtime or the render engine it used to ship.

**Copy mode uses the ffmpeg on your system**

Rendering runs through GES, so ffmpeg is only still used by copy mode, which
cuts on keyframes with `-c copy`.

- Copy mode is enabled only when **both** `ffmpeg` and `ffprobe` are in your
  PATH. It used to check only `ffmpeg`, so having just one of them led into a
  mode that failed at export.
- KVRouite says once at startup what is missing and what it costs, instead of
  leaving a greyed-out menu entry with no explanation.
- `path_manager` looks at your stored path, the usual Windows install locations
  and your PATH.
- `check_ges.py` treats a missing ffmpeg as a hint, not as a failure.

### Added

**True 360° video**

360° footage is stored equirectangular - the whole sphere squeezed into a 2:1
rectangle. Up to 5.01 KVRouite only cropped that distorted picture and moved
the crop around: no projection, no wrap-around across the 360° seam, no real
zoom - and the view never reached the export, which always rendered the full
distorted 2:1 image.

KVRouite now does the real thing with an OpenGL fragment shader
(`core/view360.py`), attached to each clip as a `GESEffect`:

- Look around by dragging in the picture, zoom with the mouse wheel, or use
  `Ctrl` + arrow keys / `Ctrl +` / `Ctrl -`, `Ctrl 0` to reset. Dragging is
  scaled by the current field of view, so it feels the same at any zoom.
- Straight lines stay straight, and panning across the seam is seamless.
- One viewing direction per video, stored in the project file (`view360`).
  *View -> Apply 360° view to all videos* copies it to every clip, which is
  what you want for material from one camera.
- **The view is rendered.** Preview and export build the same timeline, so the
  export produces a normal 16:9 video showing exactly what the preview showed.
  Crossfades work: both halves are projected and then mixed.
- Measured: the shader costs nothing noticeable in the preview (30.0 fps with
  and without it on 1920x960 material), and it changes no timing - the same
  project rendered with and without 360° gives the identical frame count and
  duration.
- If the GL elements are missing (`gstreamer1.0-gl` on Linux, or no GL context
  over remote desktop), 360° simply stays off and says why; `check_ges.py`
  reports it.

**Overlays**

Images can be placed on the timeline, positioned in the picture and are
rendered into the export.

### Removed

**Street view and the create mode**

The street view pane was only ever visible inside the create mode, and the
create mode existed to place GPX points next to it. Both are gone, together
with the Mapillary key entry. Building GPX points still works: *new points at
video time* and *directions* remain as their own menu entries.

### Fixed

**Loading a second project could stall the preview**

Loading a project while another one was open started the crossfade
pre-rendering in the middle of the load - still in the mode of the previous
project - and could leave the progress window waiting forever. Two causes, both
fixed: the preview is no longer rebuilt while a project is loading, and the
render loop can no longer stop without reporting a result.

**The keyframe index travelled between projects**

The index was written into the project file and only ever cleared by *New
Project*, so a project could carry the keyframes of videos that were no longer
loaded. It is no longer stored: when a project is loaded the index is read
directly from the video files, which takes milliseconds, and it is dropped when
the playlist changes. Project files are much smaller as a result.

---

## 5.01 – 2026-08-28

### Added

**Step along the cut edges**

The stepper button next to the forward/back arrows has a fifth setting: `c`.
It walks the video from cut edge to cut edge, frame by frame. Every cut gives
two stops - the last frame before it and the first frame after it - so you can
look at both sides of a joint and judge how the cut will play before rendering
anything. The first and the last frame of the finished video are stops as well.

`c` works in Encode Mode. There a keyframe is forced on every cut, so the two
frames you see are the ones that will end up next to each other. Copy Mode cuts
at the nearest keyframe instead, so the marked edges would not be what you get -
pressing the arrows there explains that and nothing moves. Use step mode `k` in
Copy Mode to see where the cut will really land.

The multiplier has no effect in `c`; it always goes one edge at a time.

**Hard cut instead of a crossfade**

In Encode Mode every cut is bridged with a crossfade. A single cut can now be
switched to a hard cut: right-click the black cut block in the timeline and
confirm the question. A hard cut is drawn with orange edges, so you can see at a
glance which cuts will blend and which will jump.

The cut position and the total length of the video do not change – only the
transition does: instead of blending the material before and after the cut, the
video jumps directly. The setting is stored in the project file and can be
reverted with Undo (Ctrl+Z).

While rendering, the encoder window now lists every cut and how it will be
produced:

```
[INFO] Cut 0.00s - 3.00s: trimmed away (video start)
[INFO] Cut 12.00s - 18.00s: hard cut (no crossfade)
[INFO] Cut 27.00s - 30.00s: crossfade 2.0s
```

Copy Mode has no crossfades at all, so there is nothing to switch there. The
first and the last cut cannot be switched either – they are trimmed away before
encoding and never had a crossfade.

**Lock Window Width (Config menu)**

Buttons appear and disappear while you work – when you switch to Edit mode, for
example. The window used to widen itself and the layout jumped. With this option
on, the window is measured once in its widest possible state and that width is
kept as the minimum. Nothing jumps any more. The window can still be enlarged by
hand, it just cannot be made narrower than the toolbars need.

On a small screen the reserved width can be wider than the screen itself – leave
the option off there.

**Reset Window Layout (Config menu)**

KVRouite now remembers the window size, the window position and the position of
the splitter – the divider between the left half (video and map) and the right
half (chart and GPX list) – when you close it, and restores them at the next
start. So the window only has to be arranged once.

This new menu entry forgets all of that and returns to the delivery state:
default size (16:9, 90 % of the screen), centred, splitter exactly 50/50.

**Tooltips in the info line**

Every value in the line under the GPX buttons now explains itself when the mouse
hovers over it.

### Changed

**Shorter labels in the info line**

`Video:` is now `V:`. `Length(GPX)` and `Duration(GPX)` were merged into a single
`GPX: 8.94km/00:04:25.565`. `Elevation Gain:` is now `Ele:`, `ZeroSpeed:` is now
`Zero:`, `TimeGaps:` is now `Gaps:`. The explanations moved into the tooltips.

This frees about 350 pixels in the GPX bar, and those pixels are what makes an
even 50/50 split possible on a smaller screen.

**KVRouite needs less screen width**

The smallest usable window width went down from 1295 to 1050 pixels. The 50/50
split now holds down to a window width of about 1200 pixels instead of 1700.
Checked against the startup size on screens from 1280x800 upwards: the window
fits everywhere and starts balanced.

**The Kinomap logo makes room**

When the GPX bar gets narrow, the logo hides itself instead of pushing the whole
window wider.

### Fixed

**Rendered videos could come out several seconds too short**

Before merging, every pre-trimmed part is measured to find out how much of it is
really playable, and that length is written into the concat list. The
measurement could return a value that was far too small. ffmpeg then trimmed the
part down to that length while merging, and the finished video was short by the
difference.

Measured on a project with two 60 s clips and one cut from 30 s to 90 s:

    part 1 reported  55.033 s   instead of  60.000 s
    part 2 reported  55.700 s   instead of  60.833 s
    merged file      115.933 s  instead of 120.833 s   (147 frames dropped)
    final video       55.933 s  instead of  60.833 s

The cut itself was placed correctly - the material after it simply started
almost five seconds too late.

The cause was the interval passed to ffprobe. `START%` without an explicit end
does not reliably mean "to the end of the file": depending on the file it
returned nothing at all, or only the very first frame of the interval. In the
second case the file was reported short by the width of the measuring window,
which is five seconds.

The interval now has an explicit end. On top of that the result is checked for
plausibility: this measurement exists to subtract a small overhang - at most one
GOP, measured 0.901 s - so anything more than 1.5 s below the container length is
discarded and the container value is used instead. That is the behaviour from
before this measurement existed: at worst a stutter at a joint, never a video
that is too short.

Measured after the change: five consecutive renders of the same project, all
exactly 60.833333 s, with the measurement returning correct values every time.
Before the change the same code returned a usable value in only one of three
runs. Forcing the faulty answers by hand - first frame only, two frames, no
answer at all - is now caught in every case, while a genuine correction of
0.9 s still goes through.

This affects 5.0 as well. The measurement arrived with the merge fix that first
shipped in 5.0; releases up to and including 4.34 do not contain it and are not
affected.

**The stepper now counts in the finished video**

The stepper measured its steps in the raw footage. A cut does not exist in the
finished video, but the step ran straight into it: `+1s` in front of a cut
landed inside the deleted range, and a "freeze" then parked the player at the
cut instead of stepping. On every cut longer than the step size you got stuck at
the edge and never moved on – with a cut of several minutes, `s` and `m` could
not get past it at all.

Steps are now measured in the finished video. Measured on a 29.97 fps project
with a cut from 1639.404 s to 1744.409 s, standing on the last frame before it:
`+1s` now lands at 1745.376 s, which is exactly one second later in the finished
video. It used to stop dead at the cut.

What changed per mode:

- `s` and `m` step their distance in the finished video and fly over cuts as if
  they were not there.
- `f` moves one frame in the finished video, so a single press takes you from the
  last frame before a cut to the first frame after it – it needed two before.
- `k` skips keyframes that fall inside a cut, because those do not exist in the
  result either.
- The freeze is gone. Looking at a cut edge is what the new `c` mode is for, and
  `c` and `f` now stop on exactly the same two frames.

The freeze also parked the player one millisecond before the cut, which is less
than one frame – you ended up on the first deleted frame, and the 200 ms preview
timer then threw you to the far end of the cut. That is what made it look as if
`s`, `m` and `k` could never reach a cut at all.

**The stepper assumed 25 fps for every video**

The frame rate was read from an mpv property that does not exist, so the lookup
silently fell back to 25 fps – on every file, at every frame rate. It now reads
`container-fps`, with `estimated-vf-fps` as a fallback.

This used to be almost harmless, because the value only fed a prediction that was
thrown away again. Now it decides where a frame boundary is, so it has to be
right: with 25 fps assumed, a step over a cut in 29.97 fps material would land on
the wrong frame. Checked against 24, 25, 29.97, 30, 50 and 60 fps material –
stepping over a cut lands on exactly the right frame in both directions at every
one of them.

**Cuts in Encode Mode are now frame-exact**

Every cut used to lose up to five frames: the cut was moved to the nearest
keyframe of the merged file instead of landing where it was marked. With many
cuts in one project the error added up. A keyframe is now forced at every cut
edge while merging, so the cut lands exactly on the mark.

Measured on a test project with a cut from 10.10 s to 20.10 s in a 30 s video:
the result is now 20.000 s instead of 19.833 s – a deviation of 0.000 s instead
of 0.167 s per cut.

This concerns Encode Mode only. Copy Mode cuts at keyframes by design, that has
not changed.

**GPX Summary showed rounded values**

The distance and the elevation gain shown in the GPX Summary were read back out
of the text in the info line instead of using the calculated numbers. The
elevation gain was therefore rounded to whole metres, and any change to the
labels would have made the distance silently drop to 0.00 km. Both values now
come straight from the calculation, and the elevation gain is shown with one
decimal.
