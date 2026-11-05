<!-- meshfox:canvas -->
# Video subtitles: transcribe, translate, burn in
<!-- meshfox:node id="root" -->

<!-- meshfox:comment -->
> This is a [meshfox](https://meshfox.orofarne.net/) document — open it
> with `meshfox view` (or `meshfox tui`) for the interactive canvas.
> This note is only visible here, in a plain Markdown viewer.
<!-- /meshfox:comment -->

Takes a video, transcribes the speech locally (Whisper on Apple Silicon),
optionally translates the subtitles with your coding agent, lets you fix them
by hand, and burns the result into a new video. This canvas is the whole
tool: the environment, the code, its tests and every pipeline step live in the
nodes below, and the steps share code through `extends=`.

```button name="main" default deps="render/render"
▶ Convert the video
```

The pipeline is the row of nodes below, left to right: **Transcribe → Segment →
Translate → Export → Edit → Render**; the arrows are the `deps=` and
`inputs=`/`outputs=` edges. Dashed arrows are conditional: **Translate** is in
the chain only when `NEEDS_TRANSLATION` is true (spoken language ≠ `DST_LANG`,
decided by **Plan** *after* transcription, so `SRC_LANG=auto` works), **Edit**
only when `EDIT` is true. The button asks for the video, the output file, the
languages and whether to pause for editing, then runs the whole chain.

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

## Pipeline
<!-- meshfox:node id="pipeline" type="group" fold="false" -->

### Transcribe
<!-- meshfox:node id="transcribe" x=0 y=0 w=360 h=60 -->

Word-level transcript with `mlx-whisper`. `condition_on_previous_text` is off,
so one hallucination on silence or music cannot poison the rest. `inputs=` /
`outputs=` make meshfox skip the step when the video and transcript are
unchanged — also across sessions. Long videos take a while; the first run
downloads the model.

```python name="transcribe-defs" extends="lib/core-defs"
def transcribe(video: str, words_path: str, lang: str, model: str) -> None:
    import mlx_whisper  # heavy import: only when actually transcribing

    result = mlx_whisper.transcribe(
        video,
        path_or_hf_repo=model,
        word_timestamps=True,
        language=None if lang == "auto" else lang,
        # Without this a single hallucination (silence, music) poisons every
        # following segment.
        condition_on_previous_text=False,
        verbose=None,
    )
    segments = []
    for s in result["segments"]:
        segments.append({
            "start": float(s["start"]), "end": float(s["end"]), "text": s["text"],
            "no_speech_prob": float(s.get("no_speech_prob", 0.0)),
            "avg_logprob": float(s.get("avg_logprob", 0.0)),
            "compression_ratio": float(s.get("compression_ratio", 0.0)),
            "words": [
                {"word": w["word"], "start": float(w["start"]), "end": float(w["end"]),
                 "probability": float(w.get("probability", 1.0))}
                for w in s.get("words", [])
            ],
        })
    write_json(words_path, {"language": result.get("language", lang), "model": model, "segments": segments})
```

```python name="transcribe" extends="transcribe-defs" env="VIDEO,WORDS,SRC_LANG,WHISPER_MODEL" inputs="$VIDEO" outputs="$WORDS"
E = os.environ
transcribe(E["VIDEO"], E["WORDS"], E["SRC_LANG"], E["WHISPER_MODEL"])
```

Not unit-tested: it needs Whisper and a video, so it was exercised end to end.

### Segment
<!-- meshfox:node id="segment" x=480 y=0 w=360 h=60 -->
<!-- meshfox:edge from="transcribe" style="solid" -->

Groups words into subtitle cues in the *source* language: a new cue at a long
pause or sentence end; an over-long cue is cut at a sentence end, then a
clause break, else in the middle. Segments Whisper hallucinated (high
no-speech probability, runaway repetition) are dropped, and cues never
overlap.

```python name="segment-defs" extends="lib/core-defs"
import re

SENTENCE_END = re.compile(r"[.!?…。！？]['\")\]”’»]*$")
CLAUSE_END = re.compile(r"[,;:—–、，；：]['\")\]”’»]*$")


def is_hallucination(seg: dict) -> bool:
    """Whisper invents text on silence and music. These are its tells."""
    if seg.get("no_speech_prob", 0) > 0.6 and seg.get("avg_logprob", 0) < -1.0:
        return True
    return seg.get("compression_ratio", 0) > 2.4


def _join(words: list[dict], lang: str) -> str:
    return "".join(w["word"] for w in words).strip() if lang in CJK else \
        re.sub(r"\s+", " ", "".join(w["word"] for w in words)).strip()


def _best_cut(words: list[dict], lang: str, max_chars: int) -> int | None:
    """Where to break an over-long cue: after the last sentence end, else the
    last clause break (each only if it leaves a substantial first part), else
    in the middle so both halves come out about equal. The last word is the
    one that didn't fit, so it never ends up in the first part."""
    head = words[:-1]
    for pattern in (SENTENCE_END, CLAUSE_END):
        for j in range(len(head) - 1, 0, -1):
            if pattern.search(head[j - 1]["word"].strip()) and len(_join(head[:j], lang)) >= max_chars * 0.3:
                return j
    half = len(_join(words, lang)) / 2
    return min(range(1, len(head) + 1), key=lambda j: abs(len(_join(head[:j], lang)) - half))


def build_cues(segments: list[dict], lang: str, *, max_chars: int | None = None,
               max_dur: float = 6.5, max_gap: float = 0.7, min_chars: int = 12) -> list[dict]:
    """Group word timestamps into subtitle cues.

    A cue ends at a long pause, at the end of a sentence (once it has some
    substance), or when it would no longer fit on two lines / stay on screen
    too long -- then at the last clause break if there is a reasonable one.
    """
    max_chars = max_chars or (36 if lang in CJK else 84)
    words = [w for s in segments if not is_hallucination(s) for w in s.get("words", [])
             if w["word"].strip()]
    cues: list[list[dict]] = []
    cur: list[dict] = []

    def flush(upto: int | None = None) -> None:
        nonlocal cur
        take, cur = (cur, []) if upto is None else (cur[:upto], cur[upto:])
        if take:
            cues.append(take)

    for w in words:
        if cur:
            too_long = len(_join(cur + [w], lang)) > max_chars or w["end"] - cur[0]["start"] > max_dur
            if w["start"] - cur[-1]["end"] > max_gap:
                flush()
            elif too_long:
                flush(_best_cut(cur + [w], lang, max_chars) if len(cur) > 1 else None)
        cur.append(w)
        if SENTENCE_END.search(w["word"].strip()) and len(_join(cur, lang)) >= min_chars:
            flush()
    flush()

    # Merge fragments that are too small to read into a neighbour.
    merged: list[list[dict]] = []
    for c in cues:
        if (merged and (len(_join(c, lang)) < 8 or c[-1]["end"] - c[0]["start"] < 0.8)
                and c[0]["start"] - merged[-1][-1]["end"] <= max_gap
                and len(_join(merged[-1] + c, lang)) <= max_chars
                and not SENTENCE_END.search(merged[-1][-1]["word"].strip())):
            merged[-1] = merged[-1] + c
        else:
            merged.append(c)

    out = []
    for c in merged:
        out.append({"start": c[0]["start"], "end": c[-1]["end"], "text": _join(c, lang)})
    # Collapse the same line repeated over and over (another whisper habit).
    dedup: list[dict] = []
    for cue in out:
        if len(dedup) >= 2 and cue["text"] == dedup[-1]["text"] == dedup[-2]["text"]:
            continue
        dedup.append(cue)
    # Tidy timing: readable minimum, never overlapping the next cue.
    for k, cue in enumerate(dedup):
        cue["end"] = max(cue["end"], cue["start"] + 0.6)
        if k + 1 < len(dedup):
            cue["end"] = min(cue["end"], dedup[k + 1]["start"])
        cue["end"] = max(cue["end"], cue["start"] + 0.2)
        cue["i"] = k + 1
        cue["start"], cue["end"] = round(cue["start"], 3), round(cue["end"], 3)
    return [{"i": c["i"], "start": c["start"], "end": c["end"], "text": c["text"]} for c in dedup]
```

```python name="segment" extends="segment-defs" env="WORDS,CUES" deps="transcribe/transcribe" inputs="$WORDS" outputs="$CUES"
E = os.environ
data = read_json(E["WORDS"])
cues = build_cues(data["segments"], data.get("language", "en"))
write_json(E["CUES"], cues)
print(f"{len(cues)} cues -> {E['CUES']}")
```

Tests for the segmentation: pauses, sentence ends, balanced splits, hallucination filtering, CJK, overlap.

```python name="segment-test" extends="segment-defs"
import unittest


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
        cues = build_cues([seg(words("one two three four five six", gap_before={3: 2.0}))], "en")
        self.assertEqual([c["text"] for c in cues], ["one two three", "four five six"])

    def test_sentence_end_splits_once_cue_has_substance(self):
        cues = build_cues([seg(words("Hello everyone. Today we talk about subtitles."))], "en")
        self.assertEqual([c["text"] for c in cues], ["Hello everyone.", "Today we talk about subtitles."])

    def test_tiny_sentence_is_merged_not_left_alone(self):
        cues = build_cues([seg(words("Yes. We can do that for you today."))], "en")
        self.assertEqual(len(cues), 1)

    def test_overlong_sentence_splits_into_balanced_halves(self):
        text = "Today we are going to talk about how to build a small tool that translates subtitles."
        cues = build_cues([seg(words(text, step=0.2))], "en")
        self.assertEqual(len(cues), 2)
        self.assertTrue(all(len(c["text"]) <= 84 for c in cues))
        self.assertLess(abs(len(cues[0]["text"]) - len(cues[1]["text"])), 25)

    def test_prefers_clause_break_when_splitting(self):
        text = "It is surprisingly simple, and it works really well even on very long videos like this one."
        cues = build_cues([seg(words(text, step=0.2))], "en", max_chars=60)
        self.assertEqual(cues[0]["text"], "It is surprisingly simple,")

    def test_hallucinated_segments_are_dropped(self):
        good = seg(words("A real sentence of speech."))
        silence = seg(words("Thanks for watching!", start=20), no_speech_prob=0.9, avg_logprob=-1.5)
        loop = seg(words("la la la la", start=30), compression_ratio=3.0)
        cues = build_cues([good, silence, loop], "en")
        self.assertEqual([c["text"] for c in cues], ["A real sentence of speech."])

    def test_cjk_words_are_joined_without_spaces(self):
        ws = [{"word": c, "start": i * 0.2, "end": i * 0.2 + 0.15, "probability": 1} for i, c in enumerate("你好世界。")]
        self.assertEqual(build_cues([seg(ws)], "zh")[0]["text"], "你好世界。")

    def test_cues_are_ordered_numbered_and_never_overlap(self):
        cues = build_cues([seg(words("a b c d e f g h i j k l m n o p", gap_before={5: 1, 10: 1}))], "en")
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
        cues = build_cues([seg(ws)], "en")
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["end"], 0.4)          # wanted 0.6, capped at the next start

    def test_triple_repeat_is_collapsed(self):
        ws = []
        for k in range(4):
            ws += words("See you next time.", start=k * 10)
        cues = build_cues([seg(ws)], "en")
        self.assertEqual(len([c for c in cues if c["text"] == "See you next time."]), 2)


unittest.main(argv=["segment-test"], verbosity=2)
```

### Translate
<!-- meshfox:node id="translate" x=960 y=-150 w=360 h=60 color="6" tags="optional,agent" -->
<!-- meshfox:edge from="segment" style="solid" -->
<!-- meshfox:edge from="plan" label="?NEEDS_TRANSLATION" color="6" sourceSide="right" targetSide="left" -->

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

```python name="check-defs" interpreter="$PYTHON -u"
def check_translation(cues: list[dict], translated) -> list[str]:
    """Return a list of problems (empty = fine). The agent is told to keep a
    strict 1:1 mapping by index; this is where we make sure it did."""
    if not isinstance(translated, list):
        return ["the translation must be a JSON list of {i, text} objects"]
    problems = []
    want = [c["i"] for c in cues]
    got = [t.get("i") if isinstance(t, dict) else None for t in translated]
    if got != want:
        missing = sorted(set(want) - set(got))
        extra = sorted(x for x in set(got) if x not in set(want))
        problems.append(f"indices differ from the source: {len(got)} given, {len(want)} expected"
                        + (f"; missing {missing[:10]}" if missing else "")
                        + (f"; unexpected {extra[:10]}" if extra else "")
                        + ("; or out of order / duplicated" if not missing and not extra else ""))
        return problems
    for c, t in zip(cues, translated):
        text = t.get("text")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"cue {c['i']}: empty translation of {c['text']!r}")
        elif len(text) > max(40, len(c["text"])) * 3:
            problems.append(f"cue {c['i']}: translation is suspiciously long ({len(text)} vs {len(c['text'])} chars)")
    return problems
```

```python name="check" extends="lib/core-defs,check-defs" env="CUES,TRANSLATED" deps="translate"
E = os.environ
if os.path.getmtime(E["TRANSLATED"]) < os.path.getmtime(E["CUES"]):
    sys.exit("the translation file is older than the cues: the agent session ended without writing a new one")
cues = read_json(E["CUES"])
problems = check_translation(cues, read_json(E["TRANSLATED"]))
if problems:
    sys.exit("translation rejected:\n  " + "\n  ".join(problems[:20]))
print(f"translation ok ({len(cues)} cues)")
```

The checks are tested without any agent:

```python name="check-test" extends="check-defs"
import unittest


class CheckTests(unittest.TestCase):
    CUES = [{"i": 1, "text": "Hello"}, {"i": 2, "text": "World"}]

    def ok(self, tr):
        return check_translation(self.CUES, tr)

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


unittest.main(argv=["check-test"], verbosity=2)
```

If **check** reports a problem (a missing or reordered index, an empty line,
a runaway length), the run stops there — run **Translate** again; nothing
downstream has been touched.

### Export
<!-- meshfox:node id="export" x=1440 y=0 w=360 h=60 -->
<!-- meshfox:edge from="translate" label="if translated" color="6" -->
<!-- meshfox:edge from="segment" style="solid" -->

Writes the generated `.srt`: the translation when one was made, the original
cues otherwise, lines wrapped to at most two balanced lines. It is a plain
function of the cues, so it is rewritten whenever they change; your own edits go
to a copy made by **Edit**, never here. As a safeguard, a file that no longer
matches the sidecar (`*.srt.generated`) is left alone — delete it to regenerate.

```python name="srt-defs" extends="lib/core-defs"
import re


def fmt_srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def parse_srt_time(s: str) -> float:
    m = re.fullmatch(r"\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*", s)
    if not m:
        raise ValueError(f"bad SRT timestamp: {s!r}")
    h, mi, se, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, "0")) / 1000


def wrap_text(text: str, lang: str, width: int = 42) -> str:
    """At most two balanced lines (a lone word on line two reads badly)."""
    if lang in CJK or "\n" in text or len(text) <= width:
        return text
    spaces = [m.start() for m in re.finditer(" ", text)]
    if not spaces:
        return text
    cut = min(spaces, key=lambda p: abs(p - len(text) / 2))
    return text[:cut] + "\n" + text[cut + 1:]


def to_srt(cues: list[dict], lang: str) -> str:
    blocks = []
    for n, c in enumerate(cues, 1):
        blocks.append(f"{n}\n{fmt_srt_time(c['start'])} --> {fmt_srt_time(c['end'])}\n{wrap_text(c['text'], lang)}\n")
    return "\n".join(blocks)


def parse_srt(text: str) -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [ln for ln in block.split("\n")]
        if len(lines) < 2:
            continue
        k = 1 if "-->" not in lines[0] else 0
        a, _, b = lines[k].partition("-->")
        cues.append({"start": parse_srt_time(a), "end": parse_srt_time(b),
                     "text": "\n".join(lines[k + 1:]).strip()})
    return cues


def export_srt(cues: list[dict], translated, srt_path: str, *, use_translated: bool, lang: str) -> str:
    """Write the editable SRT -- but never clobber the user's own edits.

    A sidecar remembers the hash of what we last generated. If the file on disk
    differs from that, someone edited it, and it is left alone (delete it to
    regenerate)."""
    if use_translated:
        by_i = {t["i"]: t["text"] for t in translated}
        cues = [{**c, "text": by_i[c["i"]]} for c in cues]
    content = to_srt(cues, lang)
    path, side = Path(srt_path), Path(srt_path + ".generated")
    if path.exists() and side.exists() and sha(path.read_bytes()) != side.read_text().strip():
        return "kept"      # edited by hand
    if path.exists() and not side.exists():
        return "kept"      # not ours
    path.write_text(content, encoding="utf-8")
    side.write_text(sha(content.encode("utf-8")) + "\n")
    return "written"
```

```python name="export" extends="srt-defs" env="CUES,TRANSLATED,SRT,NEEDS_TRANSLATION,SRC_USED,SRC_LANG,DST_LANG" deps="segment/segment,translate/check?NEEDS_TRANSLATION" outputs="$SRT"
E = os.environ
use = env_flag("NEEDS_TRANSLATION")
lang = E["DST_LANG"] if use else (E.get("SRC_USED") or E["SRC_LANG"])
res = export_srt(read_json(E["CUES"]), read_json(E["TRANSLATED"]) if use else None, E["SRT"],
                 use_translated=use, lang=lang)
print(f"{E['SRT']}: {'kept your edits' if res == 'kept' else 'written'}")
```

The SRT functions are also what **Render** reads the subtitles back with (it extends `export/srt-defs`). Tests: the timestamp format, round trip, and the guarantee that hand edits survive a re-export.

```python name="srt-test" extends="srt-defs"
import unittest
from tempfile import TemporaryDirectory


class SrtTests(unittest.TestCase):
    def test_roundtrip(self):
        cues = [{"start": 0.0, "end": 1.5, "text": "Hello"}, {"start": 3661.25, "end": 3662.0, "text": "two\nlines"}]
        back = parse_srt(to_srt(cues, "ru"))
        self.assertEqual([(c["start"], c["end"], c["text"]) for c in back],
                         [(0.0, 1.5, "Hello"), (3661.25, 3662.0, "two\nlines")])

    def test_timestamp_format(self):
        self.assertEqual(fmt_srt_time(3723.456), "01:02:03,456")

    def test_parse_tolerates_crlf_and_missing_index(self):
        text = "00:00:01,000 --> 00:00:02,000\r\nHi\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nThere\r\n"
        self.assertEqual([c["text"] for c in parse_srt(text)], ["Hi", "There"])

    def test_wrap_balances_two_lines(self):
        out = wrap_text("Today we are going to talk about how to build", "en")
        a, b = out.split("\n")
        self.assertLess(abs(len(a) - len(b)), 8)
        self.assertEqual(wrap_text("short", "en"), "short")


class ExportTests(unittest.TestCase):
    CUES = [{"i": 1, "start": 0, "end": 1, "text": "Hello"}, {"i": 2, "start": 1, "end": 2, "text": "World"}]
    TR = [{"i": 1, "text": "Привет"}, {"i": 2, "text": "Мир"}]

    def test_uses_translation_when_asked(self):
        with TemporaryDirectory() as d:
            srt = str(Path(d) / "x.srt")
            self.assertEqual(export_srt(self.CUES, self.TR, srt, use_translated=True, lang="ru"), "written")
            self.assertIn("Привет", Path(srt).read_text())

    def test_regenerates_an_untouched_file(self):
        with TemporaryDirectory() as d:
            srt = str(Path(d) / "x.srt")
            export_srt(self.CUES, None, srt, use_translated=False, lang="en")
            self.assertEqual(export_srt(self.CUES, self.TR, srt, use_translated=True, lang="ru"), "written")
            self.assertIn("Мир", Path(srt).read_text())

    def test_never_overwrites_hand_edits(self):
        with TemporaryDirectory() as d:
            srt = Path(d) / "x.srt"
            export_srt(self.CUES, None, str(srt), use_translated=False, lang="en")
            srt.write_text(srt.read_text().replace("World", "Everybody"))
            self.assertEqual(export_srt(self.CUES, self.TR, str(srt), use_translated=True, lang="ru"), "kept")
            self.assertIn("Everybody", srt.read_text())

    def test_does_not_adopt_a_foreign_srt(self):
        with TemporaryDirectory() as d:
            srt = Path(d) / "x.srt"
            srt.write_text("mine")
            self.assertEqual(export_srt(self.CUES, None, str(srt), use_translated=False, lang="en"), "kept")
            self.assertEqual(srt.read_text(), "mine")


unittest.main(argv=["srt-test"], verbosity=2)
```

### Edit (optional)
<!-- meshfox:node id="edit" x=1920 y=0 w=360 h=60 color="6" tags="optional,interactive" -->
<!-- meshfox:edge from="export" style="solid" -->

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

### Render
<!-- meshfox:node id="render" x=2400 y=0 w=360 h=60 -->
<!-- meshfox:edge from="edit" label="?EDIT" color="6" -->
<!-- meshfox:edge from="export" style="solid" -->

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

```python name="render-defs" extends="export/srt-defs"
import shutil
import subprocess
import tempfile


def esc_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def fmt_ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


ALIGNMENT = {"bottom": 2, "middle": 5, "top": 8}  # ASS numpad alignment, centred


def ass_color(hex_rgb: str) -> str:
    """'#RRGGBB' -> ASS '&H00BBGGRR'."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_rgb.strip())
    if not m:
        raise SystemExit(f"SUB_COLOR must look like #FFFFFF, got {hex_rgb!r}")
    r, g, b = m.group(1)[0:2], m.group(1)[2:4], m.group(1)[4:6]
    return f"&H00{b}{g}{r}".upper()


def to_ass(cues: list[dict], *, width: int, height: int, font: str, size_pct: float = 5.5,
           pos: str = "bottom", margin_pct: float = 5.0, color: str = "#FFFFFF") -> str:
    """Sizes and margins are percentages of the video height, so one setting
    looks the same on 720p, 4K and portrait video."""
    if pos not in ALIGNMENT:
        raise SystemExit(f"SUB_POS must be one of {', '.join(ALIGNMENT)}, got {pos!r}")
    if not 1 <= size_pct <= 25:
        raise SystemExit(f"SUB_SIZE must be between 1 and 25 (% of the video height), got {size_pct}")
    if not 0 <= margin_pct <= 45:
        raise SystemExit(f"SUB_MARGIN must be between 0 and 45 (% of the video height), got {margin_pct}")
    size = round(height * size_pct / 100)
    margin_v = round(height * margin_pct / 100)
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
        "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        f"Style: Default,{font},{size},{ass_color(color)},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(2, round(size / 14))},0,{ALIGNMENT[pos]},{round(width * 0.05)},{round(width * 0.05)},{margin_v},1",
        "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        *[f"Dialogue: 0,{fmt_ass_time(c['start'])},{fmt_ass_time(c['end'])},Default,,0,0,0,,{esc_ass(c['text'])}"
          for c in cues],
        "",
    ])


def video_size(video: str) -> tuple[int, int]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", video], capture_output=True, text=True, check=True).stdout.strip()
        w, h = out.split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080


def ffmpeg_has_libass() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return False
    return bool(re.search(r"^\s*\S+\s+subtitles\s", out, re.M))


def render_command(video: str, ass: str, output: str, *, tool: str) -> list[str]:
    """`ass` must be a plain relative name (we run in a temp dir) -- no
    filter-escaping of odd characters in paths."""
    if tool == "ffmpeg":
        return ["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-vf", f"ass={ass}",
                "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "copy", output]
    return ["mpv", "--no-config", "--really-quiet", video, f"--sub-file={ass}", "--sid=auto",
            "--no-sub-auto", "--o=" + output, "--ovc=libx264", "--ovcopts=crf=18,preset=medium",
            "--oac=aac", "--oacopts=b=192k"]


def render(srt: str, video: str, output: str, font: str, ass_out: str, **style) -> str:
    cues = parse_srt(Path(srt).read_text(encoding="utf-8"))
    w, h = video_size(video)
    Path(ass_out).write_text(to_ass(cues, width=w, height=h, font=font, **style), encoding="utf-8")
    tool = "ffmpeg" if ffmpeg_has_libass() else "mpv"
    if tool == "mpv" and not shutil.which("mpv"):
        raise SystemExit("neither an ffmpeg with libass (the `subtitles` filter) nor mpv is available")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(ass_out, Path(tmp) / "sub.ass")
        cmd = render_command(str(Path(video).resolve()), "sub.ass", str(Path(output).resolve()), tool=tool)
        subprocess.run(cmd, cwd=tmp, check=True)
    return tool
```

```python name="render" extends="render-defs" env="SRT,SRT_EDITED,EDIT,ASS,VIDEO,OUTPUT,SUB_FONT,SUB_SIZE,SUB_POS,SUB_MARGIN,SUB_COLOR" deps="edit/edit?EDIT" inputs="$SRT,$SRT_EDITED,$VIDEO" outputs="$OUTPUT"
E = os.environ
srt = E["SRT_EDITED"] if env_flag("EDIT") else E["SRT"]
tool = render(srt, E["VIDEO"], E["OUTPUT"], E["SUB_FONT"], E["ASS"],
              size_pct=float(E["SUB_SIZE"]), pos=E["SUB_POS"],
              margin_pct=float(E["SUB_MARGIN"]), color=E["SUB_COLOR"])
print(f"rendered with {tool} -> {E['OUTPUT']}")
```

Tests for the ASS script, the encoder command lines and the style options (the encoding itself needs a video, so it is exercised end to end):

```python name="render-test" extends="render-defs"
import unittest


class RenderTests(unittest.TestCase):
    def test_ass_escapes_and_sizes_to_the_video(self):
        ass = to_ass([{"start": 0, "end": 1.5, "text": "a {b}\nc \\ d"}], width=1280, height=720, font="Arial")
        self.assertIn("PlayResX: 1280", ass)
        self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,a \\{b\\}\\Nc \\\\ d", ass)
        self.assertIn("Style: Default,Arial,40,", ass)

    def test_ffmpeg_command_uses_a_plain_relative_ass_name(self):
        cmd = render_command("/v/a b (1).mp4", "sub.ass", "/o/out.mp4", tool="ffmpeg")
        self.assertIn("ass=sub.ass", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], "/v/a b (1).mp4")   # path passed as one argv item

    def test_mpv_command_keeps_audio_and_picks_our_subs_only(self):
        cmd = render_command("/v/a.mp4", "sub.ass", "/o/out.mp4", tool="mpv")
        self.assertIn("--sub-file=sub.ass", cmd)
        self.assertIn("--no-sub-auto", cmd)
        self.assertIn("--oac=aac", cmd)

    def test_default_style_is_unchanged(self):
        ass = to_ass([{"start": 0, "end": 1, "text": "a"}], width=1080, height=1920, font="Arial")
        self.assertIn("Style: Default,Arial,106,&H00FFFFFF,", ass)
        self.assertIn(",2,54,54,96,1", ass)  # bottom-centre, 5% margins

    def test_style_options(self):
        ass = to_ass([{"start": 0, "end": 1, "text": "a"}], width=1000, height=1000, font="X",
                          size_pct=4, pos="top", margin_pct=10, color="#FFCC00")
        self.assertIn("Style: Default,X,40,&H0000CCFF,", ass)  # ASS colours are BGR
        self.assertIn(",8,50,50,100,1", ass)

    def test_style_rejects_nonsense(self):
        cue = [{"start": 0, "end": 1, "text": "a"}]
        for kw in ({"pos": "left"}, {"size_pct": 0}, {"size_pct": 90}, {"margin_pct": -1}, {"color": "red"}):
            with self.assertRaises(SystemExit):
                to_ass(cue, width=100, height=100, font="X", **kw)


unittest.main(argv=["render-test"], verbosity=2)
```

### Plan: is translation needed?
<!-- meshfox:node id="plan" x=360 y=-150 w=360 h=60 -->
<!-- meshfox:edge from="transcribe" style="solid" sourceSide="top" targetSide="left" -->

Compares the spoken language (the detected one when `SRC_LANG=auto`) with
`DST_LANG` and publishes `NEEDS_TRANSLATION` and `SRC_USED`. That computed
boolean is what the conditional dependency on **Translate** looks at.

```python name="plan" extends="lib/core-defs" env="WORDS,SRC_LANG,DST_LANG" deps="transcribe/transcribe"
E = os.environ
spoken = E["SRC_LANG"]
if spoken == "auto":  # Whisper's guess, stored with the transcript
    spoken = read_json(E["WORDS"]).get("language") or "en"
vars_out(SRC_USED=spoken, NEEDS_TRANSLATION="true" if spoken != E["DST_LANG"] else "false")
```

### Transcript (`WORDS`)
<!-- meshfox:node id="preview-words" type="file" x=0 y=150 w=360 h=60 display="code" lang="json" -->
<!-- meshfox:edge from="transcribe"  sourceSide="bottom" targetSide="top" style="solid" -->

[WORDS]($WORDS)

Word-level transcript straight from Whisper: segments, words, per-word timestamps and probabilities.

### Cues (`CUES`)
<!-- meshfox:node id="preview-cues" type="file" x=480 y=150 w=360 h=60 display="code" lang="json" -->
<!-- meshfox:edge from="segment"  sourceSide="bottom" targetSide="top" style="solid" -->

[CUES]($CUES)

The transcript cut into subtitle cues, in the spoken language. This is what the translation step reads.

### Translated cues (`TRANSLATED`)
<!-- meshfox:node id="preview-translated" type="file" x=960 y=150 w=360 h=60 display="code" lang="json" -->
<!-- meshfox:edge from="translate"  sourceSide="bottom" targetSide="top" style="solid" -->

[TRANSLATED]($TRANSLATED)

The agent's translation, one object per cue, same `i`. Exists only when translation was needed.

### Generated subtitles (`SRT`)
<!-- meshfox:node id="preview-srt" type="file" x=1440 y=150 w=360 h=60 display="code" lang="text" -->
<!-- meshfox:edge from="export"  sourceSide="bottom" targetSide="top" style="solid" -->

[SRT]($SRT)

The generated subtitles: what **Edit** starts from and, without editing, what **Render** burns in.

### Edited subtitles (`SRT_EDITED`)
<!-- meshfox:node id="preview-srt-edited" type="file" x=1920 y=150 w=360 h=60 display="code" lang="text" -->
<!-- meshfox:edge from="edit"  sourceSide="bottom" targetSide="top" style="solid" -->

[SRT_EDITED]($SRT_EDITED)

Your copy of the subtitles: what **Render** burns in when `EDIT` is true. It exists once **Edit** has run.

### Burn-in script (`ASS`)
<!-- meshfox:node id="preview-ass" type="file" x=2400 y=150 w=360 h=60 display="code" lang="text" -->
<!-- meshfox:edge from="render"  sourceSide="bottom" targetSide="top" style="solid" -->

[ASS]($ASS)

Styled and sized to the video, regenerated by **Render** on every run.

### Result (OUTPUT)
<!-- meshfox:node id="result-output" type="file" x=2880 y=0 w=360 -->
<!-- meshfox:edge from="render" -->

[OUTPUT]($OUTPUT)

The finished video with the subtitles burned in, written by **Render** where you asked for it.

## Tech details
<!-- meshfox:node id="tech-details" -->

The environment, shared code, path handling and tests: everything the pipeline steps rely on.

### Python environment
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

### Shared helpers
<!-- meshfox:node id="lib" -->

The helpers every step uses: reading the environment, handing values on to
meshfox through `MESHFOX_VARS_OUT`, JSON, hashing. They are ordinary code, kept
in this one block; a step does not import it. Instead a block that writes
`extends="lib/core-defs"` runs with this block's text in front of its own (see
the `extends=` recipe in meshfox's README), so what is defined here is simply
there for it. This block is only borrowed from: it does nothing when run. It begins with
`from __future__ import annotations`, so it always comes first in an
`extends=` list.

The rest of the code lives next to the step that owns it, in a `*-defs` block
the step and its tests both extend. That keeps a function, the step that uses
it and its tests on one screen, and — because the code is part of each block —
editing a function makes exactly the steps that use it stale, which a separate
helper file never could.

```python name="core-defs" interpreter="$PYTHON -u"
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

CJK = {"zh", "ja", "ko"}


def vars_out(**kv: str) -> None:
    """Publish values to meshfox (`meshfox:var ... from=`), or print them."""
    target = os.environ.get("MESHFOX_VARS_OUT")
    lines = "".join(f"{k}={v}\n" for k, v in kv.items())
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(lines)
    sys.stdout.write(lines)


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def sha(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, obj) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
```

### Paths
<!-- meshfox:node id="paths" -->

Derives every intermediate file name from `OUTPUT` and `WORK_DIR` (never next
to the result) and publishes them as `WORDS`, `CUES`, `TRANSLATED`, `SRT`,
`SRT_EDITED` and `ASS`.

```python name="paths-defs" extends="lib/core-defs"
def derive_paths(output: str, work_dir: str) -> dict[str, str]:
    """Intermediate files live in `work_dir`, never next to the result (a
    player would auto-load `out.srt` / `out.ass` beside `out.mp4` on top of the
    burned-in subtitles). Named after OUTPUT's stem plus a short hash of its
    full path, so two outputs called `talk.mp4` do not share state."""
    out = Path(output).expanduser().resolve()
    tag = hashlib.sha1(str(out).encode("utf-8")).hexdigest()[:8]
    stem = str(Path(work_dir).expanduser().resolve() / f"{out.stem}-{tag}")
    return {
        "WORDS": stem + ".words.json",
        "CUES": stem + ".cues.json",
        "TRANSLATED": stem + ".cues.translated.json",
        "SRT": stem + ".srt",
        "SRT_EDITED": stem + ".edited.srt",
        "ASS": stem + ".ass",
    }
```

The step itself adds the three lines that use it:

```python name="paths" extends="paths-defs" env="OUTPUT,WORK_DIR"
E = os.environ
Path(E["WORK_DIR"]).mkdir(parents=True, exist_ok=True)
vars_out(**derive_paths(E["OUTPUT"], E["WORK_DIR"]))
```

And its tests, which extend the same definitions:

```python name="paths-test" extends="paths-defs"
import unittest


class PathsTests(unittest.TestCase):
    def test_paths_derive_from_output(self):
        p = derive_paths("/o/talk (1).subbed.mp4", "/w")
        self.assertRegex(p["SRT"], r"^/w/talk \(1\)\.subbed-[0-9a-f]{8}\.srt$")
        self.assertTrue(p["WORDS"].endswith(".words.json"))
        self.assertTrue(all(v.startswith("/w/") for v in p.values()))  # nothing next to OUTPUT

    def test_same_stem_in_different_folders_does_not_collide(self):
        a = derive_paths("/a/talk.mp4", "/w")
        b = derive_paths("/b/talk.mp4", "/w")
        self.assertTrue(set(a.values()).isdisjoint(b.values()))

    def test_the_edited_copy_is_a_sibling_of_the_generated_srt(self):
        p = derive_paths("/o/talk.mp4", "/w")
        self.assertEqual(p["SRT_EDITED"], p["SRT"][:-len(".srt")] + ".edited.srt")


unittest.main(argv=["paths-test"], verbosity=2)
```

### Tests
<!-- meshfox:node id="tests" -->

Every function above has unit tests next to it (`paths-test`, `segment-test`,
`check-test`, `srt-test`, `render-test`). Each runs on its own from its node;
this block runs all of them. They need no video, Whisper or agent: the
transcription call and the encoders themselves were exercised end to end.

```bash name="tests" default deps="paths/paths-test,segment/segment-test,translate/check-test,export/srt-test,render/render-test"
echo "all subtitle tests passed"
```

## Design notes
<!-- meshfox:node id="design-notes" -->

Why the tool is built the way it is: the alternatives that were considered.

### Design note: a subtitle editor in the middle
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

### Why mpv for burning in
<!-- meshfox:node id="why-mpv" -->

On the machine this was built on, `ffmpeg -h filter=subtitles` says
`Unknown filter` — no libass. `mpv` always ships libass and has an encode mode
(`--o=`), so it renders the very same `.ass` into H.264/AAC without rebuilding
ffmpeg. If your ffmpeg does have libass it is used instead (it is also faster
to start). Burning in is a re-encode either way: CRF 18, x264, same
resolution and frame rate as the source.

