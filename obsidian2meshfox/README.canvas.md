<!-- meshfox:canvas -->
# obsidian2meshfox

<!-- meshfox:comment -->
> This is a [meshfox](https://meshfox.orofarne.net/) document — open it
> with `meshfox view` (or `meshfox tui`) for the interactive canvas.
> This note is only visible here, in a plain Markdown viewer.
<!-- /meshfox:comment -->

Converts an Obsidian [JSON Canvas](https://jsoncanvas.org/) file (`*.canvas`)
into a meshfox canvas (`*.canvas.md`). This canvas is the whole tool: the
Python environment, the converter script, its tests and an optional
AI-agent clean-up step all live in the nodes below. Nothing to install —
run **Convert** and pick the input and output files.

<!-- meshfox:var name="INPUT" type="file" ext="canvas" prompt="Obsidian canvas to convert (*.canvas)" -->
<!-- meshfox:var name="OUTPUT" type="file" mode="save" ext="md" prompt="Where to write the meshfox canvas (*.canvas.md)" -->
<!-- meshfox:var name="VAULT_ROOT" prompt="Obsidian vault root, for resolving attachments (empty = the input's own directory)" default="" -->
<!-- meshfox:var name="NO_PREVIEW" type="bool" prompt="Skip preview cards on link nodes?" default="false" -->
<!-- meshfox:var name="USE_AGENT" type="bool" prompt="After converting, let an AI agent tidy the result?" default="false" -->
<!-- meshfox:var name="PYTHON" from="env/setup" -->

## Usage
<!-- meshfox:node id="usage" color="4" -->

Open this file with `meshfox view README.canvas.md` (or `meshfox tui`) and
run the **Convert** node — you are asked for `INPUT` and `OUTPUT` (file
pickers) and whether to run the optional agent step. Or, non-interactively:

```console
meshfox README.canvas.md run main \
  --set INPUT=~/Vault/Map.canvas --set OUTPUT=~/Vault/Map.canvas.md \
  --set USE_AGENT=false
```

| Variable | Type | Meaning |
|---|---|---|
| `INPUT` | file (open) | the `*.canvas` to convert |
| `OUTPUT` | file (save) | the `*.canvas.md` to write; attachments referenced by `file` nodes are copied next to it |
| `VAULT_ROOT` | string, optional | Obsidian stores attachment paths relative to the **vault root**; set it when `INPUT` isn't in the vault root. Empty = the input's directory |
| `NO_PREVIEW` | bool | don't set `preview="true"` on link nodes |
| `USE_AGENT` | bool | after converting, let an AI agent tidy the result (see below) |

The converter also works as a plain CLI — meshfox writes it to a hidden
`.meshfox-tangle-README.canvas.md__convert.py` next to this file; run it with
`--help`. A whole vault can be converted that way (`DIR --out OUT`), which the
file variables here deliberately don't cover.

## Python environment
<!-- meshfox:node id="env" -->

The converter only needs the standard library, so the only real requirement
is the Python version. The block is a `pyproject.toml`: `@python_venv`
installs it into an isolated venv (under `.meshfox/`), and pip refuses to do
so if the interpreter is older than `requires-python` — a clear
`requires a different Python` error instead of a puzzling traceback later.
The venv's interpreter is published as `$PYTHON`, which the other blocks run
under. Third-party packages, if the script ever needs any, go into
`dependencies`.

```toml name="setup" interpreter="@python_venv"
[project]
name = "obsidian2meshfox-env"
version = "0.0.0"
requires-python = ">=3.10"
dependencies = []
```

## Convert
<!-- meshfox:node id="main" color="4" -->

The entry point. It runs the converter, then — only when `USE_AGENT` is true —
the optional agent step. The condition lives on the dependency edge
(`fix/fix?USE_AGENT`), so with it off the agent step is not run, not asked
about, and not part of this block's freshness.

```bash name="main" env="OUTPUT" deps="convert/convert,fix/fix?USE_AGENT"
echo "done: $OUTPUT"
```

## Converter script
<!-- meshfox:node id="convert" -->

The converter itself. `tangle` writes it to a stable hidden file instead of
a throwaway temp file, so the tests below (and your shell) can import it;
`INPUT`, `OUTPUT`, `VAULT_ROOT` and `NO_PREVIEW` arrive as environment
variables and are read as defaults for the matching CLI options.

```python name="convert" interpreter="$PYTHON -u" tangle env="INPUT,OUTPUT,VAULT_ROOT,NO_PREVIEW"
#!/usr/bin/env python3
"""Convert Obsidian JSON Canvas files (*.canvas) into meshfox canvases
(*.canvas.md), preserving node content and connectivity.

Obsidian canvases are freeform graphs (arbitrary x/y layout, arbitrary
edges). meshfox documents are trees: heading nesting *is* the node tree,
with any edges that don't fit the tree declared explicitly as
`meshfox:edge` comments. Converting one into the other therefore requires
picking a spanning tree:

  * Each weakly-connected component of the canvas becomes one top-level
    (H2) section, rooted at whichever node in that component has the
    highest degree (in the specific sense of "most directly-connected
    neighbours" -- the natural hub in a hand-built mind map).
  * From that hub, a BFS spanning tree assigns every other node in the
    component a structural parent.
  * Edges that aren't part of the spanning tree are preserved as
    `<!-- meshfox:edge from="..." -->` comments attached to their target
    node, so no connection from the original canvas is lost.
  * Node bodies, in the emitted document, are written out via a
    depth-first *pre-order* walk of that tree -- each node is immediately
    followed by its whole subtree -- because that's what markdown heading
    nesting actually encodes (a heading's parent is the nearest preceding
    heading of a shallower level). Emitting in breadth-first order would
    silently scramble the nesting for anything below depth 2.
  * meshfox only nests headings up to H6; deeper nodes stay pinned at H6
    and declare their true parent explicitly via `parent="..."` instead,
    per the spec.

Node titles are synthesized from content, since Obsidian canvas nodes
don't have a separate title field: the first line of text for `text`
nodes, host+path for `link` nodes, the filename for `file` nodes, and the
group's own label for `group` nodes.

Coordinates (x/y/w/h) from the source canvas are intentionally *not*
carried over -- meshfox lays its own nodes out from the tree structure,
and stale freeform coordinates from a fundamentally different layout
model are more misleading than useful. A node's `color` *is* carried
over (as meshfox's own `color=`), since it's a plain visual tag with no
positional meaning of its own.

Obsidian has no explicit "this node is in that group" edge -- group
membership is purely spatial (whichever nodes' boxes fall inside the
group's own box). This script reconstructs that relationship once, up
front, and folds it into the same adjacency graph edges already populate,
so a group and its members land in one component together and the group
naturally becomes their structural parent -- without ever fabricating a
`meshfox:edge` for a spatial relationship that was never a real edge in
the source.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

CANVAS_MARKER = "<!-- meshfox:canvas -->"
# The same hidden preamble `meshfox create` writes: invisible in meshfox,
# explains the file to someone reading it in a plain Markdown viewer.
PREAMBLE = [
    "<!-- meshfox:comment -->",
    "> This is a [meshfox](https://meshfox.orofarne.net/) document \u2014 open it",
    "> with `meshfox view` (or `meshfox tui`) for the interactive canvas.",
    "> This note is only visible here, in a plain Markdown viewer.",
    "<!-- /meshfox:comment -->",
]
ID_RE = re.compile(r"^[a-z0-9-]+$")
TRUE_WORDS = {"1", "true", "yes", "on"}


def clean_title(s: str, maxlen: int = 70) -> str:
    s = s.strip()
    s = re.sub(r"^#+\s*", "", s)
    s = s.split("\n", 1)[0].strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return "Untitled"
    if len(s) > maxlen:
        s = s[: maxlen - 1].rstrip() + "…"
    return s


def title_for_link(url: str) -> str:
    p = urlparse(url)
    label = p.netloc
    if p.path and p.path != "/":
        label += p.path.rstrip("/")
    if p.fragment:
        label += "#" + p.fragment
    return clean_title(label or url, 70)


def title_for_file(path: str) -> str:
    stem = Path(path).stem
    return clean_title(stem, 70)


def esc_attr(s: str) -> str:
    return s.replace('"', "&quot;")


def make_id_map(ids: list[str]) -> dict[str, str]:
    """meshfox ids are lowercase `a-z0-9-`; Obsidian's are usually 16 hex
    chars (already fine) but may be anything. Map each source id to a valid,
    unique meshfox id, leaving already-valid ones untouched."""
    taken = {i for i in ids if ID_RE.match(i)}
    out: dict[str, str] = {}
    for i in ids:
        if ID_RE.match(i):
            out[i] = i
            continue
        base = re.sub(r"[^a-z0-9]+", "-", i.lower()).strip("-") or "node"
        cand, k = base, 2
        while cand in taken:
            cand, k = f"{base}-{k}", k + 1
        taken.add(cand)
        out[i] = cand
    return out


FENCE_RE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})(.*)$")
MARKER_RE = re.compile(r"^(\s*)<!--(\s*/?meshfox:)")


def sanitize_body(text: str) -> str:
    """Make foreign Markdown inert inside a meshfox node.

    * A line that looks like a meshfox marker (`<!-- meshfox:node ... -->`)
      would be parsed as structure -- a note could forge nodes, edges or
      variables -- so its `<!--` is HTML-escaped.
    * A code fence is *runnable* in meshfox when it is `bash`/`sh`, or when
      its info string carries `interpreter=`/`name=`... A snippet someone
      pasted into an Obsidian note must not become a run button, so only the
      bare language word is kept and `bash`/`sh` become `shell`.
    """
    out: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                info = m.group(3).strip()
                lang = info.split(None, 1)[0] if info else ""
                if "=" in lang or lang.startswith("{"):
                    lang = ""
                if lang.lower() in ("bash", "sh"):
                    lang = "shell"
                fence = (m.group(2)[0], len(m.group(2)))
                line = m.group(1) + m.group(2) + lang
            else:
                line = MARKER_RE.sub(r"\1&lt;!--\2", line)
        elif m and m.group(2)[0] == fence[0] and len(m.group(2)) >= fence[1] and not m.group(3).strip():
            fence = None
        out.append(line)
    return "\n".join(out)


def assign_attachment_names(nodes: dict, taken: set[str]) -> dict[str, str]:
    """Attachments are copied next to the output under their plain filename,
    so `a/x.md` and `b/x.md` would overwrite each other. Give each distinct
    source path its own name (`x.md`, `x-2.md`, ...)."""
    names: dict[str, str] = {}
    used = set(taken)
    for n in nodes.values():
        if n.get("type") != "file" or n["file"] in names:
            continue
        p = Path(n["file"])
        cand, k = p.name, 2
        while cand in used:
            cand, k = f"{p.stem}-{k}{p.suffix}", k + 1
        used.add(cand)
        names[n["file"]] = cand
    return names


def rect_contains(outer: dict, inner: dict, eps: float = 0.5) -> bool:
    """True if `inner`'s box sits fully inside `outer`'s, within a small
    tolerance for float rounding in hand-dragged Obsidian layouts."""
    try:
        return (
            inner["x"] >= outer["x"] - eps
            and inner["y"] >= outer["y"] - eps
            and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + eps
            and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + eps
        )
    except (KeyError, TypeError):
        return False


def find_group_containment(nodes: dict) -> dict[str, str]:
    """Obsidian determines group membership purely by bounding-box overlap
    -- there's no membership edge in the source data. Map each node (a
    group included, for group-in-group nesting) to the smallest group
    that fully contains it, or omit it if none does."""
    groups = [n for n in nodes.values() if n.get("type") == "group"]
    contained_by: dict[str, str] = {}
    for n in nodes.values():
        nid = n["id"]
        own_area = n.get("width", 0) * n.get("height", 0)
        candidates = []
        for g in groups:
            if g["id"] == nid:
                continue
            area = g.get("width", 0) * g.get("height", 0)
            if n.get("type") == "group" and area <= own_area:
                continue
            if rect_contains(g, n):
                candidates.append((area, g["id"]))
        if candidates:
            candidates.sort()
            contained_by[nid] = candidates[0][1]
    return contained_by


def build_component_tree(node_ids, adj, sort_key=None):
    """BFS spanning tree over one weakly-connected component, rooted at
    the highest-degree node. Returns (root_id, parent_map, children_map,
    tree_edges) where tree_edges is the set of frozenset({a, b}) edges
    used by the tree (everything else is an "extra" edge)."""
    node_ids = list(node_ids)
    index = {n: i for i, n in enumerate(node_ids)}
    degree = {nid: len(adj[nid]) for nid in node_ids}
    root = min(node_ids, key=lambda n: (-degree[n], index[n]))

    visited = {root}
    parent = {root: None}
    children: dict[str, list[str]] = defaultdict(list)
    tree_edges = set()
    q = deque([root])
    while q:
        cur = q.popleft()
        neighbours = adj[cur] if sort_key is None else sorted(adj[cur], key=sort_key)
        for nxt in neighbours:
            if nxt not in visited:
                visited.add(nxt)
                parent[nxt] = cur
                children[cur].append(nxt)
                tree_edges.add(frozenset((cur, nxt)))
                q.append(nxt)

    return root, parent, children, tree_edges


def convert_canvas(
    src_path: Path,
    dst_path: Path,
    *,
    vault_root: Path,
    title: str | None = None,
    add_preview: bool = True,
) -> None:
    data = json.loads(src_path.read_text(encoding="utf-8"))

    raw_nodes = data.get("nodes", [])
    id_map = make_id_map([n["id"] for n in raw_nodes])
    nodes = {}
    for n in raw_nodes:
        n = dict(n, id=id_map[n["id"]])
        nodes[n["id"]] = n
    edges = [
        dict(e, fromNode=id_map.get(e["fromNode"], e["fromNode"]),
             toNode=id_map.get(e["toNode"], e["toNode"]))
        for e in data.get("edges", [])
        if e.get("fromNode") in id_map and e.get("toNode") in id_map
    ]

    edge_lookup: dict[frozenset, dict] = {}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        a, b = e["fromNode"], e["toNode"]
        adj[a].append(b)
        adj[b].append(a)
        edge_lookup.setdefault(frozenset((a, b)), e)

    for member_id, group_id in find_group_containment(nodes).items():
        adj[member_id].append(group_id)
        adj[group_id].append(member_id)

    all_ids = list(nodes.keys())
    seen: set[str] = set()
    components: list[list[str]] = []
    for nid in all_ids:
        if nid in seen:
            continue
        comp = []
        q = deque([nid])
        seen.add(nid)
        while q:
            cur = q.popleft()
            comp.append(cur)
            for other in adj[cur]:
                if other not in seen:
                    seen.add(other)
                    q.append(other)
        components.append(comp)

    index = {n: i for i, n in enumerate(all_ids)}
    components.sort(key=lambda comp: min(index[n] for n in comp))

    # Siblings come out in reading order (top to bottom, then left to right),
    # not in whatever order the edges happen to be listed in the file.
    def reading_order(nid: str):
        n = nodes[nid]
        return (n.get("y", 0), n.get("x", 0), index[nid])

    forest = []
    all_tree_edges: set[frozenset] = set()
    structural_parent: dict[str, str] = {}
    for comp in components:
        root, parent, children, tree_edges = build_component_tree(comp, adj, reading_order)
        forest.append((root, parent, children))
        all_tree_edges |= tree_edges
        for child, p in parent.items():
            if p is not None:
                structural_parent[child] = p

    extra_by_target: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        a, b = e["fromNode"], e["toNode"]
        # Only the one edge that realised a tree link is structural. A second
        # edge between the same pair (e.g. the reverse direction), or a
        # self-loop, is an extra edge and must keep its label and style.
        is_structural = (
            frozenset((a, b)) in all_tree_edges
            and edge_lookup.get(frozenset((a, b))) is e
        )
        if not is_structural:
            extra_by_target[b].append(
                {
                    "from": a,
                    "arrow_start": e.get("fromEnd") == "arrow",
                    "arrow_end_none": e.get("toEnd") == "none",
                    "color": e.get("color"),
                    "label": e.get("label"),
                }
            )

    def node_title(nid: str) -> str:
        n = nodes[nid]
        t = n.get("type")
        if t == "text":
            return clean_title(n.get("text", ""))
        if t == "link":
            return title_for_link(n.get("url", ""))
        if t == "file":
            return title_for_file(n.get("file", ""))
        if t == "group":
            return clean_title(n.get("label", ""))
        return "Untitled"

    def node_body(nid: str) -> str:
        n = nodes[nid]
        t = n.get("type")
        if t == "text":
            text = n.get("text", "").strip()
            body_lines = text.split("\n")
            if body_lines and re.match(r"^#+\s+\S", body_lines[0]):
                # The first line became this node's synthesized heading;
                # drop it here so it isn't duplicated as the first line
                # of the body too.
                rest = body_lines[1:]
                while rest and rest[0].strip() == "":
                    rest = rest[1:]
                text = "\n".join(rest)
            return sanitize_body(text)
        if t == "link":
            url = n.get("url", "")
            return f"[{title_for_link(url)}]({url})"
        if t == "file":
            path = n.get("file", "")
            fname = file_names[path]
            subpath = n.get("subpath") or ""
            if subpath:
                fname += subpath if subpath.startswith("#") else f"#{subpath}"
            return f"[{title_for_file(path)}]({fname})"
        return ""

    file_names = assign_attachment_names(nodes, {dst_path.name})

    lines: list[str] = [CANVAS_MARKER]
    h1_title = title if title is not None else clean_title(src_path.stem)
    lines.append(f"# {h1_title}")
    lines.append("")
    lines.extend(PREAMBLE)
    lines.append("")
    try:
        rel = src_path.relative_to(vault_root)
    except ValueError:
        rel = src_path.name
    lines.append(f"Imported from the Obsidian canvas `{rel}`.")
    lines.append("")

    def emit_node(nid: str, depth: int, parent_override: str | None) -> None:
        n = nodes[nid]
        t = n.get("type", "text")
        level = min(depth, 6)
        lines.append("#" * level + " " + node_title(nid))

        attrs = [f'id="{esc_attr(nid)}"']
        if t != "text":
            attrs.append(f'type="{t}"')
        color = n.get("color")
        if color:
            attrs.append(f'color="{esc_attr(color)}"')
        if t == "link" and add_preview:
            attrs.append('preview="true"')
        true_parent = structural_parent.get(nid)
        if true_parent:
            src_edge = edge_lookup.get(frozenset((true_parent, nid)))
            edge_label = src_edge.get("label") if src_edge else None
            if edge_label:
                attrs.append(f'edgeLabel="{esc_attr(edge_label)}"')
        if parent_override:
            attrs.append(f'parent="{esc_attr(parent_override)}"')
        lines.append("<!-- meshfox:node " + " ".join(attrs) + " -->")

        for extra in extra_by_target.get(nid, []):
            eattrs = [f'from="{esc_attr(extra["from"])}"']
            if extra["label"]:
                eattrs.append(f'label="{esc_attr(extra["label"])}"')
            if extra["color"]:
                eattrs.append(f'color="{esc_attr(extra["color"])}"')
            if extra["arrow_start"]:
                eattrs.append('arrowStart="arrow"')
            if extra["arrow_end_none"]:
                eattrs.append('arrowEnd="none"')
            lines.append("<!-- meshfox:edge " + " ".join(eattrs) + " -->")

        lines.append("")
        body = node_body(nid)
        if body:
            lines.extend(body.split("\n"))
            lines.append("")

    def emit_subtree(nid: str, depth: int, true_parent: str | None, children) -> None:
        parent_override = true_parent if depth > 6 else None
        emit_node(nid, depth, parent_override)
        for child in children.get(nid, []):
            emit_subtree(child, depth + 1, nid, children)

    for root, parent, children in forest:
        emit_subtree(root, 2, None, children)

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    root_resolved = vault_root.resolve()
    for path, name in file_names.items():
        src_file = vault_root / path
        dst_file = dst_path.parent / name
        try:
            inside = src_file.resolve().is_relative_to(root_resolved)
        except OSError:
            inside = False
        if not inside:
            print(f"warning: {src_path}: not copying {path}: outside the vault root", file=sys.stderr)
        elif not src_file.is_file():
            print(f"warning: {src_path}: missing referenced file {src_file}", file=sys.stderr)
        elif src_file.resolve() != dst_file.resolve():
            shutil.copy2(src_file, dst_file)


def find_canvases(inputs: list[Path]) -> list[Path]:
    found: list[Path] = []
    for p in inputs:
        if p.is_dir():
            found.extend(sorted(p.rglob("*.canvas")))
        elif p.is_file():
            found.append(p)
        else:
            print(f"warning: no such file or directory: {p}", file=sys.stderr)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="obsidian2meshfox",
        description=(
            "Convert Obsidian JSON Canvas files into meshfox canvases "
            "(.canvas.md). Options may also come from the environment "
            "(INPUT, OUTPUT, VAULT_ROOT, NO_PREVIEW) -- that's how the "
            "meshfox canvas this script lives in calls it."
        ),
    )
    ap.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help=(
            "One or more *.canvas files, or directories to search "
            "recursively. Default: $INPUT."
        ),
    )
    ap.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help=(
            "Exact output file. Only valid with a single input file. "
            "Default: $OUTPUT."
        ),
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output directory. The relative path of each source file (from "
            "--vault-root, or from the common input directory if omitted) "
            "is mirrored underneath it. Default: write each "
            "<name>.canvas.md next to its source *.canvas file."
        ),
    )
    ap.add_argument(
        "--vault-root",
        type=Path,
        default=None,
        help=(
            "Root the Obsidian vault's *.canvas 'file' node paths are "
            "relative to (Obsidian stores attachment paths relative to the "
            "vault root, not to the canvas file). Default: $VAULT_ROOT, "
            "else the input directory, or each file's own directory in "
            "single-file mode."
        ),
    )
    ap.add_argument(
        "--no-preview",
        action="store_true",
        help='Do not set preview="true" on link nodes. Also on if $NO_PREVIEW is true.',
    )
    args = ap.parse_args(argv)

    if not args.inputs and os.environ.get("INPUT"):
        args.inputs = [Path(os.environ["INPUT"]).expanduser()]
    if args.output is None and os.environ.get("OUTPUT"):
        args.output = Path(os.environ["OUTPUT"]).expanduser()
    if args.vault_root is None and os.environ.get("VAULT_ROOT"):
        args.vault_root = Path(os.environ["VAULT_ROOT"]).expanduser()
    if os.environ.get("NO_PREVIEW", "").strip().lower() in TRUE_WORDS:
        args.no_preview = True
    if not args.inputs:
        ap.error("no input: pass a path or set $INPUT")

    canvases = find_canvases(args.inputs)
    if not canvases:
        print("no *.canvas files found", file=sys.stderr)
        return 1
    if args.output is not None and (len(canvases) != 1 or args.out is not None):
        ap.error("--output needs exactly one input file and no --out")

    if args.vault_root is not None:
        vault_root = args.vault_root
    elif len(args.inputs) == 1 and args.inputs[0].is_dir():
        vault_root = args.inputs[0]
    elif len(args.inputs) == 1 and args.inputs[0].is_file():
        vault_root = args.inputs[0].parent
    else:
        vault_root = Path(os.path.commonpath([str(p) for p in canvases]))

    for src in canvases:
        if args.output is not None:
            dst = args.output
        elif args.out is not None:
            try:
                rel = src.relative_to(vault_root)
            except ValueError:
                rel = Path(src.name)
            dst = (args.out / rel).with_suffix(".canvas.md")
        else:
            dst = src.with_suffix(".canvas.md")

        convert_canvas(
            src,
            dst,
            vault_root=vault_root,
            add_preview=not args.no_preview,
        )
        print(f"{src} -> {dst}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Agent step (optional)
<!-- meshfox:node id="fix" color="6" tags="optional,agent" -->

The tree-picking heuristic (see below) sometimes chooses a root or section
split you wouldn't have, and synthesized titles can be clumsy. This block
hands the converted file to your coding agent (`interpreters.agent.provider`
in `.meshfox/config.toml`: `claude` or `codex`) with a precise brief.
`INPUT` and `OUTPUT` are interpolated into the prompt — the agent reads the
source, edits the output, and re-validates it.

It is **optional**: **Convert** runs it only when `USE_AGENT` is true. Run
it directly to tidy a file you already converted. Add the `tty` flag to the
fence to talk to the agent interactively instead of one-shot `-p`.

```text name="fix" interpreter="@agent" env="INPUT,OUTPUT"
A meshfox canvas was just generated automatically from an Obsidian canvas.
Please tidy it up.

  Source Obsidian canvas (read-only): $INPUT
  Generated meshfox canvas (edit this one): $OUTPUT

Run `meshfox --agent-help` first and follow it: use `meshfox node ...`
commands for structural edits rather than rewriting the file by hand.

What to do:
1. Read both files. The converter picked each section's root as the node with
   the most connections and titled every node from the first line of its
   text, so roots, nesting and titles may look arbitrary.
2. Where the structure is clearly wrong or awkward, fix it: rename unclear
   titles (`meshfox node rename`), move misplaced nodes (`meshfox node mv`),
   promote the natural hub of each cluster. Group related top-level sections
   if that helps readability.
3. Never delete a node or an edge, never change a node's body text, and keep
   every node id as it is: nothing from the source canvas may be lost.
4. Finish with `meshfox validate $OUTPUT` and fix anything it reports.
5. Reply with a short list of what you changed and why.
```

## Design note: how the agent step is optional
<!-- meshfox:node id="optional-agent" -->

A conditional dependency: `deps="convert/convert,fix/fix?USE_AGENT"`. The
`?USE_AGENT` suffix keeps the edge only while the `bool` variable is true;
`?!USE_AGENT` would invert it, and `?PROVIDER=claude` compares against a
value. Because the condition belongs to the edge, running **Agent step**
directly still works, and the built-in `@agent` interpreter keeps provider
selection, `$VAR` interpolation and `tty` handling — no `bash` wrapper
calling `claude -p` by hand. Needs a meshfox build that supports `?` in
`deps=`.

## How the conversion works
<!-- meshfox:node id="how" -->

Obsidian canvases are freeform graphs — arbitrary x/y layout, arbitrary
edges, no inherent hierarchy. meshfox documents are trees: heading nesting
*is* the node tree, and anything that doesn't fit has to be declared
explicitly as a `meshfox:edge` comment. So converting means picking a
spanning tree:

- Every node and edge of the source is preserved — nothing is dropped.
  Node **content** carries over; node **titles** are synthesized (there is no
  title field in Obsidian) from the first line of text, the link's host+path,
  the file's name, or a group's own label. Exactly one edge per tree link is
  structural; a second edge between the same pair (say, the reverse
  direction) and self-loops become ordinary `meshfox:edge`s with their own
  label and colour.
- A node's `color`, and an edge's `label`/`color`/arrowheads, carry over
  onto meshfox's own attributes. The structural edge keeps only its
  **label** (as `edgeLabel=`); an edge that loses to a shorter path keeps its
  full styling as an explicit `meshfox:edge`.
- Obsidian group membership is purely spatial. It is reconstructed once from
  the source coordinates and folded into the same connectivity graph, so a
  group and its members always end up in one component; a membership that
  loses the spanning-tree race is dropped rather than turned into a
  fabricated edge.
- Each weakly-connected component becomes one `##` section rooted at its
  node with the most direct connections; a breadth-first spanning tree from
  there assigns every other node a structural parent. Siblings are ordered
  top-to-bottom, then left-to-right, as on the source canvas. Edges that lose
  are kept as `meshfox:edge` comments.
- Headings only nest to `######`; deeper nodes stay at H6 and name their
  real parent with `parent="..."`.
- Obsidian ids that aren't valid meshfox ids (lowercase `a-z0-9-`) are
  slugged and kept unique; the usual 16-hex-char ids pass through unchanged.
- Attachments are copied next to the output; two files with the same name
  from different folders get distinct names (`x.md`, `x-2.md`), and a path
  that escapes the vault root is refused.
- **Foreign Markdown is made inert.** A line that looks like a meshfox marker
  is escaped, and a pasted code fence loses everything but its language word
  (`bash`/`sh` become `shell`) — otherwise a snippet in a note would turn
  into a run button, and a hostile canvas could forge nodes or run code.
- Obsidian's x/y/width/height **and edge attachment sides**
  (`fromSide`/`toSide`) are **not** carried over — they describe a manual
  layout that meshfox does not have, and meshfox routes edges itself.

Because the hub is picked by raw connection count, a few canvases get a root
you wouldn't have chosen by hand. The result is a normal canvas, easy to fix
by hand — or with the optional agent step above.

### Known limitations
<!-- meshfox:node id="limitations" color="3" -->

- A structural edge always points parent → child. If the source edge pointed
  child → parent (or had no arrowhead, or arrowheads on both ends), the
  direction and arrowheads of that one edge are lost; only its label
  survives. Edges that become `meshfox:edge`s keep direction and arrowheads.
- Obsidian-only Markdown (`[[wikilinks]]`, `![[embeds]]`, `> [!callouts]`,
  `%%comments%%`) is copied verbatim and shows as plain text.
- Text nodes' titles come from their first line, so they can be clumsy; the
  optional agent step exists for that.

## Tests
<!-- meshfox:node id="tests" -->

The suite rebuilds the node tree from the emitted Markdown the way meshfox's
parser would (heading nesting + `parent=` + `meshfox:edge`) and compares it
with the source canvas's edges — a regression test for a real bug where
emitting nodes in breadth-first order silently scrambled nesting below depth
2. It also covers the marker/preamble, id slugging and the `INPUT`/`OUTPUT`
environment path. Runs **Convert**'s tangled script, so no extra setup.

```python name="tests" interpreter="$PYTHON -u" deps="convert/convert"
"""Regression tests for obsidian2meshfox.

The core risk in this converter isn't the JSON parsing -- it's getting the
markdown heading nesting right. Earlier versions emitted nodes in
breadth-first order, which silently scrambles the tree for anything below
depth 2 (a heading's *structural* parent in markdown is whichever heading
of a shallower level most recently preceded it in the document, not
whatever the generator "meant"). These tests reconstruct the tree from the
emitted markdown the same way meshfox's own parser would -- by walking
headings and `parent=` overrides -- and check it against the source
canvas's edges, rather than just eyeballing the output.
"""
from __future__ import annotations

import json
import re
import glob
import importlib.util
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# The converter is the tangled `convert` block of the canvas this test lives
# in: a hidden file next to the canvas, not an importable module.
_candidates = sorted(glob.glob(".meshfox-tangle-*__convert.py"))
if not _candidates:
    raise SystemExit("run the `convert` block once first (it writes the tangled script)")
_spec = importlib.util.spec_from_file_location("obsidian2meshfox", _candidates[0])
conv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conv)
convert_canvas = conv.convert_canvas

NODE_HEADING_RE = re.compile(r"^(#{1,6})\s")
NODE_COMMENT_RE = re.compile(r"<!-- meshfox:node (.+) -->$")
EDGE_COMMENT_RE = re.compile(r"<!-- meshfox:edge (.+) -->$")
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def reconstruct_edges(markdown: str) -> tuple[set[frozenset], int]:
    """Walk the emitted document and rebuild the set of (undirected) edges
    it encodes -- both structural (heading nesting / parent=) and extra
    (meshfox:edge) -- the same way a parser following the spec would."""
    stack: list[tuple[int, str]] = []
    edges: set[frozenset] = set()
    pending_level = None
    node_count = 0

    for line in markdown.split("\n"):
        m = NODE_HEADING_RE.match(line)
        if m:
            pending_level = len(m.group(1))
            continue
        m2 = NODE_COMMENT_RE.match(line)
        if m2:
            attrs = dict(ATTR_RE.findall(m2.group(1)))
            nid, level = attrs["id"], pending_level
            node_count += 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            struct_parent = attrs.get("parent") or (stack[-1][1] if stack else None)
            if struct_parent:
                edges.add(frozenset((struct_parent, nid)))
            stack.append((level, nid))
            pending_level = None
            continue
        m3 = EDGE_COMMENT_RE.match(line)
        if m3:
            attrs = dict(ATTR_RE.findall(m3.group(1)))
            to_id = stack[-1][1] if stack else None
            edges.add(frozenset((attrs["from"], to_id)))

    return edges, node_count


def make_canvas(nodes: list[dict], edges: list[tuple[str, str]]) -> dict:
    return {
        "nodes": nodes,
        "edges": [
            {"id": f"e{i}", "fromNode": a, "toNode": b} for i, (a, b) in enumerate(edges)
        ],
    }


class RoundTripTests(unittest.TestCase):
    def _convert(self, canvas: dict) -> tuple[str, dict]:
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Test.canvas"
            src.write_text(json.dumps(canvas), encoding="utf-8")
            dst = tmp / "Test.canvas.md"
            convert_canvas(src, dst, vault_root=tmp)
            return dst.read_text(encoding="utf-8"), canvas

    def test_deep_chain_and_branching_preserves_all_edges(self):
        # A hub with three branches: B carries a straight-line chain that
        # runs past heading level 6 (forcing parent= overrides on the
        # nodes that don't fit); C and D both also point at a shared node
        # F, which BFS can only give one structural parent to, forcing the
        # other incoming edge to become a non-tree meshfox:edge.
        nodes = [{"id": "a", "type": "text", "text": "Hub", "x": 0, "y": 0, "width": 1, "height": 1}]
        for bid, label in (("b", "Branch B"), ("c", "Branch C"), ("d", "Branch D")):
            nodes.append({"id": bid, "type": "text", "text": label, "x": 0, "y": 0, "width": 1, "height": 1})
        chain = [f"e{i}" for i in range(1, 6)]  # E1..E5
        for cid in chain:
            nodes.append({"id": cid, "type": "text", "text": f"Node {cid}", "x": 0, "y": 0, "width": 1, "height": 1})
        nodes.append({"id": "f", "type": "text", "text": "Shared", "x": 0, "y": 0, "width": 1, "height": 1})

        edges = [("a", "b"), ("a", "c"), ("a", "d"), ("b", "e1")]
        edges += [(chain[i], chain[i + 1]) for i in range(len(chain) - 1)]
        edges += [("c", "f"), ("d", "f")]

        canvas = make_canvas(nodes, edges)
        markdown, canvas = self._convert(canvas)

        expected = {frozenset(e) for e in edges}
        got, node_count = reconstruct_edges(markdown)
        self.assertEqual(node_count, len(nodes))
        self.assertEqual(got, expected)

        # F is reached from both B and D but BFS discovers it via C first
        # (C is dequeued before D), so C becomes F's structural parent and
        # D-F must survive as an explicit extra edge.
        self.assertIn('<!-- meshfox:edge from="d" -->', markdown)

        # The chain runs A(2) B(3) E1(4) E2(5) E3(6) E4(7) E5(8): E4 and E5
        # sit past H6, so both must carry an explicit parent= override and
        # stay pinned at heading level 6.
        self.assertRegex(markdown, r"###### Node e4\n<!-- meshfox:node id=\"e4\"[^>]*parent=\"e3\"")
        self.assertRegex(markdown, r"###### Node e5\n<!-- meshfox:node id=\"e5\"[^>]*parent=\"e4\"")

    def test_link_node_gets_preview_by_default(self):
        nodes = [{"id": "a", "type": "link", "url": "https://example.com/page", "x": 0, "y": 0, "width": 1, "height": 1}]
        markdown, _ = self._convert(make_canvas(nodes, []))
        self.assertIn('type="link" preview="true"', markdown)
        self.assertIn("[example.com/page](https://example.com/page)", markdown)

    def test_no_preview_flag_omits_attribute(self):
        nodes = [{"id": "a", "type": "link", "url": "https://example.com/page", "x": 0, "y": 0, "width": 1, "height": 1}]
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Test.canvas"
            src.write_text(json.dumps(make_canvas(nodes, [])), encoding="utf-8")
            dst = tmp / "Test.canvas.md"
            convert_canvas(src, dst, vault_root=tmp, add_preview=False)
            markdown = dst.read_text(encoding="utf-8")
        self.assertNotIn("preview=", markdown)

    def test_no_coordinates_in_output(self):
        nodes = [{"id": "a", "type": "text", "text": "Hub", "x": 123, "y": 456, "width": 250, "height": 60}]
        markdown, _ = self._convert(make_canvas(nodes, []))
        for attr in ('x="', 'y="', 'w="', 'h="'):
            self.assertNotIn(attr, markdown)

    def test_file_node_is_copied_next_to_output(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "attachments").mkdir()
            (tmp / "attachments" / "photo.png").write_bytes(b"fake-png")
            nodes = [
                {
                    "id": "a",
                    "type": "file",
                    "file": "attachments/photo.png",
                    "x": 0, "y": 0, "width": 1, "height": 1,
                }
            ]
            src = tmp / "Test.canvas"
            src.write_text(json.dumps(make_canvas(nodes, [])), encoding="utf-8")
            out_dir = tmp / "out"
            dst = out_dir / "Test.canvas.md"
            convert_canvas(src, dst, vault_root=tmp)
            self.assertTrue((out_dir / "photo.png").exists())
            self.assertIn("[photo](photo.png)", dst.read_text(encoding="utf-8"))

    def test_isolated_node_becomes_its_own_section(self):
        nodes = [
            {"id": "a", "type": "text", "text": "Hub", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "b", "type": "text", "text": "Orphan", "x": 0, "y": 0, "width": 1, "height": 1},
        ]
        markdown, _ = self._convert(make_canvas(nodes, []))
        self.assertIn("## Hub", markdown)
        self.assertIn("## Orphan", markdown)

    def test_node_color_is_carried_over(self):
        nodes = [{"id": "a", "type": "text", "text": "Hub", "color": "4", "x": 0, "y": 0, "width": 1, "height": 1}]
        markdown, _ = self._convert(make_canvas(nodes, []))
        self.assertIn('color="4"', markdown)

    def test_edge_label_color_and_arrow_end_carried_on_extra_edge(self):
        nodes = [
            {"id": "a", "type": "text", "text": "Hub", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "b", "type": "text", "text": "Other", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "c", "type": "text", "text": "Extra", "x": 0, "y": 0, "width": 1, "height": 1},
        ]
        canvas = make_canvas(nodes, [("a", "b"), ("a", "c")])
        # B -> C is an extra (non-tree) edge, since C is already reached via A.
        canvas["edges"].append(
            {
                "id": "e-extra",
                "fromNode": "b",
                "toNode": "c",
                "label": "see also",
                "color": "2",
                "toEnd": "none",
            }
        )
        markdown, _ = self._convert(canvas)
        self.assertIn(
            '<!-- meshfox:edge from="b" label="see also" color="2" arrowEnd="none" -->',
            markdown,
        )

    def test_structural_edge_label_becomes_edge_label_attribute(self):
        nodes = [
            {"id": "a", "type": "text", "text": "Hub", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "b", "type": "text", "text": "Child", "x": 0, "y": 0, "width": 1, "height": 1},
        ]
        canvas = make_canvas(nodes, [])
        canvas["edges"] = [{"id": "e0", "fromNode": "a", "toNode": "b", "label": "leads to"}]
        markdown, _ = self._convert(canvas)
        self.assertRegex(markdown, r'<!-- meshfox:node id="b"[^>]*edgeLabel="leads to"')

    def test_group_node_gets_label_as_title_and_nests_contained_members(self):
        nodes = [
            {"id": "g", "type": "group", "label": "My Group", "x": 0, "y": 0, "width": 200, "height": 200},
            {"id": "a", "type": "text", "text": "Inside", "x": 10, "y": 10, "width": 50, "height": 50},
        ]
        markdown, _ = self._convert(make_canvas(nodes, []))
        self.assertIn("## My Group", markdown)
        self.assertIn('type="group"', markdown)
        got, node_count = reconstruct_edges(markdown)
        self.assertEqual(node_count, 2)
        self.assertIn(frozenset(("g", "a")), got)
        # A group's own body must stay empty per the meshfox spec.
        self.assertNotIn("Inside\n\n### Inside", markdown)

    def test_file_node_subpath_becomes_link_fragment(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "note.md").write_text("hi", encoding="utf-8")
            nodes = [
                {
                    "id": "a",
                    "type": "file",
                    "file": "note.md",
                    "subpath": "#Some Heading",
                    "x": 0, "y": 0, "width": 1, "height": 1,
                }
            ]
            src = tmp / "Test.canvas"
            src.write_text(json.dumps(make_canvas(nodes, [])), encoding="utf-8")
            dst = tmp / "Test.canvas.md"
            convert_canvas(src, dst, vault_root=tmp)
            self.assertIn("[note](note.md#Some Heading)", dst.read_text(encoding="utf-8"))


class NewBehaviourTests(unittest.TestCase):
    """Checks for what the in-canvas version added on top of the original."""

    _convert = RoundTripTests._convert

    def test_output_starts_with_canvas_marker_and_preamble(self):
        markdown, _ = self._convert(make_canvas(
            [{"id": "a", "type": "text", "text": "Only", "x": 0, "y": 0, "width": 1, "height": 1}], []))
        self.assertEqual(markdown.split("\n", 1)[0], "<!-- meshfox:canvas -->")
        self.assertEqual(markdown.count("\n# "), 1 - markdown.startswith("# "))
        self.assertIn("<!-- meshfox:comment -->", markdown)

    def test_invalid_ids_are_slugged_and_stay_unique(self):
        nodes = [
            {"id": "Node_One", "type": "text", "text": "x", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "node one", "type": "text", "text": "y", "x": 0, "y": 0, "width": 1, "height": 1},
        ]
        markdown, _ = self._convert(make_canvas(nodes, [("Node_One", "node one")]))
        ids = re.findall(r'meshfox:node id="([^"]+)"', markdown)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(re.fullmatch(r"[a-z0-9-]+", i) for i in ids))
        got, _ = reconstruct_edges(markdown)
        self.assertEqual(len(got), 1)

    def test_env_and_output_flag(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "In.canvas"
            src.write_text(json.dumps(make_canvas(
                [{"id": "a", "type": "text", "text": "Hi", "x": 0, "y": 0, "width": 1, "height": 1}], [])))
            dst = tmp / "sub" / "Exact.canvas.md"
            os.environ.update(INPUT=str(src), OUTPUT=str(dst))
            try:
                self.assertEqual(conv.main([]), 0)
            finally:
                del os.environ["INPUT"], os.environ["OUTPUT"]
            self.assertTrue(dst.exists())


def _n(i, text="x", **kw):
    return {"id": i, "type": "text", "text": text, "x": 0, "y": 0, "width": 1, "height": 1, **kw}


class FidelityTests(unittest.TestCase):
    """Things an earlier version silently dropped or let through."""

    def _convert(self, canvas, files=None):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for rel, content in (files or {}).items():
                (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
                (tmp / rel).write_text(content)
            src = tmp / "T.canvas"
            src.write_text(json.dumps(canvas))
            dst = tmp / "out" / "T.canvas.md"
            convert_canvas(src, dst, vault_root=tmp)
            contents = {p.name: p.read_text(encoding="utf-8") for p in dst.parent.iterdir()}
            return dst.read_text(encoding="utf-8"), sorted(contents), contents

    def test_reverse_and_parallel_edges_keep_label_and_colour(self):
        canvas = make_canvas([_n("a"), _n("b")], [("a", "b"), ("b", "a")])
        canvas["edges"][0]["label"] = "forward"
        canvas["edges"][1].update(label="backward", color="2")
        md, _, _ = self._convert(canvas)
        self.assertIn('edgeLabel="forward"', md)
        self.assertIn('<!-- meshfox:edge from="b" label="backward" color="2" -->', md)

    def test_self_loop_survives(self):
        canvas = make_canvas([_n("a")], [("a", "a")])
        canvas["edges"][0]["label"] = "again"
        md, _, _ = self._convert(canvas)
        self.assertIn('<!-- meshfox:edge from="a" label="again" -->', md)

    def test_body_cannot_forge_meshfox_markers(self):
        md, _, _ = self._convert(make_canvas(
            [_n("a", 'Title\n\n## Fake\n<!-- meshfox:node id="evil" -->\nx')], []))
        self.assertIn('&lt;!-- meshfox:node id="evil" -->', md)
        self.assertEqual(re.findall(r'^<!-- meshfox:node', md, re.M), ["<!-- meshfox:node"])

    def test_pasted_code_fences_are_not_runnable(self):
        text = 'T\n\n```bash name="x" autorun\nrm -rf /\n```\n\n```python interpreter="python3"\nprint(1)\n```\n\n```\nplain\n```'
        md, _, _ = self._convert(make_canvas([_n("a", text)], []))
        self.assertNotRegex(md, r"```bash")
        self.assertNotIn("name=", md)
        self.assertNotIn("interpreter=", md)
        self.assertNotIn("autorun", md)
        self.assertIn("```shell\nrm -rf /", md)       # content untouched, just inert
        self.assertIn("```python\nprint(1)", md)

    def test_markers_inside_code_fence_are_left_alone(self):
        text = "T\n\n```text\n<!-- meshfox:node id=\"x\" -->\n```"
        md, _, _ = self._convert(make_canvas([_n("a", text)], []))
        self.assertIn('```text\n<!-- meshfox:node id="x" -->\n```', md)

    def test_same_named_attachments_do_not_overwrite_each_other(self):
        nodes = [
            {"id": "f1", "type": "file", "file": "a/same.md", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "f2", "type": "file", "file": "b/same.md", "x": 0, "y": 0, "width": 1, "height": 1},
        ]
        md, names, files = self._convert(make_canvas(nodes, [("f1", "f2")]),
                                     files={"a/same.md": "A", "b/same.md": "B"})
        self.assertIn("[same](same.md)", md)
        self.assertIn("[same](same-2.md)", md)
        self.assertEqual(files["same.md"], "A")
        self.assertEqual(files["same-2.md"], "B")

    def test_attachment_outside_vault_is_not_copied(self):
        node = {"id": "f", "type": "file", "file": "../secret.txt", "x": 0, "y": 0, "width": 1, "height": 1}
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "secret.txt").write_text("s")
            vault = tmp / "vault"
            vault.mkdir()
            src = vault / "T.canvas"
            src.write_text(json.dumps(make_canvas([node], [])))
            dst = tmp / "out" / "T.canvas.md"
            convert_canvas(src, dst, vault_root=vault)
            self.assertFalse((dst.parent / "secret.txt").exists())

    def test_siblings_follow_reading_order(self):
        nodes = [_n("hub", "Hub"), _n("right", "Right", x=500, y=0),
                 _n("low", "Low", x=0, y=500), _n("left", "Left", x=0, y=0)]
        md, _, _ = self._convert(make_canvas(nodes, [("hub", "right"), ("hub", "low"), ("hub", "left")]))
        self.assertEqual(re.findall(r'^### (\w+)', md, re.M), ["Left", "Right", "Low"])


if __name__ == "__main__":
    unittest.main()
```
