# Project memory (meshfox second brain)

This project keeps its own persistent memory in a
[meshfox](https://meshfox.orofarne.net/) canvas: `MEMORY.canvas.md` at the
repo root. Unlike this `CLAUDE.md`, which is static instructions, that file
is a living record you read from and write to as you work — a second brain
that survives across sessions, machines, and (if committed) contributors.

Read this whole file once at the start of a session. It tells you *when*
and *how* to use `MEMORY.canvas.md` — not what's currently in it.

## Where memory lives

- One memory = one node. Each is a `##` heading directly under the root,
  with a `<!-- meshfox:node tags="..." -->` comment carrying exactly one of
  the four tags below.
- The file's root node carries a `` ```starlark constraint `` fence (see
  "First-time setup") enforcing the one rule that actually matters: every
  `feedback`/`project` memory's body contains a `**Why:**` line. Run
  `meshfox check MEMORY.canvas.md` after writing to catch a violation —
  `meshfox validate` alone won't, since a missing `**Why:**` still parses
  fine as a document.
- The root also declares the `auto-timestamps` option, so every memory node
  gets a real `createdAt`/`updatedAt` automatically — what makes `meshfox
  node find --since 7d` ("what changed recently") actually work.

## The four memory types

### `user`
Facts about who you're working with: role, expertise, responsibilities,
preferences. Tailor how you explain things and what you assume they
already know.

**Save when:** you learn a detail about their role or background that
would change how you explain or approach something.

### `feedback`
Guidance on *how to work* — corrections and confirmed approaches alike.
Only saving corrections makes you cautious but not consistent; also save
when a non-obvious choice is explicitly confirmed as right.

**Save when:** the user corrects your approach ("no, don't do X") *or*
confirms an unusual one worked ("yes, exactly", accepting something
without pushback).

**Body structure:** the rule itself, then:
```
**Why:** <the reason given — a past incident, a stated preference>
**How to apply:** <when this kicks in, so you can judge edge cases>
```

### `project`
Who is doing what, why, or by when — context not derivable from the code
or git history. Decays fast, so lead with the fact and convert relative
dates ("Thursday") to absolute ones before writing.

**Save when:** you learn about an ongoing initiative, deadline, or the
motivation behind a piece of work.

**Body structure:** same `**Why:**` / `**How to apply:**` shape as
`feedback` above.

### `reference`
A pointer to where real information lives in an external system (issue
tracker, dashboard, Slack channel) — not the information itself.

**Save when:** you learn where something is tracked or documented outside
this repo.

## What NOT to store here

Same reasoning as any memory system: don't write down what's cheaper to
re-derive.

- Code patterns, conventions, file paths — read the current code instead.
- Git history / who-changed-what — `git log`/`git blame` are authoritative.
- Anything already in this `CLAUDE.md` or other project docs.
- In-progress task state — that belongs in a plan or a todo list, not here.

If asked to save something and it turns out to just be "what happened,"
without a *why* worth keeping, that's a signal it doesn't belong here.

## Reading memory

Before starting non-trivial work, or when the user references past
context, check `MEMORY.canvas.md` rather than assuming:

```bash
# node find/add/body/... take --canvas explicitly -- they don't accept
# a bare trailing path the way validate/check/list/view/tui do above.
meshfox node find --canvas MEMORY.canvas.md --text "<keyword>"     # full-text search
meshfox node find --canvas MEMORY.canvas.md .feedback              # everything tagged feedback
meshfox node find --canvas MEMORY.canvas.md .project --since 7d    # recent project context
meshfox tui MEMORY.canvas.md                                       # browse interactively
```

A memory is a claim about the state of things *when it was written*. If it
names a specific file, function, or flag and you're about to act on it
(not just recalling history), verify it still exists before relying on it.

## Writing memory

1. **Search first** — `meshfox node find --canvas MEMORY.canvas.md --text
   "<topic>"` — and update an existing node instead of creating a
   near-duplicate: pipe the new body to `meshfox node body --canvas
   MEMORY.canvas.md <id>` (stdin, no `--file` flag needed), or append
   instead of replacing with `node append` the same way.
2. **Add a new node** under the root, tagged with exactly one of the four
   types above:
   ```bash
   echo "<the memory, one paragraph>" \
     | meshfox node add --canvas MEMORY.canvas.md root "<short title>" \
         --tags "<user|feedback|project|reference>" --body-file -
   ```
   (`node add`'s stdin needs the explicit `--body-file -`, unlike `node
   body`/`node append` below — pass a real path instead of `-` to read
   from a file). Prints the new node's id; follow up with `meshfox node
   body --canvas MEMORY.canvas.md <new-id>` if the body needs the
   `**Why:**`/`**How to apply:**` structure below rather than one plain
   paragraph.
3. **Never hand-edit structure** — adding/moving/retagging a node, same as
   any other `.canvas.md` file (see `meshfox --agent-help`). Hand-editing
   prose *inside* an existing node's body is fine.
4. **Always finish with**:
   ```bash
   meshfox validate MEMORY.canvas.md && meshfox check MEMORY.canvas.md
   ```

If the user explicitly says to forget something, find the node (`node
find --canvas MEMORY.canvas.md --text ...`) and delete it (`meshfox node
rm --canvas MEMORY.canvas.md <id>`) rather than leaving a stale entry.

## MCP, if configured

If this project's `.mcp.json` starts `meshfox mcp`, prefer its `node_*`
tools (`node_find`, `node_add`, `node_body`, `node_meta`, `node_rm`, ...)
over shelling out to the CLI above — same operations, structured
JSON instead of text to re-parse. `canvas_open` first; every other tool
takes the `canvas_id` it returns.

```json
{
  "mcpServers": {
    "meshfox": { "command": "meshfox", "args": ["mcp"] }
  }
}
```

## First-time setup

If `MEMORY.canvas.md` doesn't exist yet in this repo, create it once:

```bash
meshfox create MEMORY.canvas.md
```

Then hand-edit just its root — the one bootstrap edit that's fine to do
by hand, since there's no other content yet to risk corrupting — to pin a
stable `id="root"` and declare the constraint + timestamp option:

````markdown
# Project Memory
<!-- meshfox:node id="root" -->

<!-- meshfox:option name="auto-timestamps" -->

This canvas is this project's second brain — see CLAUDE.md for how to
read and write it.

```starlark constraint
for n in self.descendants():
    if "feedback" in n.tags or "project" in n.tags:
        if "**Why:**" not in n.text:
            fail(n.id + " (" + ",".join(n.tags) + "): missing a '**Why:**' line")
```
````

Confirm it's well-formed and the constraint actually runs:

```bash
meshfox validate MEMORY.canvas.md
meshfox check MEMORY.canvas.md
```

Decide with the user whether `MEMORY.canvas.md` should be committed (a
durable, shared team memory) or gitignored (private scratch space, same
as this project's own `TODO.canvas.md` convention if it has one) — and
mention this file in the project's real `CLAUDE.md` if this template
replaced a pre-existing one, so the two don't drift apart.
