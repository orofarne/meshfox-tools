#!/usr/bin/env python3
"""Shared helpers for the subtitle canvas (README.canvas.md).

Everything that is not "call another program" lives here: segmentation of
word timestamps into cues, SRT/ASS, translation checks, edit-safe export.
The canvas blocks are thin: each one imports what it needs from this module
(they run in this directory, so `import subs_lib` just works), reads its
options from the environment and passes values on via meshfox's
MESHFOX_VARS_OUT (see `vars_out`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CJK = {"zh", "ja", "ko"}
SENTENCE_END = re.compile(r"[.!?…。！？]['\")\]”’»]*$")
CLAUSE_END = re.compile(r"[,;:—–、，；：]['\")\]”’»]*$")


# --------------------------------------------------------------- small utils
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


# --------------------------------------------------------------------- paths
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


# ---------------------------------------------------------------- transcribe
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


# ------------------------------------------------------------------- segment
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


# --------------------------------------------------------------------- check
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


# -------------------------------------------------------------------- export
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


# -------------------------------------------------------------------- render
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
