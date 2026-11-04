<!-- meshfox:canvas -->
# Video subtitles: transcribe, translate, burn in

<!-- meshfox:comment -->
> This is a [meshfox](https://meshfox.orofarne.net/) document — open it
> with `meshfox view` (or `meshfox tui`) for the interactive canvas.
> This note is only visible here, in a plain Markdown viewer.
<!-- /meshfox:comment -->

Takes a video, transcribes the speech locally (Whisper on Apple Silicon),
optionally translates the subtitles with your coding agent, lets you fix them
by hand, and burns the result into a new video. This canvas plus
one helper file, `subs_lib.py`, is the whole tool: environment, tests and every
pipeline step live in the nodes below.

<!-- meshfox:var name="VIDEO" type="file" ext="mp4,mkv,mov,webm,m4v" prompt="Video to subtitle" -->
<!-- meshfox:var name="OUTPUT" type="file" mode="save" ext="mp4" prompt="Where to write the video with burned-in subtitles (.mp4)" -->
<!-- meshfox:var name="SRC_LANG" type="select" choices="auto,en,ru,uk,de,fr,es,it,pt,pl,nl,cs,tr,ar,hi,zh,ja,ko" default="auto" prompt="Language spoken in the video (auto = detect)" -->
<!-- meshfox:var name="DST_LANG" type="select" choices="en,ru,uk,de,fr,es,it,pt,pl,nl,cs,tr,ar,hi,zh,ja,ko" default="en" prompt="Subtitle language (translated only if it differs from the spoken one)" -->
<!-- meshfox:var name="WHISPER_MODEL" type="select" choices="mlx-community/whisper-large-v3-turbo,mlx-community/whisper-small-mlx,mlx-community/whisper-tiny" default="mlx-community/whisper-large-v3-turbo" prompt="Whisper model (bigger = slower, more accurate)" -->
<!-- meshfox:var name="SUB_FONT" default="Helvetica" prompt="Subtitle font" -->
<!-- meshfox:var name="SUB_SIZE" default="5.5" prompt="Subtitle size, % of the video height (4-7 is typical)" -->
<!-- meshfox:var name="SUB_POS" type="select" choices="bottom,middle,top" default="bottom" prompt="Where the subtitles sit" -->
<!-- meshfox:var name="SUB_MARGIN" default="5" prompt="Distance from the top/bottom edge, % of the video height (ignored for middle)" -->
<!-- meshfox:var name="SUB_COLOR" default="#FFFFFF" prompt="Text colour, #RRGGBB (the outline is always black)" -->
<!-- meshfox:var name="EDIT" type="bool" default="false" prompt="Pause to edit the subtitles by hand before burning them in?" -->
<!-- meshfox:var name="EDITOR_CMD" default="nvim" prompt="Editor for the .srt (a terminal editor, e.g. nvim, hx, nano)" -->
<!-- meshfox:var name="PREVIEW" type="bool" default="false" prompt="Open the video in mpv next to the editor (press r there to reload the subtitles)?" -->
<!-- meshfox:var name="WORK_DIR" type="dir" default="@tmp/work" prompt="Where to keep intermediate files (transcript, cues, editable .srt, .ass); default: this canvas's temporary directory" -->
<!-- meshfox:var name="PYTHON" from="env/setup" -->
<!-- meshfox:var name="WORDS" type="file" mode="save" from="paths/paths" -->
<!-- meshfox:var name="CUES" type="file" mode="save" from="paths/paths" -->
<!-- meshfox:var name="TRANSLATED" type="file" mode="save" from="paths/paths" -->
<!-- meshfox:var name="SRT" type="file" mode="save" from="paths/paths" -->
<!-- meshfox:var name="SRT_EDITED" type="file" mode="save" from="paths/paths" -->
<!-- meshfox:var name="ASS" type="file" mode="save" from="paths/paths" -->
<!-- meshfox:var name="NEEDS_TRANSLATION" type="bool" from="plan/plan" -->
<!-- meshfox:var name="SRC_USED" from="plan/plan" -->

## Convert
<!-- meshfox:node id="main" color="4" -->

The entry point: run it, answer the prompts (video, output file, languages,
whether to pause for editing), get the video.

```bash name="main" default env="OUTPUT" deps="render/render" output="markdown"
echo "**done**: [$OUTPUT]($OUTPUT)"
```

`OUTPUT` is the only file written where you asked for it. Everything else
goes to `WORK_DIR` (default: this canvas's temporary directory, `@tmp/work`):
`*.words.json` (transcript), `*.cues.json`, `*.cues.translated.json`, `*.srt`
(the editable subtitles) and `*.ass` (what gets burned in), named after
`OUTPUT` plus a short hash of its path. Keeping them away from the result
matters: a player auto-loads `out.srt` / `out.ass` lying next to `out.mp4` and
draws them on top of the burned-in subtitles. Steps whose inputs did not
change are skipped, so re-running after a tweak is cheap: re-rendering with
another style (`SUB_FONT`, `SUB_SIZE`, `SUB_POS`, `SUB_MARGIN`, `SUB_COLOR`) does not
re-transcribe or re-translate. The temporary
directory lives as long as the canvas session — `meshfox session reset`
deletes it (and the freshness records with it); point `WORK_DIR` at a real
folder to keep the transcript and your edits for good.

Non-interactively:

```console
meshfox README.canvas.md run main --set VIDEO=talk.mp4 --set OUTPUT=out/talk.mp4 \
  --set SRC_LANG=auto --set DST_LANG=ru --set EDIT=false
```

Interactive terminals only: because the optional **Edit** step is a `tty`
block, `meshfox run` refuses to start from a non-terminal (a cron job, CI)
even with `EDIT=false`. Run it from `meshfox view`, `meshfox tui` or a real
terminal. The **Translate** step opens your coding agent interactively; leave it (`/exit`) once it reports the file is written.

Hand edits live in `*.edited.srt` and are never overwritten (see **Edit**): if
the generated subtitles change afterwards (a new `DST_LANG`, a re-transcription),
the previous edits are kept as `*.edited.srt.bak` and **Edit** starts again from
the new subtitles.

## Pipeline at a glance
<!-- meshfox:node id="overview" -->

![Pipeline: VIDEO, transcribe, segment, optional translate and check, export, optional edit, render, OUTPUT; plan decides whether translation is needed](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDQwIDIxNCIgd2lkdGg9IjEwNDAiIGhlaWdodD0iMjE0IiBmb250LWZhbWlseT0iLWFwcGxlLXN5c3RlbSxIZWx2ZXRpY2EsQXJpYWwsc2Fucy1zZXJpZiIgZm9udC1zaXplPSIxMyI+CjxkZWZzPjxtYXJrZXIgaWQ9ImEiIHZpZXdCb3g9IjAgMCAxMCAxMCIgcmVmWD0iOSIgcmVmWT0iNSIgbWFya2VyV2lkdGg9IjciIG1hcmtlckhlaWdodD0iNyIgb3JpZW50PSJhdXRvIj48cGF0aCBkPSJNMCAxIEwxMCA1IEwwIDkgeiIgZmlsbD0iIzQ3NTU2OSIvPjwvbWFya2VyPjwvZGVmcz4KPHJlY3Qgd2lkdGg9IjEwNDAiIGhlaWdodD0iMjE0IiByeD0iMTIiIGZpbGw9IiNmOGZhZmMiLz4KPGcgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjZDk3NzA2IiBzdHJva2Utd2lkdGg9IjEuNSIgc3Ryb2tlLWRhc2hhcnJheT0iNiA0Ij4KPHJlY3QgeD0iMzQ0IiB5PSI0MiIgd2lkdGg9IjIzNiIgaGVpZ2h0PSI3NiIgcng9IjEwIi8+CjxyZWN0IHg9IjY4NiIgeT0iNDIiIHdpZHRoPSIxMTYiIGhlaWdodD0iNzYiIHJ4PSIxMCIvPgo8L2c+CjxnIGZpbGw9IiNiNDUzMDkiIGZvbnQtc2l6ZT0iMTEuNSIgZm9udC1zdHlsZT0iaXRhbGljIj4KPHRleHQgeD0iMzUyIiB5PSIzNiI+aWYgTkVFRFNfVFJBTlNMQVRJT048L3RleHQ+Cjx0ZXh0IHg9IjY5NCIgeT0iMzYiPmlmIEVESVQ8L3RleHQ+CjwvZz4KPGcgc3Ryb2tlPSIjNjQ3NDhiIiBzdHJva2Utd2lkdGg9IjEuNSI+CjxyZWN0IHg9IjEyIiB5PSI2MCIgd2lkdGg9Ijg4IiBoZWlnaHQ9IjQwIiByeD0iOCIgZmlsbD0iI2RiZWFmZSIgc3Ryb2tlPSIjMjU2M2ViIi8+CjxyZWN0IHg9IjkyNCIgeT0iNjAiIHdpZHRoPSI4OCIgaGVpZ2h0PSI0MCIgcng9IjgiIGZpbGw9IiNkY2ZjZTciIHN0cm9rZT0iIzE2YTM0YSIvPgo8cmVjdCB4PSIxMjYiIHk9IjYwIiB3aWR0aD0iODgiIGhlaWdodD0iNDAiIHJ4PSI4IiBmaWxsPSIjZmZmIi8+CjxyZWN0IHg9IjI0MCIgeT0iNjAiIHdpZHRoPSI4OCIgaGVpZ2h0PSI0MCIgcng9IjgiIGZpbGw9IiNmZmYiLz4KPHJlY3QgeD0iMzU0IiB5PSI2MCIgd2lkdGg9Ijg4IiBoZWlnaHQ9IjQwIiByeD0iOCIgZmlsbD0iI2ZmZiIvPgo8cmVjdCB4PSI0NjgiIHk9IjYwIiB3aWR0aD0iODgiIGhlaWdodD0iNDAiIHJ4PSI4IiBmaWxsPSIjZmZmIi8+CjxyZWN0IHg9IjU4MiIgeT0iNjAiIHdpZHRoPSI4OCIgaGVpZ2h0PSI0MCIgcng9IjgiIGZpbGw9IiNmZmYiLz4KPHJlY3QgeD0iNjk2IiB5PSI2MCIgd2lkdGg9Ijg4IiBoZWlnaHQ9IjQwIiByeD0iOCIgZmlsbD0iI2ZmZiIvPgo8cmVjdCB4PSI4MTAiIHk9IjYwIiB3aWR0aD0iODgiIGhlaWdodD0iNDAiIHJ4PSI4IiBmaWxsPSIjZmZmIi8+CjxyZWN0IHg9IjI0MCIgeT0iMTUwIiB3aWR0aD0iODgiIGhlaWdodD0iNDAiIHJ4PSI4IiBmaWxsPSIjZmZmIi8+CjwvZz4KPGcgZmlsbD0iIzBmMTcyYSIgdGV4dC1hbmNob3I9Im1pZGRsZSI+Cjx0ZXh0IHg9IjU2IiB5PSI4NSI+VklERU88L3RleHQ+PHRleHQgeD0iOTY4IiB5PSI4NSI+T1VUUFVUPC90ZXh0Pgo8dGV4dCB4PSIxNzAiIHk9Ijg1Ij50cmFuc2NyaWJlPC90ZXh0Pjx0ZXh0IHg9IjI4NCIgeT0iODUiPnNlZ21lbnQ8L3RleHQ+Cjx0ZXh0IHg9IjM5OCIgeT0iODUiPnRyYW5zbGF0ZTwvdGV4dD48dGV4dCB4PSI1MTIiIHk9Ijg1Ij5jaGVjazwvdGV4dD4KPHRleHQgeD0iNjI2IiB5PSI4NSI+ZXhwb3J0PC90ZXh0Pjx0ZXh0IHg9Ijc0MCIgeT0iODUiPmVkaXQ8L3RleHQ+Cjx0ZXh0IHg9Ijg1NCIgeT0iODUiPnJlbmRlcjwvdGV4dD48dGV4dCB4PSIyODQiIHk9IjE3NSI+cGxhbjwvdGV4dD4KPC9nPgo8ZyBmaWxsPSJub25lIiBzdHJva2U9IiM0NzU1NjkiIHN0cm9rZS13aWR0aD0iMS41IiBtYXJrZXItZW5kPSJ1cmwoI2EpIj4KPHBhdGggZD0iTTEwMCA4MEgxMjQiLz48cGF0aCBkPSJNMjE0IDgwSDIzOCIvPjxwYXRoIGQ9Ik0zMjggODBIMzUyIi8+CjxwYXRoIGQ9Ik00NDIgODBINDY2Ii8+PHBhdGggZD0iTTU1NiA4MEg1ODAiLz48cGF0aCBkPSJNNjcwIDgwSDY5NCIvPgo8cGF0aCBkPSJNNzg0IDgwSDgwOCIvPjxwYXRoIGQ9Ik04OTggODBIOTIyIi8+CjxwYXRoIGQ9Ik0xNzAgMTAwVjE3MEgyMzgiLz4KPHBhdGggZD0iTTMyOCAxNzBINTEyVjEyMCIgc3Ryb2tlLWRhc2hhcnJheT0iNiA0IiBzdHJva2U9IiNiNDUzMDkiLz4KPC9nPgo8dGV4dCB4PSI1MjIiIHk9IjE2OCIgZmlsbD0iI2I0NTMwOSIgZm9udC1zaXplPSIxMiIgZm9udC1zdHlsZT0iaXRhbGljIj5uZWVkcyB0cmFuc2xhdGlvbj8g4oCUIGRlY2lkZWQgYWZ0ZXIgdHJhbnNjcmlwdGlvbiwgc28gU1JDX0xBTkc9YXV0byB3b3JrczwvdGV4dD4KPC9zdmc+Cg==){width=100%}

Brackets are conditional dependencies: **translate** is in the chain only
when `NEEDS_TRANSLATION` is true (spoken language ≠ `DST_LANG`, decided *after*
transcription so `SRC_LANG=auto` works), **edit** only when `EDIT` is true.

## Python environment
<!-- meshfox:node id="env" -->

`mlx-whisper` runs Whisper on the Apple GPU, so this tool needs Apple Silicon.
The block is a `pyproject.toml`: `@python_venv` installs it into an isolated
venv under `.meshfox/` and publishes its interpreter as `$PYTHON`. The first
run downloads the packages (about a minute) and the chosen Whisper model.

```toml name="setup" interpreter="@python_venv"
[project]
name = "subtitles-env"
version = "0.0.0"
requires-python = ">=3.10"
dependencies = ["mlx-whisper"]
```

## Shared helpers
<!-- meshfox:node id="lib" type="file" display="code" lang="python" -->

[subs_lib.py](./subs_lib.py)

The one file kept next to this canvas: segmentation, SRT/ASS, translation
checks, edit-safe export. Every step below imports from it.

## Paths
<!-- meshfox:node id="paths" -->

Derives every intermediate file name from `OUTPUT` and `WORK_DIR` (never next
to the result) and publishes them as `WORDS`, `CUES`, `TRANSLATED`, `SRT`,
`SRT_EDITED` and `ASS`.

```python name="paths" interpreter="$PYTHON -u" env="OUTPUT,WORK_DIR"
import os
from pathlib import Path
from subs_lib import derive_paths, vars_out

E = os.environ
Path(E["WORK_DIR"]).mkdir(parents=True, exist_ok=True)
vars_out(**derive_paths(E["OUTPUT"], E["WORK_DIR"]))
```

## Transcribe
<!-- meshfox:node id="transcribe" -->

Word-level transcript with `mlx-whisper`. `condition_on_previous_text` is off,
so one hallucination on silence or music cannot poison the rest. `inputs=` /
`outputs=` make meshfox skip the step when the video and transcript are
unchanged — also across sessions. Long videos take a while; the first run
downloads the model.

```python name="transcribe" interpreter="$PYTHON -u" env="VIDEO,WORDS,SRC_LANG,WHISPER_MODEL" inputs="$VIDEO" outputs="$WORDS"
import os
from subs_lib import transcribe

E = os.environ
transcribe(E["VIDEO"], E["WORDS"], E["SRC_LANG"], E["WHISPER_MODEL"])
```

### Transcript (`WORDS`)
<!-- meshfox:node id="preview-words" type="file" display="code" lang="json" -->

[WORDS]($WORDS)

Word-level transcript straight from Whisper: segments, words, per-word timestamps and probabilities.

## Plan: is translation needed?
<!-- meshfox:node id="plan" -->

Compares the spoken language (the detected one when `SRC_LANG=auto`) with
`DST_LANG` and publishes `NEEDS_TRANSLATION` and `SRC_USED`. That computed
boolean is what the conditional dependency on **Translate** looks at.

```python name="plan" interpreter="$PYTHON -u" env="WORDS,SRC_LANG,DST_LANG" deps="transcribe/transcribe"
import os
from subs_lib import read_json, vars_out

E = os.environ
spoken = E["SRC_LANG"]
if spoken == "auto":  # Whisper's guess, stored with the transcript
    spoken = read_json(E["WORDS"]).get("language") or "en"
vars_out(SRC_USED=spoken, NEEDS_TRANSLATION="true" if spoken != E["DST_LANG"] else "false")
```

## Segment
<!-- meshfox:node id="segment" -->

Groups words into subtitle cues in the *source* language: a new cue at a long
pause or sentence end; an over-long cue is cut at a sentence end, then a
clause break, else in the middle. Segments Whisper hallucinated (high
no-speech probability, runaway repetition) are dropped, and cues never
overlap.

```python name="segment" interpreter="$PYTHON -u" env="WORDS,CUES" deps="transcribe/transcribe" inputs="$WORDS" outputs="$CUES"
import os
from subs_lib import build_cues, read_json, write_json

E = os.environ
data = read_json(E["WORDS"])
cues = build_cues(data["segments"], data.get("language", "en"))
write_json(E["CUES"], cues)
print(f"{len(cues)} cues -> {E['CUES']}")
```

### Cues (`CUES`)
<!-- meshfox:node id="preview-cues" type="file" display="code" lang="json" -->

[CUES]($CUES)

The transcript cut into subtitle cues, in the spoken language. This is what the translation step reads.

## Translate
<!-- meshfox:node id="translate" color="6" tags="optional,agent" -->

Optional: runs only when `NEEDS_TRANSLATION` is true. The translation is done
by your coding agent in an **interactive session**: an `@agent` block with
`tty` (provider `claude` or `codex` from `interpreters.agent.provider` in
`.meshfox/config.toml`) that opens in the terminal with the task
already typed in, reads the cues file and writes the translated one. Because
you are in the loop it can ask about terminology, names or register before it
starts, and every file read/write goes through the agent's normal permission
prompt — nothing to configure (to stop being asked, allow `Read` of
`*.cues.json` and `Edit` of `*.cues.translated.json` in your agent's settings). When it says the file is written, leave the
session (`/exit` or Ctrl-D) and the pipeline continues at once (the block is
`autoclose`: no "press any key" stop). Translating whole cues
one-to-one — rather than asking the model to also re-chunk — keeps timings
trivially correct.

`inputs=` / `outputs=` mean an unchanged cue file is not translated (and paid
for) twice. The agent is untrusted code as far as correctness goes, so the
**check** block right after it verifies the result mechanically. The step is a
`tty` block, like **Edit**, so it needs a real terminal (`meshfox view`,
`meshfox tui` or a shell).

```text name="translate" interpreter="@agent" tty autoclose env="CUES,TRANSLATED,SRC_USED,DST_LANG" deps="segment/segment" inputs="$CUES" outputs="$TRANSLATED"
Translate video subtitles.

  Input  (read this):  $CUES
  Output (write this): $TRANSLATED
  From language code:  $SRC_USED
  To language code:    $DST_LANG

The input is a JSON list of {"i": number, "start": s, "end": s, "text": "..."}.
Write a JSON list of {"i": number, "text": "..."} to the output file.

Before you start, skim the input. If something would change the translation
-- ambiguous terms, names, formal vs. informal address, jargon -- ask me, once,
and wait for the answer. If nothing is unclear, just proceed.

The same goes while you work: if a cue is doubtful or unintelligible (a likely
mis-hearing by the speech recognizer, a joke or idiom that does not carry
over, a name you cannot place), do not guess silently -- stop and ask me about
that cue, quoting its "i" and text, then continue with my answer.

Rules:
1. Exactly one output object per input cue, same "i", same order. Never
   merge, split, drop or reorder cues, even if a sentence runs across two
   cues: translate each cue so that read in order they form the sentence.
2. Natural, concise subtitle language, not word-for-word. Keep names, numbers
   and technical terms. No notes, no quotes added, no speaker labels.
3. One line of text per cue (no line breaks); the player wraps it.
4. Work through the file in batches of about 30 cues, with the previous batch
   as context, so terminology stays consistent.
5. Write valid UTF-8 JSON (use real characters, not \u escapes) to the
   output file, and nothing else.

When the file is written, tell me in one short line that I can exit.
```

```python name="check" interpreter="$PYTHON -u" env="CUES,TRANSLATED" deps="translate"
import os, sys
from subs_lib import check_translation, read_json

E = os.environ
if os.path.getmtime(E["TRANSLATED"]) < os.path.getmtime(E["CUES"]):
    sys.exit("the translation file is older than the cues: the agent session ended without writing a new one")
cues = read_json(E["CUES"])
problems = check_translation(cues, read_json(E["TRANSLATED"]))
if problems:
    sys.exit("translation rejected:\n  " + "\n  ".join(problems[:20]))
print(f"translation ok ({len(cues)} cues)")
```

If **check** reports a problem (a missing or reordered index, an empty line,
a runaway length), the run stops there — run **Translate** again; nothing
downstream has been touched.

### Translated cues (`TRANSLATED`)
<!-- meshfox:node id="preview-translated" type="file" display="code" lang="json" -->

[TRANSLATED]($TRANSLATED)

The agent's translation, one object per cue, same `i`. Exists only when translation was needed.

## Export
<!-- meshfox:node id="export" -->

Writes the generated `.srt`: the translation when one was made, the original
cues otherwise, lines wrapped to at most two balanced lines. It is a plain
function of the cues, so it is rewritten whenever they change; your own edits go
to a copy made by **Edit**, never here. As a safeguard, a file that no longer
matches the sidecar (`*.srt.generated`) is left alone — delete it to regenerate.

```python name="export" interpreter="$PYTHON -u" env="CUES,TRANSLATED,SRT,NEEDS_TRANSLATION,SRC_USED,SRC_LANG,DST_LANG" deps="segment/segment,translate/check?NEEDS_TRANSLATION" outputs="$SRT"
import os
from subs_lib import env_flag, export_srt, read_json

E = os.environ
use = env_flag("NEEDS_TRANSLATION")
lang = E["DST_LANG"] if use else (E.get("SRC_USED") or E["SRC_LANG"])
res = export_srt(read_json(E["CUES"]), read_json(E["TRANSLATED"]) if use else None, E["SRT"],
                 use_translated=use, lang=lang)
print(f"{E['SRT']}: {'kept your edits' if res == 'kept' else 'written'}")
```

### Generated subtitles (`SRT`)
<!-- meshfox:node id="preview-srt" type="file" display="code" lang="text" -->

[SRT]($SRT)

The generated subtitles: what **Edit** starts from and, without editing, what **Render** burns in.

## Edit (optional)
<!-- meshfox:node id="edit" color="6" tags="optional,interactive" -->

Runs only when `EDIT` is true: **Render** reaches it through the conditional
dependency `deps="edit/edit?EDIT"`. A `tty` block that hands the terminal to
`EDITOR_CMD`; saving and quitting continues the pipeline. With `PREVIEW` the
video opens in mpv beside it — after saving, press `r` in the mpv window to
reload the subtitles. See *Design note: a subtitle editor* for other options.

The step reads the generated `.srt` and edits a copy, `*.edited.srt`, which is
what **Render** burns in. Its input (the generated subtitles) and its output
(your copy) are declared, so meshfox treats the step as done — and does not
reopen the editor — as long as the generated subtitles are unchanged and you
have already edited them in this session (`meshfox session reset` forgets that).
It opens again when the generated subtitles change (a new `DST_LANG`, a
re-transcription) or when `VIDEO`, `EDITOR_CMD` or `PREVIEW` change. Then the
previous copy is set aside as `*.edited.srt.bak` and the new one starts from the
new subtitles; opened again on unchanged subtitles, it continues from your copy.

```bash name="edit" tty autoclose env="SRT,SRT_EDITED,VIDEO,EDITOR_CMD,PREVIEW" inputs="$SRT" outputs="$SRT_EDITED"
# Work on a copy: the generated .srt is this step's input and must stay as it is.
# A copy made from different generated subtitles is set aside, never overwritten.
now="$(shasum -a 256 < "$SRT" | cut -d' ' -f1)"
if [ ! -e "$SRT_EDITED" ] || [ "$(cat "$SRT_EDITED.base" 2>/dev/null)" != "$now" ]; then
  if [ -e "$SRT_EDITED" ]; then cp "$SRT_EDITED" "$SRT_EDITED.bak"; fi
  cp "$SRT" "$SRT_EDITED"
  echo "$now" > "$SRT_EDITED.base"
fi
if [ "$PREVIEW" = true ]; then
  conf="$(mktemp)"; echo "r sub-reload" > "$conf"
  mpv --no-config --input-conf="$conf" --sub-file="$SRT_EDITED" --pause --loop-file=inf \
      --really-quiet "$VIDEO" >/dev/null 2>&1 &
  mpv_pid=$!
  trap 'kill $mpv_pid 2>/dev/null; rm -f "$conf"' EXIT
fi
$EDITOR_CMD "$SRT_EDITED"
```

### Edited subtitles (`SRT_EDITED`)
<!-- meshfox:node id="preview-srt-edited" type="file" display="code" lang="text" -->

[SRT_EDITED]($SRT_EDITED)

Your copy of the subtitles: what **Render** burns in when `EDIT` is true. It exists once **Edit** has run.

## Render
<!-- meshfox:node id="render" -->

`.srt` → `.ass` (styled and sized to the video's real resolution), then burned
into the video, audio re-encoded to AAC. It prefers `ffmpeg` when it has the
`subtitles` filter (libass) and falls back to `mpv`'s encode mode otherwise —
Homebrew's ffmpeg is frequently built without libass. The `.ass` is copied
into a scratch directory first, so odd characters in paths never need
filter escaping.

It reads the edited copy (`SRT_EDITED`) when `EDIT` is true and the generated
`.srt` otherwise. Both are declared as `inputs=`: **Export** is pulled in
through `SRT`, while `SRT_EDITED` — and with it **Edit** — counts only as long as
the conditional dependency `edit/edit?EDIT` is on; when `EDIT` is false that
input is ignored. Nothing else forces a re-render, so it runs again only when
the subtitles, the video or a style option actually changed.

```python name="render" interpreter="$PYTHON -u" env="SRT,SRT_EDITED,EDIT,ASS,VIDEO,OUTPUT,SUB_FONT,SUB_SIZE,SUB_POS,SUB_MARGIN,SUB_COLOR" deps="edit/edit?EDIT" inputs="$SRT,$SRT_EDITED,$VIDEO" outputs="$OUTPUT"
import os
from subs_lib import env_flag, render

E = os.environ
srt = E["SRT_EDITED"] if env_flag("EDIT") else E["SRT"]
tool = render(srt, E["VIDEO"], E["OUTPUT"], E["SUB_FONT"], E["ASS"],
              size_pct=float(E["SUB_SIZE"]), pos=E["SUB_POS"],
              margin_pct=float(E["SUB_MARGIN"]), color=E["SUB_COLOR"])
print(f"rendered with {tool} -> {E['OUTPUT']}")
```

### Burn-in script (`ASS`)
<!-- meshfox:node id="preview-ass" type="file" display="code" lang="text" -->

[ASS]($ASS)

Styled and sized to the video, regenerated by **Render** on every run.

## Design note: a subtitle editor in the middle
<!-- meshfox:node id="editor-options" color="3" -->

The **Edit** step needs *some* editor. Options, roughly from cheapest to most
work:

| Option | What it is | Verdict |
|---|---|---|
| `$EDITOR` on the `.srt` | what is wired in now (`tty` block) | zero dependencies; the format is plain text and wrapped to two lines, so it edits well; no timing feedback |
| `$EDITOR` + mpv preview | the same plus `PREVIEW`: video beside the editor, `r` reloads subs | cheap, gives real feedback on timing and line length |
| Aegisub | the standard desktop timing editor (waveform, styles, ASS); maintained forks exist | best for hard timing work; a GUI — block would be `open -W -a Aegisub "$SRT"` |
| An existing terminal editor | a small PyPI package `subtitle-editor` is a terminal SRT editor | unverified: tiny project, no ASS; try before relying on it |
| subed (Emacs) | Emacs minor mode for SRT with timing keys and mpv sync | excellent if you live in Emacs |
| A purpose-built TUI | ~250 lines of Python (Textual): cue list, inline edit, split/merge, nudge timing ±100 ms, mpv IPC for "play this cue" | the ideal fit for this pipeline, and it could live in this canvas as one more block — not built yet |

Searching turned up no mature terminal editor covering both SRT and ASS
timing, so the realistic choices are the first two now, and a small Textual
TUI if hand-editing becomes routine. The edited `.srt` is the contract: whichever
editor is used, **Render** reads only that file.

## Why mpv for burning in
<!-- meshfox:node id="why-mpv" -->

On the machine this was built on, `ffmpeg -h filter=subtitles` says
`Unknown filter` — no libass. `mpv` always ships libass and has an encode mode
(`--o=`), so it renders the very same `.ass` into H.264/AAC without rebuilding
ffmpeg. If your ffmpeg does have libass it is used instead (it is also faster
to start). Burning in is a re-encode either way: CRF 18, x264, same
resolution and frame rate as the source.

## Tests
<!-- meshfox:node id="tests" -->

Unit tests for `subs_lib.py`: segmentation (pauses, sentence ends,
balanced splits, hallucination filtering, CJK, overlap), SRT/ASS formatting,
translation validation, and the guarantee that hand edits survive a re-export.
The transcription and rendering calls themselves are not unit-tested — they
need Whisper and a video — they were exercised end to end instead.

```python name="tests" interpreter="$PYTHON -u"
"""Tests for subs_lib.py."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import subs_lib as subs  # this block runs in the canvas directory


def words(text: str, start: float = 0.0, step: float = 0.4, gap_before: dict | None = None):
    """Fake word timestamps; `gap_before` = {word_index: extra silence}."""
    out, t = [], start
    for i, w in enumerate(text.split()):
        t += (gap_before or {}).get(i, 0)
        out.append({"word": " " + w, "start": round(t, 3), "end": round(t + step * 0.9, 3), "probability": 0.9})
        t += step
    return out


def seg(ws, **kw):
    return {"start": ws[0]["start"], "end": ws[-1]["end"], "text": "", "words": ws,
            "no_speech_prob": 0.0, "avg_logprob": -0.2, "compression_ratio": 1.2, **kw}


class SegmentTests(unittest.TestCase):
    def test_long_pause_starts_a_new_cue(self):
        cues = subs.build_cues([seg(words("one two three four five six", gap_before={3: 2.0}))], "en")
        self.assertEqual([c["text"] for c in cues], ["one two three", "four five six"])

    def test_sentence_end_splits_once_cue_has_substance(self):
        cues = subs.build_cues([seg(words("Hello everyone. Today we talk about subtitles."))], "en")
        self.assertEqual([c["text"] for c in cues], ["Hello everyone.", "Today we talk about subtitles."])

    def test_tiny_sentence_is_merged_not_left_alone(self):
        cues = subs.build_cues([seg(words("Yes. We can do that for you today."))], "en")
        self.assertEqual(len(cues), 1)

    def test_overlong_sentence_splits_into_balanced_halves(self):
        text = "Today we are going to talk about how to build a small tool that translates subtitles."
        cues = subs.build_cues([seg(words(text, step=0.2))], "en")
        self.assertEqual(len(cues), 2)
        self.assertTrue(all(len(c["text"]) <= 84 for c in cues))
        self.assertLess(abs(len(cues[0]["text"]) - len(cues[1]["text"])), 25)

    def test_prefers_clause_break_when_splitting(self):
        text = "It is surprisingly simple, and it works really well even on very long videos like this one."
        cues = subs.build_cues([seg(words(text, step=0.2))], "en", max_chars=60)
        self.assertEqual(cues[0]["text"], "It is surprisingly simple,")

    def test_hallucinated_segments_are_dropped(self):
        good = seg(words("A real sentence of speech."))
        silence = seg(words("Thanks for watching!", start=20), no_speech_prob=0.9, avg_logprob=-1.5)
        loop = seg(words("la la la la", start=30), compression_ratio=3.0)
        cues = subs.build_cues([good, silence, loop], "en")
        self.assertEqual([c["text"] for c in cues], ["A real sentence of speech."])

    def test_cjk_words_are_joined_without_spaces(self):
        ws = [{"word": c, "start": i * 0.2, "end": i * 0.2 + 0.15, "probability": 1} for i, c in enumerate("你好世界。")]
        self.assertEqual(subs.build_cues([seg(ws)], "zh")[0]["text"], "你好世界。")

    def test_cues_are_ordered_numbered_and_never_overlap(self):
        cues = subs.build_cues([seg(words("a b c d e f g h i j k l m n o p", gap_before={5: 1, 10: 1}))], "en")
        self.assertEqual([c["i"] for c in cues], list(range(1, len(cues) + 1)))
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-9)
            self.assertGreater(a["end"], a["start"])

    def test_short_cue_is_stretched_but_not_into_the_next_one(self):
        def w(word, a, b):
            return {"word": " " + word, "start": a, "end": b, "probability": 1}
        # A very quick "Hello there everyone." (0.3 s) followed at 0.4 s by the next sentence.
        ws = [w("Hello", 0.0, 0.1), w("there", 0.1, 0.2), w("everyone.", 0.2, 0.3),
              w("Next", 0.4, 0.6), w("sentence", 0.6, 0.9), w("is", 0.9, 1.0), w("here.", 1.0, 1.4)]
        cues = subs.build_cues([seg(ws)], "en")
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["end"], 0.4)          # wanted 0.6, capped at the next start

    def test_triple_repeat_is_collapsed(self):
        ws = []
        for k in range(4):
            ws += words("See you next time.", start=k * 10)
        cues = subs.build_cues([seg(ws)], "en")
        self.assertEqual(len([c for c in cues if c["text"] == "See you next time."]), 2)


class CheckTests(unittest.TestCase):
    CUES = [{"i": 1, "text": "Hello"}, {"i": 2, "text": "World"}]

    def ok(self, tr):
        return subs.check_translation(self.CUES, tr)

    def test_accepts_matching_translation(self):
        self.assertEqual(self.ok([{"i": 1, "text": "Привет"}, {"i": 2, "text": "Мир"}]), [])

    def test_rejects_missing_cue(self):
        self.assertIn("missing [2]", self.ok([{"i": 1, "text": "Привет"}])[0])

    def test_rejects_wrong_order_or_duplicates(self):
        self.assertTrue(self.ok([{"i": 2, "text": "Мир"}, {"i": 1, "text": "Привет"}]))
        self.assertTrue(self.ok([{"i": 1, "text": "a"}, {"i": 1, "text": "b"}]))

    def test_rejects_empty_text_and_non_list(self):
        self.assertIn("empty translation", self.ok([{"i": 1, "text": "  "}, {"i": 2, "text": "Мир"}])[0])
        self.assertTrue(self.ok({"i": 1}))

    def test_rejects_runaway_length(self):
        self.assertIn("suspiciously long", self.ok([{"i": 1, "text": "x" * 500}, {"i": 2, "text": "Мир"}])[0])


class SrtTests(unittest.TestCase):
    def test_roundtrip(self):
        cues = [{"start": 0.0, "end": 1.5, "text": "Hello"}, {"start": 3661.25, "end": 3662.0, "text": "two\nlines"}]
        back = subs.parse_srt(subs.to_srt(cues, "ru"))
        self.assertEqual([(c["start"], c["end"], c["text"]) for c in back],
                         [(0.0, 1.5, "Hello"), (3661.25, 3662.0, "two\nlines")])

    def test_timestamp_format(self):
        self.assertEqual(subs.fmt_srt_time(3723.456), "01:02:03,456")

    def test_parse_tolerates_crlf_and_missing_index(self):
        text = "00:00:01,000 --> 00:00:02,000\r\nHi\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nThere\r\n"
        self.assertEqual([c["text"] for c in subs.parse_srt(text)], ["Hi", "There"])

    def test_wrap_balances_two_lines(self):
        out = subs.wrap_text("Today we are going to talk about how to build", "en")
        a, b = out.split("\n")
        self.assertLess(abs(len(a) - len(b)), 8)
        self.assertEqual(subs.wrap_text("short", "en"), "short")


class ExportTests(unittest.TestCase):
    CUES = [{"i": 1, "start": 0, "end": 1, "text": "Hello"}, {"i": 2, "start": 1, "end": 2, "text": "World"}]
    TR = [{"i": 1, "text": "Привет"}, {"i": 2, "text": "Мир"}]

    def test_uses_translation_when_asked(self):
        with TemporaryDirectory() as d:
            srt = str(Path(d) / "x.srt")
            self.assertEqual(subs.export_srt(self.CUES, self.TR, srt, use_translated=True, lang="ru"), "written")
            self.assertIn("Привет", Path(srt).read_text())

    def test_regenerates_an_untouched_file(self):
        with TemporaryDirectory() as d:
            srt = str(Path(d) / "x.srt")
            subs.export_srt(self.CUES, None, srt, use_translated=False, lang="en")
            self.assertEqual(subs.export_srt(self.CUES, self.TR, srt, use_translated=True, lang="ru"), "written")
            self.assertIn("Мир", Path(srt).read_text())

    def test_never_overwrites_hand_edits(self):
        with TemporaryDirectory() as d:
            srt = Path(d) / "x.srt"
            subs.export_srt(self.CUES, None, str(srt), use_translated=False, lang="en")
            srt.write_text(srt.read_text().replace("World", "Everybody"))
            self.assertEqual(subs.export_srt(self.CUES, self.TR, str(srt), use_translated=True, lang="ru"), "kept")
            self.assertIn("Everybody", srt.read_text())

    def test_does_not_adopt_a_foreign_srt(self):
        with TemporaryDirectory() as d:
            srt = Path(d) / "x.srt"
            srt.write_text("mine")
            self.assertEqual(subs.export_srt(self.CUES, None, str(srt), use_translated=False, lang="en"), "kept")
            self.assertEqual(srt.read_text(), "mine")


class RenderTests(unittest.TestCase):
    def test_ass_escapes_and_sizes_to_the_video(self):
        ass = subs.to_ass([{"start": 0, "end": 1.5, "text": "a {b}\nc \\ d"}], width=1280, height=720, font="Arial")
        self.assertIn("PlayResX: 1280", ass)
        self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,a \\{b\\}\\Nc \\\\ d", ass)
        self.assertIn("Style: Default,Arial,40,", ass)

    def test_ffmpeg_command_uses_a_plain_relative_ass_name(self):
        cmd = subs.render_command("/v/a b (1).mp4", "sub.ass", "/o/out.mp4", tool="ffmpeg")
        self.assertIn("ass=sub.ass", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], "/v/a b (1).mp4")   # path passed as one argv item

    def test_mpv_command_keeps_audio_and_picks_our_subs_only(self):
        cmd = subs.render_command("/v/a.mp4", "sub.ass", "/o/out.mp4", tool="mpv")
        self.assertIn("--sub-file=sub.ass", cmd)
        self.assertIn("--no-sub-auto", cmd)
        self.assertIn("--oac=aac", cmd)

    def test_default_style_is_unchanged(self):
        ass = subs.to_ass([{"start": 0, "end": 1, "text": "a"}], width=1080, height=1920, font="Arial")
        self.assertIn("Style: Default,Arial,106,&H00FFFFFF,", ass)
        self.assertIn(",2,54,54,96,1", ass)  # bottom-centre, 5% margins

    def test_style_options(self):
        ass = subs.to_ass([{"start": 0, "end": 1, "text": "a"}], width=1000, height=1000, font="X",
                          size_pct=4, pos="top", margin_pct=10, color="#FFCC00")
        self.assertIn("Style: Default,X,40,&H0000CCFF,", ass)  # ASS colours are BGR
        self.assertIn(",8,50,50,100,1", ass)

    def test_style_rejects_nonsense(self):
        cue = [{"start": 0, "end": 1, "text": "a"}]
        for kw in ({"pos": "left"}, {"size_pct": 0}, {"size_pct": 90}, {"margin_pct": -1}, {"color": "red"}):
            with self.assertRaises(SystemExit):
                subs.to_ass(cue, width=100, height=100, font="X", **kw)

    def test_paths_derive_from_output(self):
        p = subs.derive_paths("/o/talk (1).subbed.mp4", "/w")
        self.assertRegex(p["SRT"], r"^/w/talk \(1\)\.subbed-[0-9a-f]{8}\.srt$")
        self.assertTrue(p["WORDS"].endswith(".words.json"))
        self.assertTrue(all(v.startswith("/w/") for v in p.values()))  # nothing next to OUTPUT

    def test_same_stem_in_different_folders_does_not_collide(self):
        a = subs.derive_paths("/a/talk.mp4", "/w")
        b = subs.derive_paths("/b/talk.mp4", "/w")
        self.assertTrue(set(a.values()).isdisjoint(b.values()))


if __name__ == "__main__":
    unittest.main()
```
