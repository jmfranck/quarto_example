#!/usr/bin/env python3
import re
from pathlib import Path
import yaml

include_pattern = re.compile(r"\{\{\s*<\s*include\s+([^>\s]+)\s*>\s*\}\}")

# Collect anchor definitions {#sec:id}, {#fig:id}, {#tab:id}
anchor_pattern = re.compile(r"\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")
heading_pattern = re.compile(r"^(#+)\s+(.*?)\s*\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")

def load_rendered_files():
    cfg = yaml.safe_load(Path('_quarto.yml').read_text())
    return set(cfg.get('project', {}).get('render', []))


def build_include_map(render_files):
    included_by = {}
    for root_file in render_files:
        root_dir = Path(root_file).parent
        stack = [Path(root_file).resolve()]
        visited = set()
        while stack:
            current = stack.pop()
            if current in visited or not current.exists():
                continue
            visited.add(current)
            content = current.read_text()
            for inc in include_pattern.findall(content):
                target = (root_dir / inc).resolve()
                try:
                    target_rel = target.relative_to(Path('.').resolve())
                    current_rel = current.relative_to(Path('.').resolve())
                except ValueError:
                    target_rel = target
                    current_rel = current
                target_path = target_rel.as_posix()
                included_by.setdefault(target_path, []).append(current_rel.as_posix())
                stack.append(target)
    return included_by


def resolve_render_file(file, included_by, render_files):
    visited = set()
    while file not in render_files:
        if file in visited or file not in included_by:
            break
        visited.add(file)
        file = included_by[file][0]
    return file


def collect_anchors(render_files, included_by):
    anchors = {}
    for path in Path('.').rglob('*.qmd'):
        lines = path.read_text().splitlines()
        for line in lines:
            for m in anchor_pattern.finditer(line):
                kind, ident = m.group(1), m.group(2)
                key = f"{kind}:{ident}"
                text = ident
                hm = heading_pattern.match(line)
                if hm:
                    text = hm.group(2).strip()
                render_file = resolve_render_file(path.as_posix(), included_by, render_files)
                anchors[key] = (render_file, text)
    return anchors

ref_pattern = re.compile(r"@(sec|fig|tab):([A-Za-z0-9_-]+)")

def replace_refs(path, anchors):
    changed = False
    def repl(match):
        nonlocal changed
        kind, ident = match.group(1), match.group(2)
        key = f"{kind}:{ident}"
        if key in anchors:
            changed = True
            file, text = anchors[key]
            link = f"{file.replace('.qmd', '.html')}#{key}"
            return f"[{text}]({link})"
        return match.group(0)
    content = path.read_text()
    new_content = ref_pattern.sub(repl, content)
    if changed:
        path.write_text(new_content)
    return changed

if __name__ == "__main__":
    render_files = load_rendered_files()
    include_map = build_include_map(render_files)
    anchors = collect_anchors(render_files, include_map)
    for path in Path('.').rglob('*.qmd'):
        replace_refs(path, anchors)
