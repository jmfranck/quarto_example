#!/usr/bin/env python3
import re
from pathlib import Path

# Collect anchor definitions {#sec:id}, {#fig:id}, {#tab:id}
anchor_pattern = re.compile(r"\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")
heading_pattern = re.compile(r"^(#+)\s+(.*?)\s*\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")

def collect_anchors():
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
                anchors[key] = (str(path), text)
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
            return f"[{text}]({file}#{key})"
        return match.group(0)
    content = path.read_text()
    new_content = ref_pattern.sub(repl, content)
    if changed:
        path.write_text(new_content)
    return changed

if __name__ == "__main__":
    anchors = collect_anchors()
    for path in Path('.').rglob('*.qmd'):
        replace_refs(path, anchors)
