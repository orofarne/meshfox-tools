<!-- meshfox:canvas -->
# meshfox-tools

<!-- meshfox:comment -->
> This is a [meshfox](https://meshfox.orofarne.net/) document — open it
> with `meshfox view` (or `meshfox tui`) for the interactive canvas.
> This note is only visible here, in a plain Markdown viewer.
<!-- /meshfox:comment -->

Small utilities around [meshfox](https://meshfox.orofarne.net/) canvases.
One tool, one directory; each directory has its own `README.canvas.md`,
and for the runnable tools that canvas *is* the tool — environment, scripts
and tests live inside it, so there is nothing to install. Open this file
with `meshfox view README.md` and click through to a tool.

## circle-vertical
<!-- meshfox:node id="circle-vertical" type="file" -->

[circle-vertical/README.canvas.md](./circle-vertical/README.canvas.md)

Turns a Telegram video note (кружочек) into a tidy vertical video: a smooth-edged circle on a gradient, blurred-video or flat-colour background, with configurable resolution and circle position.

## obsidian2meshfox
<!-- meshfox:node id="obsidian2meshfox" type="file" -->

[obsidian2meshfox/README.canvas.md](./obsidian2meshfox/README.canvas.md)

Converts Obsidian JSON Canvas files (`*.canvas`) into meshfox canvases, with an optional AI-agent pass to tidy the result.

## second-brain
<!-- meshfox:node id="second-brain" type="file" -->

[second-brain/README.canvas.md](./second-brain/README.canvas.md)

A ready-to-copy `CLAUDE.md` template that turns a meshfox canvas into persistent project memory for Claude Code.

## subtitles
<!-- meshfox:node id="subtitles" type="file" -->

[subtitles/README.canvas.md](./subtitles/README.canvas.md)

Transcribes a video locally with Whisper, optionally translates the subtitles with your coding agent, lets you edit them, and burns them in.
