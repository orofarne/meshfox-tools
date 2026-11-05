<!-- meshfox:canvas -->
# Telegram circle → vertical video
<!-- meshfox:node id="root" -->

<!-- meshfox:comment -->
> This is a [meshfox](https://meshfox.orofarne.net/) document — open it
> with `meshfox view` (or `meshfox tui`) for the interactive canvas.
> This note is only visible here, in a plain Markdown viewer.
<!-- /meshfox:comment -->

Turns a Telegram video note (the round "кружочек", delivered as a small square
video) into a tidy vertical video of any size, 1080×1920 by default: the
picture is cut to a smooth-edged circle, placed on the canvas and the rest is
filled with a background of your choice. This canvas is the whole tool: the
code, its tests and the one pipeline step live in the nodes below. It needs
only `ffmpeg` and `python3` on the `PATH`.

```button name="main" default deps="render/render"
▶ Make the vertical video
```

<!-- meshfox:var name="VIDEO" type="file" ext="mp4,mkv,mov,webm,m4v" prompt="Telegram circle video (square or any video: it is cropped to a centred square)" -->
<!-- meshfox:var name="OUTPUT" type="file" mode="save" ext="mp4" prompt="Where to write the result (.mp4)" -->
<!-- meshfox:var name="RESOLUTION" default="1080x1920" prompt="Target resolution, WIDTHxHEIGHT (even numbers), e.g. 1080x1920, 720x1280, 1080x1080" -->
<!-- meshfox:var name="BACKGROUND" type="select" choices="gradient,video,color" default="gradient" prompt="Background: gradient (colours of the video, top to bottom), video (blurred enlarged copy), color (one flat colour)" -->
<!-- meshfox:var name="BG_COLOR" default="#101010" prompt="Colour for BACKGROUND=color, #RRGGBB (ignored otherwise)" -->
<!-- meshfox:var name="CIRCLE_SIZE" default="89" prompt="Circle diameter, % of the video width (89 is 960 px at 1080 wide)" -->
<!-- meshfox:var name="CIRCLE_POS" default="50" prompt="Vertical position of the circle's centre, % of the height from the top (50 = centred, 33 = upper third)" -->

## Render
<!-- meshfox:node id="render" -->

One `ffmpeg` call builds the whole picture:

1. **The circle.** The video is cut to a centred square, scaled (Lanczos) to
   `CIRCLE_SIZE` and given an alpha channel from a per-pixel formula — one
   pixel of anti-aliased edge, so there is no stair-stepping.
2. **The background**, by `BACKGROUND`:
   - `gradient` — the average colours of the top, middle and bottom of the
     video (inner square only: the corners of a Telegram circle are white or
     black and would stain it), smoothed in time over ~20 frames so it never
     flickers, blown up and blurred into a vertical gradient, saturated a bit.
     (Sampling more than one column makes visible vertical stripes.)
   - `video` — the same inner square enlarged to cover the canvas and heavily
     blurred, a little darker.
   - `color` — flat `BG_COLOR`.
3. **The circle** is overlaid horizontally centred, its centre at `CIRCLE_POS`
   percent of the height (clamped so it never leaves the canvas).

Output is H.264 (CRF 18) at a constant 30 fps — Telegram notes are often
variable-frame-rate — with the audio re-encoded to AAC 160k, `+faststart`.
The circle is scaled *up* from the 400 px source, so it is a little soft: a
smaller `CIRCLE_SIZE` looks sharper.

```python name="render-defs" interpreter="python3 -u"
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

BACKGROUNDS = ("gradient", "video", "color")
FPS = 30


def parse_resolution(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", text)
    if not m:
        raise SystemExit(f"RESOLUTION must look like 1080x1920, got {text!r}")
    w, h = int(m.group(1)), int(m.group(2))
    if w < 64 or h < 64 or w % 2 or h % 2 or w > 8192 or h > 8192:
        raise SystemExit(f"RESOLUTION needs even sides between 64 and 8192, got {w}x{h}")
    return w, h


def parse_color(text: str) -> str:
    """'#RRGGBB' -> ffmpeg '0xRRGGBB'."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", text.strip())
    if not m:
        raise SystemExit(f"BG_COLOR must look like #101010, got {text!r}")
    return "0x" + m.group(1).upper()


def circle_geometry(w: int, h: int, size_pct: float, pos_pct: float) -> tuple[int, int, int]:
    """(diameter, x, y) of the circle's bounding square on a w x h canvas."""
    if not 5 <= size_pct <= 100:
        raise SystemExit(f"CIRCLE_SIZE must be between 5 and 100 (% of the width), got {size_pct}")
    if not 0 <= pos_pct <= 100:
        raise SystemExit(f"CIRCLE_POS must be between 0 and 100 (% of the height), got {pos_pct}")
    d = round(w * size_pct / 100) // 2 * 2
    if d > h:
        raise SystemExit(f"a circle of {d} px does not fit into a canvas {h} px high; lower CIRCLE_SIZE")
    x = (w - d) // 2
    y = min(max(round(h * pos_pct / 100 - d / 2), 0), h - d)
    return d, x, y


def background_chain(mode: str, w: int, h: int, color: str) -> str:
    """Filters from the pad `[a]` (the full, square-cropped video) to `[bg]`."""
    if mode == "gradient":
        # 1 column x 3 rows of average colour, smoothed over time, then blown up
        # in two steps: nearest to a small canvas, blur it, scale to size.
        return ("[a]crop=iw*0.7:ih*0.7,scale=1:3:flags=area,tmix=frames=20,"
                "scale=54:96:flags=neighbor,gblur=sigma=14:steps=4,"
                f"scale={w}:{h}:flags=bicubic,eq=saturation=1.6:brightness=0.03[bg]")
    if mode == "video":
        sw, sh = max(2, w // 8), max(2, h // 8)   # blur small, it is much cheaper and smoother
        return (f"[a]crop=iw*0.7:ih*0.7,scale={sw}:{sh}:force_original_aspect_ratio=increase,"
                f"crop={sw}:{sh},gblur=sigma={max(1.0, h * 0.03 / 8):.2f}:steps=3,"
                f"scale={w}:{h}:flags=bicubic,eq=brightness=-0.1:saturation=1.3[bg]")
    if mode == "color":
        return f"[a]scale={w}:{h},drawbox=x=0:y=0:w=iw:h=ih:color={color}:t=fill[bg]"
    raise SystemExit(f"BACKGROUND must be one of {', '.join(BACKGROUNDS)}, got {mode!r}")


def build_filter(w: int, h: int, *, background: str, color: str, size_pct: float, pos_pct: float) -> str:
    d, x, y = circle_geometry(w, h, size_pct, pos_pct)
    alpha = "255*clip(W/2-hypot(X-W/2+0.5,Y-H/2+0.5)+0.5,0,1)"
    return ";".join([
        f"[0:v]fps={FPS},crop='min(iw,ih)':'min(iw,ih)',split[a][b]",
        background_chain(background, w, h, color),
        f"[b]scale={d}:{d}:flags=lanczos,format=yuva420p,"
        f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='{alpha}'[fg]",
        f"[bg][fg]overlay={x}:{y},format=yuv420p[v]",
    ])


def render_command(video: str, output: str, filtergraph: str) -> list[str]:
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-filter_complex", filtergraph,
            "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", output]


def render(video: str, output: str, *, resolution: str, background: str, bg_color: str,
           size_pct: float, pos_pct: float) -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is not on the PATH")
    w, h = parse_resolution(resolution)
    graph = build_filter(w, h, background=background, color=parse_color(bg_color),
                         size_pct=size_pct, pos_pct=pos_pct)
    Path(output).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(render_command(str(Path(video).expanduser().resolve()),
                                  str(Path(output).expanduser().resolve()), graph), check=True)
```

```python name="render" extends="render-defs" env="VIDEO,OUTPUT,RESOLUTION,BACKGROUND,BG_COLOR,CIRCLE_SIZE,CIRCLE_POS" inputs="$VIDEO" outputs="$OUTPUT"
E = os.environ
render(E["VIDEO"], E["OUTPUT"], resolution=E["RESOLUTION"], background=E["BACKGROUND"],
       bg_color=E["BG_COLOR"], size_pct=float(E["CIRCLE_SIZE"]), pos_pct=float(E["CIRCLE_POS"]))
print(f"rendered -> {E['OUTPUT']}")
```

Tests for the option parsing, the circle geometry and the filter graph (the
encoding itself needs a video, so it is exercised end to end):

```python name="render-test" extends="render-defs"
import unittest


class RenderTests(unittest.TestCase):
    def test_resolution(self):
        self.assertEqual(parse_resolution("1080x1920"), (1080, 1920))
        self.assertEqual(parse_resolution(" 720 X 1280 "), (720, 1280))
        for bad in ("1080", "1081x1920", "10x10", "axb", "1080x"):
            with self.assertRaises(SystemExit):
                parse_resolution(bad)

    def test_color(self):
        self.assertEqual(parse_color("#ff8800"), "0xFF8800")
        with self.assertRaises(SystemExit):
            parse_color("orange")

    def test_default_geometry_is_the_centred_960_circle(self):
        self.assertEqual(circle_geometry(1080, 1920, 89, 50), (960, 60, 480))

    def test_position_moves_the_centre_and_is_clamped(self):
        d, _, y = circle_geometry(1080, 1920, 89, 33)
        self.assertEqual(y + d // 2, round(1920 * 0.33))
        self.assertEqual(circle_geometry(1080, 1920, 89, 0)[2], 0)
        self.assertEqual(circle_geometry(1080, 1920, 89, 100)[2], 1920 - 960)

    def test_geometry_rejects_nonsense(self):
        for args in ((1080, 1920, 2, 50), (1080, 1920, 101, 50), (1080, 1920, 89, -1), (1080, 500, 89, 50)):
            with self.assertRaises(SystemExit):
                circle_geometry(*args)

    def test_each_background_ends_in_bg_and_uses_the_resolution(self):
        for mode in BACKGROUNDS:
            chain = background_chain(mode, 720, 1280, "0x101010")
            self.assertTrue(chain.startswith("[a]") and chain.endswith("[bg]"), mode)
            self.assertIn("720", chain)
        self.assertIn("0x101010", background_chain("color", 720, 1280, "0x101010"))
        with self.assertRaises(SystemExit):
            background_chain("plaid", 720, 1280, "0x101010")

    def test_filter_graph_is_connected(self):
        g = build_filter(1080, 1920, background="gradient", color="0x000000", size_pct=89, pos_pct=50)
        self.assertIn("split[a][b]", g)
        self.assertIn("scale=960:960", g)
        self.assertIn("overlay=60:480", g)
        self.assertTrue(g.endswith("[v]"))

    def test_command_passes_paths_as_single_args_and_keeps_optional_audio(self):
        cmd = render_command("/v/a b (1).mp4", "/o/out.mp4", "G")
        self.assertEqual(cmd[cmd.index("-i") + 1], "/v/a b (1).mp4")
        self.assertIn("0:a?", cmd)
        self.assertEqual(cmd[-1], "/o/out.mp4")


unittest.main(argv=["render-test"], verbosity=2)
```

### Result (OUTPUT)
<!-- meshfox:node id="result-output" type="file" -->

[OUTPUT]($OUTPUT)

The finished vertical video, written by **Render** where you asked for it.

## Tech details
<!-- meshfox:node id="tech-details" -->

### Tests
<!-- meshfox:node id="tests" -->

Unit tests live next to the code they test (`render-test`); this block runs
them all. They need neither a video nor `ffmpeg`.

```bash name="tests" default deps="render/render-test"
echo "all circle-vertical tests passed"
```
