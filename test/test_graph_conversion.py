from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
import yaml_graph


def test_yaml_to_dot_matches_existing():
    root = Path(__file__).resolve().parents[1]
    yaml_path = root / "graph" / "graph.yaml"
    dot_expected = (root / "graph" / "graph.dot").read_text().strip()
    graph = yaml_graph.load_yaml(yaml_path)
    dot_generated = yaml_graph.to_dot(graph).strip()
    assert dot_generated == dot_expected
