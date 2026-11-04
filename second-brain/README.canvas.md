<!-- meshfox:canvas -->
# Second brain: CLAUDE.md template

<!-- meshfox:comment -->
> This is a [meshfox](https://meshfox.orofarne.net/) document — open it
> with `meshfox view` (or `meshfox tui`) for the interactive canvas.
> This note is only visible here, in a plain Markdown viewer.
<!-- /meshfox:comment -->

[`CLAUDE.md`](./CLAUDE.md) in this directory is a ready-to-copy Claude Code
project template for using a meshfox canvas (`MEMORY.canvas.md`) as a
persistent second brain — memory that survives across sessions instead of
living only in a chat transcript.

It covers the same four memory types (`user` / `feedback` / `project` /
`reference`) as meshfox's own
[second-brain example](https://github.com/orofarne/meshfox/blob/main/examples/second-brain.canvas.md),
a constraint fence that enforces a `**Why:**` line on every `feedback` /
`project` entry, and the `auto-timestamps` option so `meshfox node find
--since` has something to filter on.

**Use it:** copy `CLAUDE.md` into your project as its own `CLAUDE.md` (merge
by hand if one exists), then follow its "First-time setup" section to
bootstrap `MEMORY.canvas.md`. Every command it documents — bootstrap,
`node add` / `node body` / `node find`, `validate` / `check` — was run
against the real `meshfox` binary while writing it.
