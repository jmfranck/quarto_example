#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import threading
import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

include_pattern = re.compile(r"\{\{\s*<\s*(include|embed)\s+([^>\s]+)\s*>\s*\}\}")

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
            for _kind, inc in include_pattern.findall(content):
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

def replace_refs_text(text, anchors):
    def repl(match):
        kind, ident = match.group(1), match.group(2)
        key = f"{kind}:{ident}"
        if key in anchors:
            file, label = anchors[key]
            link = f"{file.replace('.qmd', '.html')}#{key}"
            return f"[{label}]({link})"
        return match.group(0)
    return ref_pattern.sub(repl, text)

def replace_refs(path, anchors):
    content = path.read_text()
    new_content = replace_refs_text(content, anchors)
    if new_content != content:
        path.write_text(new_content)
        return True
    return False



def render_fragment(src: Path, anchors, cache, root_dir=None) -> str:
    """Render src to HTML fragment with includes expanded."""
    if root_dir is None:
        root_dir = src.parent
    if src in cache:
        return cache[src]

    text = replace_refs_text(src.read_text(), anchors)

    def repl(match: re.Match) -> str:
        target = (root_dir / match.group(2)).resolve()
        return render_fragment(target, anchors, cache, root_dir)

    text = include_pattern.sub(repl, text)

    dest = Path('_build') / src
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)

    html_path = dest.with_suffix('.html')
    subprocess.run(
        ['quarto', 'render', dest.name, '--output', html_path.name, '--no-execute'],
        check=True,
        cwd=dest.parent
    )
    html = html_path.read_text()
    m = re.search(r'<body[^>]*>(.*)</body>', html, flags=re.S)
    if m:
        html = m.group(1)
        html_path.write_text(html)
    cache[src] = html
    return html



def build_all():
    render_files = load_rendered_files()
    include_map = build_include_map(render_files)
    anchors = collect_anchors(render_files, include_map)
    cache = {}
    for src in render_files:
        render_fragment(Path(src), anchors, cache)


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, build_func):
        self.build = build_func

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.qmd') and '/_build/' not in event.src_path:
            print(f"Change detected: {event.src_path}")
            self.build()


def serve(dir: str = '_build', port: int = 8000):
    handler = SimpleHTTPRequestHandler
    httpd = ThreadingHTTPServer(('0.0.0.0', port), handler)
    print(f"Serving {dir} at http://localhost:{port}")
    Path(dir).mkdir(parents=True, exist_ok=True)
    orig = Path.cwd()
    try:
        os.chdir(dir)
        httpd.serve_forever()
    finally:
        os.chdir(orig)


def watch_and_serve():
    build_all()
    threading.Thread(target=serve, daemon=True).start()
    observer = Observer()
    handler = ChangeHandler(build_all)
    observer.schedule(handler, '.', recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Resolve refs and build site")
    parser.add_argument('--watch', action='store_true', help='Watch files and serve site')
    args = parser.parse_args()
    if args.watch:
        watch_and_serve()
    else:
        build_all()
