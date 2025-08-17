"""Utilities for working with graphs stored in YAML.

Each node is represented as a mapping with the following keys:
- text: label for the node
- parents: list of parent node names
- children: list of child node names
- subgraph: optional name of a subgraph/cluster

The module loads the YAML file into an in-memory dictionary and ensures
that parent/child relationships are symmetric. It can also emit a Graphviz
DOT representation of the graph.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set, Optional
import yaml
from collections import defaultdict


@dataclass
class Node:
    text: str
    parents: Set[str] = field(default_factory=set)
    children: Set[str] = field(default_factory=set)
    subgraph: Optional[str] = None


def load_yaml(path: Path) -> Dict[str, Node]:
    """Load a YAML graph description into a dictionary of Nodes.

    Parent/child relationships are kept in sync so that if a node lists a
    child, that child will list the node as a parent (and vice versa).
    """
    data = yaml.safe_load(Path(path).read_text()) or {}
    graph: Dict[str, Node] = {}
    for name, info in data.items():
        graph[name] = Node(
            text=info.get("text", name),
            parents=set(info.get("parents", [])),
            children=set(info.get("children", [])),
            subgraph=info.get("subgraph"),
        )
    # ensure symmetry
    for name, node in list(graph.items()):
        for child in list(node.children):
            if child not in graph:
                graph[child] = Node(text=child)
            graph[child].parents.add(name)
        for parent in list(node.parents):
            if parent not in graph:
                graph[parent] = Node(text=parent)
            graph[parent].children.add(name)
    return graph


def to_dot(graph: Dict[str, Node]) -> str:
    """Create a DOT representation of the graph."""
    lines = ["digraph G {"]
    # organise nodes by subgraph
    subgraphs: Dict[Optional[str], list[str]] = defaultdict(list)
    for name, node in graph.items():
        subgraphs[node.subgraph].append(name)
    # render subgraphs
    for subgraph, nodes in subgraphs.items():
        if subgraph is None:
            continue
        lines.append(f'    subgraph cluster_{subgraph} {{')
        lines.append(f'        label="{subgraph}";')
        for name in nodes:
            lines.append(f'        "{name}" [label="{graph[name].text}"];')
        lines.append("    }")
    # nodes not in a subgraph
    for name in subgraphs[None]:
        lines.append(f'    "{name}" [label="{graph[name].text}"];')
    # edges
    for name, node in graph.items():
        for child in node.children:
            lines.append(f'    "{name}" -> "{child}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_dot_from_yaml(yaml_path: Path, dot_path: Path) -> None:
    """Read YAML file and write a DOT file."""
    graph = load_yaml(yaml_path)
    dot_path.write_text(to_dot(graph))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Convert YAML graph to DOT")
    parser.add_argument("yaml_file", type=Path)
    parser.add_argument("dot_file", type=Path)
    args = parser.parse_args()
    write_dot_from_yaml(args.yaml_file, args.dot_file)


if __name__ == "__main__":
    main()
