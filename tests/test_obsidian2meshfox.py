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
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meshfox_tools.obsidian2meshfox import convert_canvas  # noqa: E402

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
        nodes = [{"id": "A", "type": "text", "text": "Hub", "x": 0, "y": 0, "width": 1, "height": 1}]
        for bid, label in (("B", "Branch B"), ("C", "Branch C"), ("D", "Branch D")):
            nodes.append({"id": bid, "type": "text", "text": label, "x": 0, "y": 0, "width": 1, "height": 1})
        chain = [f"E{i}" for i in range(1, 6)]  # E1..E5
        for cid in chain:
            nodes.append({"id": cid, "type": "text", "text": f"Node {cid}", "x": 0, "y": 0, "width": 1, "height": 1})
        nodes.append({"id": "F", "type": "text", "text": "Shared", "x": 0, "y": 0, "width": 1, "height": 1})

        edges = [("A", "B"), ("A", "C"), ("A", "D"), ("B", "E1")]
        edges += [(chain[i], chain[i + 1]) for i in range(len(chain) - 1)]
        edges += [("C", "F"), ("D", "F")]

        canvas = make_canvas(nodes, edges)
        markdown, canvas = self._convert(canvas)

        expected = {frozenset(e) for e in edges}
        got, node_count = reconstruct_edges(markdown)
        self.assertEqual(node_count, len(nodes))
        self.assertEqual(got, expected)

        # F is reached from both B and D but BFS discovers it via C first
        # (C is dequeued before D), so C becomes F's structural parent and
        # D-F must survive as an explicit extra edge.
        self.assertIn('<!-- meshfox:edge from="D" -->', markdown)

        # The chain runs A(2) B(3) E1(4) E2(5) E3(6) E4(7) E5(8): E4 and E5
        # sit past H6, so both must carry an explicit parent= override and
        # stay pinned at heading level 6.
        self.assertRegex(markdown, r"###### Node E4\n<!-- meshfox:node id=\"E4\"[^>]*parent=\"E3\"")
        self.assertRegex(markdown, r"###### Node E5\n<!-- meshfox:node id=\"E5\"[^>]*parent=\"E4\"")

    def test_link_node_gets_preview_by_default(self):
        nodes = [{"id": "A", "type": "link", "url": "https://example.com/page", "x": 0, "y": 0, "width": 1, "height": 1}]
        markdown, _ = self._convert(make_canvas(nodes, []))
        self.assertIn('type="link" preview="true"', markdown)
        self.assertIn("[example.com/page](https://example.com/page)", markdown)

    def test_no_preview_flag_omits_attribute(self):
        nodes = [{"id": "A", "type": "link", "url": "https://example.com/page", "x": 0, "y": 0, "width": 1, "height": 1}]
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Test.canvas"
            src.write_text(json.dumps(make_canvas(nodes, [])), encoding="utf-8")
            dst = tmp / "Test.canvas.md"
            convert_canvas(src, dst, vault_root=tmp, add_preview=False)
            markdown = dst.read_text(encoding="utf-8")
        self.assertNotIn("preview=", markdown)

    def test_no_coordinates_in_output(self):
        nodes = [{"id": "A", "type": "text", "text": "Hub", "x": 123, "y": 456, "width": 250, "height": 60}]
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
                    "id": "A",
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
            {"id": "A", "type": "text", "text": "Hub", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "B", "type": "text", "text": "Orphan", "x": 0, "y": 0, "width": 1, "height": 1},
        ]
        markdown, _ = self._convert(make_canvas(nodes, []))
        self.assertIn("## Hub", markdown)
        self.assertIn("## Orphan", markdown)

    def test_node_color_is_carried_over(self):
        nodes = [{"id": "A", "type": "text", "text": "Hub", "color": "4", "x": 0, "y": 0, "width": 1, "height": 1}]
        markdown, _ = self._convert(make_canvas(nodes, []))
        self.assertIn('color="4"', markdown)

    def test_edge_label_color_and_arrow_end_carried_on_extra_edge(self):
        nodes = [
            {"id": "A", "type": "text", "text": "Hub", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "B", "type": "text", "text": "Other", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "C", "type": "text", "text": "Extra", "x": 0, "y": 0, "width": 1, "height": 1},
        ]
        canvas = make_canvas(nodes, [("A", "B"), ("A", "C")])
        # B -> C is an extra (non-tree) edge, since C is already reached via A.
        canvas["edges"].append(
            {
                "id": "e-extra",
                "fromNode": "B",
                "toNode": "C",
                "label": "see also",
                "color": "2",
                "toEnd": "none",
            }
        )
        markdown, _ = self._convert(canvas)
        self.assertIn(
            '<!-- meshfox:edge from="B" label="see also" color="2" arrowEnd="none" -->',
            markdown,
        )

    def test_structural_edge_label_becomes_edge_label_attribute(self):
        nodes = [
            {"id": "A", "type": "text", "text": "Hub", "x": 0, "y": 0, "width": 1, "height": 1},
            {"id": "B", "type": "text", "text": "Child", "x": 0, "y": 0, "width": 1, "height": 1},
        ]
        canvas = make_canvas(nodes, [])
        canvas["edges"] = [{"id": "e0", "fromNode": "A", "toNode": "B", "label": "leads to"}]
        markdown, _ = self._convert(canvas)
        self.assertRegex(markdown, r'<!-- meshfox:node id="B"[^>]*edgeLabel="leads to"')

    def test_group_node_gets_label_as_title_and_nests_contained_members(self):
        nodes = [
            {"id": "G", "type": "group", "label": "My Group", "x": 0, "y": 0, "width": 200, "height": 200},
            {"id": "A", "type": "text", "text": "Inside", "x": 10, "y": 10, "width": 50, "height": 50},
        ]
        markdown, _ = self._convert(make_canvas(nodes, []))
        self.assertIn("## My Group", markdown)
        self.assertIn('type="group"', markdown)
        got, node_count = reconstruct_edges(markdown)
        self.assertEqual(node_count, 2)
        self.assertIn(frozenset(("G", "A")), got)
        # A group's own body must stay empty per the meshfox spec.
        self.assertNotIn("Inside\n\n### Inside", markdown)

    def test_file_node_subpath_becomes_link_fragment(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "note.md").write_text("hi", encoding="utf-8")
            nodes = [
                {
                    "id": "A",
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


if __name__ == "__main__":
    unittest.main()
