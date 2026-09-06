<!-- meshfox:canvas -->
# meshfox-tools

Small utilities around [meshfox](https://meshfox.orofarne.net/) canvases.

This document is itself a valid meshfox canvas — every `##`/`###` section
here is a node, nested under this root. Open it with `meshfox view
README.md` (or `meshfox tui README.md`) for the interactive version, or
just keep reading it as plain Markdown — nothing above changes.

## obsidian2meshfox
<!-- meshfox:node id="obsidian2meshfox" -->

Converts Obsidian [JSON Canvas](https://jsoncanvas.org/) files (`*.canvas`)
into meshfox canvases (`*.canvas.md`).

### Install
<!-- meshfox:node id="install" -->

```sh
cd meshfox-tools
python3 -m pip install -e .
```

Or run it straight from the checkout without installing:

```sh
python3 src/meshfox_tools/obsidian2meshfox.py --help
```

### Usage
<!-- meshfox:node id="usage" -->

```sh
# a single canvas, written next to the source as Foo.canvas.md
obsidian2meshfox path/to/Foo.canvas

# every *.canvas file under a vault, mirrored into ./out/
obsidian2meshfox ~/Documents/MyVault --out ./out

# don't add preview="true" to link nodes
obsidian2meshfox Foo.canvas --no-preview
```

By default, output is written next to each source file. With `--out`, the
input path's directory structure is mirrored underneath the given
directory instead.

Obsidian stores `file`-type node targets (attachments) as paths relative
to the **vault root**, not to the canvas file itself. If you're not
converting a whole vault (i.e. your input isn't the vault root), pass
`--vault-root` explicitly so attachment paths resolve correctly; without
it, single-file mode assumes the source file's own directory is the vault
root. Any attachments referenced by `file` nodes are copied next to the
generated `.canvas.md`, flattened to their plain filename — including a
`subpath` anchor (Obsidian's `#Heading`/`#^blockid` deep link into the
target note), carried over onto the emitted link.

#### CLI help
<!-- meshfox:node id="usage-help" -->

```bash name="usage-help" cache
python3 src/meshfox_tools/obsidian2meshfox.py --help
```
<!-- meshfox:output name="usage-help" hash="f308498d" -->
```text
exit code: 0 · 232ms

usage: obsidian2meshfox [-h] [--out OUT] [--vault-root VAULT_ROOT]
                        [--no-preview]
                        inputs [inputs ...]

Convert Obsidian JSON Canvas files into meshfox canvases (.canvas.md).

positional arguments:
  inputs                One or more *.canvas files, or directories to search
                        recursively.

options:
  -h, --help            show this help message and exit
  --out OUT             Output directory. The relative path of each source
                        file (from --vault-root, or from the common input
                        directory if omitted) is mirrored underneath it.
                        Default: write each <name>.canvas.md next to its
                        source *.canvas file.
  --vault-root VAULT_ROOT
                        Root the Obsidian vault's *.canvas 'file' node paths
                        are relative to (Obsidian stores attachment paths
                        relative to the vault root, not to the canvas file).
                        Default: the input directory, or each file's own
                        directory in single-file mode.
  --no-preview          Do not set preview="true" on link nodes.
```
<!-- /meshfox:output -->

### Why this isn't a lossless 1:1 translation
<!-- meshfox:node id="why-not-lossless" -->

Obsidian canvases are freeform graphs — arbitrary x/y layout, arbitrary
edges, no inherent hierarchy. meshfox documents are trees: heading
nesting *is* the node tree, and anything that doesn't fit that tree has
to be declared explicitly as a `meshfox:edge` comment. So converting one
into the other means picking a spanning tree, and this tool does it with
a heuristic:

- Every node and edge from the source canvas is preserved — nothing is
  dropped. Node **content** carries over exactly; node **titles** are
  synthesized (there's no separate title field in Obsidian canvas nodes)
  from the first line of text, the link's host+path, the file's name, or
  (for a `group` node) the group's own label.
- A node's `color` and an edge's `label`/`color`/arrowhead direction
  carry straight across onto meshfox's own `color=`/`meshfox:edge
  label=`/`color=`/`arrowStart=`/`arrowEnd=` attributes, since meshfox
  supports the same JSON-Canvas-style values natively. The one edge that
  becomes part of the structural tree instead of a `meshfox:edge` keeps
  only its **label**, as the child node's `edgeLabel=` — meshfox's
  structural (nesting) edges have no slot for color or arrow direction of
  their own, only text, so a styled edge that loses the spanning-tree
  race to a shorter path keeps its full styling (as an explicit
  `meshfox:edge`), while one that wins it keeps only the label.
- Obsidian groups have no explicit "contains" edge — membership is purely
  spatial (whichever nodes' boxes fall inside the group's own box). This
  tool reconstructs that relationship once, up front, from the source
  canvas's own coordinates, and folds it into the same connectivity graph
  real edges populate — a group and its members always end up in one
  weakly-connected component together, with the group typically (though,
  per the hub heuristic below, not always) becoming their structural
  parent.
- Each weakly-connected component of the graph becomes one top-level
  (`##`) section, rooted at whichever node in that component has the
  most direct connections — real edges and reconstructed group
  membership counted together — the natural hub in a hand-built mind map
  or a deliberately-grouped cluster.
- From that hub, a breadth-first spanning tree assigns every other node
  in the component a structural (heading-nesting) parent — i.e. the
  *shortest* path from the hub wins when a node is reachable more than
  one way. Edges that lose out to a shorter path are **not** discarded:
  they're kept as explicit `meshfox:edge` comments on the node they
  point to, so the full original connectivity is still recoverable from
  the file, just not all of it as document nesting. A reconstructed
  group-membership relationship that loses this race is simply dropped
  rather than turned into a fabricated `meshfox:edge` — it was never a
  real edge in the source, so nothing pretends otherwise in the output.
- meshfox only nests headings up to `######` (H6); components whose tree
  runs deeper than that keep the heading pinned at H6 and disambiguate
  the real parent via the `parent="..."` attribute, per the meshfox spec.
- Obsidian's freeform `x`/`y`/`width`/`height` coordinates are **not**
  carried over. They describe a layout model meshfox doesn't have; stale
  coordinates from a completely different canvas would be misleading
  rather than useful, and meshfox already lays out an untouched canvas
  from its own tree structure.

Because the hub is chosen by raw connection count, a small fraction of
canvases — ones where a node incidental to the "real" structure happens
to have unusually many connections — may pick a root you wouldn't have
chosen by hand; a populated group is usually, but not always, the winner
in its own cluster for the same reason (an individual member with enough
of its own edges elsewhere can still out-rank it). The generated file is
a normal meshfox canvas, so this is easy to fix afterwards (`meshfox
view` or a text editor) rather than something the tool needs to get
perfectly right up front.

### Tests
<!-- meshfox:node id="tests" -->

The test suite reconstructs the node tree from the emitted markdown the
same way meshfox's own parser would (heading nesting + `parent=`
overrides + `meshfox:edge`), and checks it against the source canvas's
edges — this is a regression test for a real bug caught during
development, where emitting nodes in breadth-first order silently
scrambled the heading nesting below depth 2.

```bash name="tests" cache
python3 -m unittest discover -s tests -v
```
<!-- meshfox:output name="tests" hash="9f31b169" -->
```text
exit code: 0 · 196ms

test_deep_chain_and_branching_preserves_all_edges (test_obsidian2meshfox.RoundTripTests.test_deep_chain_and_branching_preserves_all_edges) ... ok
test_edge_label_color_and_arrow_end_carried_on_extra_edge (test_obsidian2meshfox.RoundTripTests.test_edge_label_color_and_arrow_end_carried_on_extra_edge) ... ok
test_file_node_is_copied_next_to_output (test_obsidian2meshfox.RoundTripTests.test_file_node_is_copied_next_to_output) ... ok
test_file_node_subpath_becomes_link_fragment (test_obsidian2meshfox.RoundTripTests.test_file_node_subpath_becomes_link_fragment) ... ok
test_group_node_gets_label_as_title_and_nests_contained_members (test_obsidian2meshfox.RoundTripTests.test_group_node_gets_label_as_title_and_nests_contained_members) ... ok
test_isolated_node_becomes_its_own_section (test_obsidian2meshfox.RoundTripTests.test_isolated_node_becomes_its_own_section) ... ok
test_link_node_gets_preview_by_default (test_obsidian2meshfox.RoundTripTests.test_link_node_gets_preview_by_default) ... ok
test_no_coordinates_in_output (test_obsidian2meshfox.RoundTripTests.test_no_coordinates_in_output) ... ok
test_no_preview_flag_omits_attribute (test_obsidian2meshfox.RoundTripTests.test_no_preview_flag_omits_attribute) ... ok
test_node_color_is_carried_over (test_obsidian2meshfox.RoundTripTests.test_node_color_is_carried_over) ... ok
test_structural_edge_label_becomes_edge_label_attribute (test_obsidian2meshfox.RoundTripTests.test_structural_edge_label_becomes_edge_label_attribute) ... ok

----------------------------------------------------------------------
Ran 11 tests in 0.010s

OK
```
<!-- /meshfox:output -->

