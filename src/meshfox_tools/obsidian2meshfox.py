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


def build_component_tree(node_ids, adj):
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
        for nxt in adj[cur]:
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

    nodes = {n["id"]: n for n in data.get("nodes", [])}
    edges = data.get("edges", [])

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

    forest = []
    all_tree_edges: set[frozenset] = set()
    structural_parent: dict[str, str] = {}
    for comp in components:
        root, parent, children, tree_edges = build_component_tree(comp, adj)
        forest.append((root, parent, children))
        all_tree_edges |= tree_edges
        for child, p in parent.items():
            if p is not None:
                structural_parent[child] = p

    extra_by_target: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        a, b = e["fromNode"], e["toNode"]
        if frozenset((a, b)) not in all_tree_edges:
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
            return text
        if t == "link":
            url = n.get("url", "")
            return f"[{title_for_link(url)}]({url})"
        if t == "file":
            path = n.get("file", "")
            fname = Path(path).name
            subpath = n.get("subpath") or ""
            if subpath:
                fname += subpath if subpath.startswith("#") else f"#{subpath}"
            return f"[{title_for_file(path)}]({fname})"
        return ""

    lines: list[str] = []
    h1_title = title if title is not None else clean_title(src_path.stem)
    lines.append(f"# {h1_title}")
    lines.append("")
    try:
        rel = src_path.relative_to(vault_root)
    except ValueError:
        rel = src_path.name
    lines.append(f"Импортировано из Obsidian canvas `{rel}`.")
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

    for n in nodes.values():
        if n.get("type") == "file":
            src_file = vault_root / n["file"]
            dst_file = dst_path.parent / Path(n["file"]).name
            if src_file.exists():
                if src_file.resolve() != dst_file.resolve():
                    shutil.copy2(src_file, dst_file)
            else:
                print(f"warning: {src_path}: missing referenced file {src_file}", file=sys.stderr)


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
        description="Convert Obsidian JSON Canvas files into meshfox canvases (.canvas.md).",
    )
    ap.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="One or more *.canvas files, or directories to search recursively.",
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
            "vault root, not to the canvas file). Default: the input "
            "directory, or each file's own directory in single-file mode."
        ),
    )
    ap.add_argument(
        "--no-preview",
        action="store_true",
        help='Do not set preview="true" on link nodes.',
    )
    args = ap.parse_args(argv)

    canvases = find_canvases(args.inputs)
    if not canvases:
        print("no *.canvas files found", file=sys.stderr)
        return 1

    if args.vault_root is not None:
        vault_root = args.vault_root
    elif len(args.inputs) == 1 and args.inputs[0].is_dir():
        vault_root = args.inputs[0]
    elif len(args.inputs) == 1 and args.inputs[0].is_file():
        vault_root = args.inputs[0].parent
    else:
        vault_root = Path(os.path.commonpath([str(p) for p in canvases]))

    in_root = vault_root

    for src in canvases:
        if args.out is not None:
            try:
                rel = src.relative_to(in_root)
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
