#!/usr/bin/env python3
import os
import re
import subprocess
import time
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import threading
import shutil
import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from selenium import webdriver
import selenium

include_pattern = re.compile(r"\{\{\s*<\s*(include|embed)\s+([^>\s]+)\s*>\s*\}\}")

# Collect anchor definitions {#sec:id}, {#fig:id}, {#tab:id}
anchor_pattern = re.compile(r"\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")
heading_pattern = re.compile(r"^(#+)\s+(.*?)\s*\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")

def load_rendered_files():
    cfg = yaml.safe_load(Path('_quarto.yml').read_text())
    return list(cfg.get('project', {}).get('render', []))


def build_include_map(render_files):
    """Map each included file to the files that include it."""
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






BUILD_DIR = Path('_build')
BODY_TEMPLATE = Path('body-only.html').resolve()


def build_include_tree(render_files):
    """Return mapping of each file to the files it includes and their root dirs."""
    tree = {}
    visited = set()
    stack = [Path(f).resolve() for f in render_files]
    root = Path('.').resolve()
    root_dirs = {Path(f).resolve(): Path(f).parent.resolve() for f in render_files}
    while stack:
        current = stack.pop()
        if current in visited or not current.exists():
            continue
        visited.add(current)
        root_dir = root_dirs.get(current, root_dirs.get(Path(current), current.parent))
        includes = []
        text = current.read_text()
        for _kind, inc in include_pattern.findall(text):
            target = (root_dir / inc).resolve()
            try:
                rel = target.relative_to(root).as_posix()
            except ValueError:
                rel = target.as_posix()
            includes.append(rel)
            stack.append(target)
            root_dirs[target] = root_dir
        try:
            key = current.relative_to(root).as_posix()
        except ValueError:
            key = current.as_posix()
        tree[key] = includes
    # convert keys to posix strings
    root_dirs_str = {p.relative_to(root).as_posix(): d for p, d in root_dirs.items() if p.exists()}
    return tree, root_dirs_str


def all_files(render_files, tree):
    files = set(render_files)
    for src, incs in tree.items():
        files.add(src)
        files.update(incs)
    return files


def build_order(render_files, tree):
    order = []
    visited = set()

    def visit(f):
        if f in visited:
            return
        visited.add(f)
        for child in tree.get(f, []):
            visit(child)
        order.append(f)

    for f in render_files:
        visit(f)
    return order


def mirror_and_modify(files, anchors, roots):
    project_root = PROJECT_ROOT
    for file in files:
        src = Path(file)
        dest = BUILD_DIR / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text()
        text = replace_refs_text(text, anchors)

        root_dir = roots.get(file, src.parent)

        def repl(match: re.Match) -> str:
            kind, inc = match.groups()
            target_src = (root_dir / inc).resolve()
            target_rel = target_src.relative_to(project_root)
            html_path = (BUILD_DIR / target_rel).with_suffix('.html')
            inc_path = os.path.relpath(html_path, dest.parent)
            # use an element marker preserved by Pandoc
            return f"<div data-{kind.lower()}=\"{inc_path}\"></div>"

        text = include_pattern.sub(repl, text)
        dest.write_text(text)


PROJECT_ROOT = Path('.').resolve()


def render_file(src: Path, dest: Path, fragment: bool):
    """Render ``src`` to ``dest`` using Quarto with embedded resources."""

    args = [
        "quarto",
        "render",
        dest.name,
    ]
    if fragment:
        args.append("--embed-resources")
        template_path = os.path.relpath(BODY_TEMPLATE, dest.parent)
        args += ["--to", "html", "--template", template_path]
    args += ["--output", dest.with_suffix(".html").name]
    subprocess.run(args, check=True, cwd=dest.parent)


from lxml import html as lxml_html

def postprocess_html(html_path: Path):
    """Replace placeholder nodes with referenced HTML bodies."""
    root = lxml_html.fromstring(html_path.read_text())
    for node in list(root.xpath('//*[@data-include] | //*[@data-embed]')):
        target_rel = node.get('data-include') or node.get('data-embed')
        target = (html_path.parent / target_rel).resolve()
        if target.exists():
            frag_text = target.read_text()
            frag = lxml_html.fromstring(frag_text)
            body = frag.xpath('body')
            if body:
                elems = list(body[0])
            else:
                elems = [frag]
            parent = node.getparent()
            idx = parent.index(node)
            parent.remove(node)
            for elem in reversed(elems):
                parent.insert(idx, elem)
        else:
            node.getparent().remove(node)
    html_path.write_text(lxml_html.tostring(root, encoding='unicode'))


def build_all():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    # copy project configuration without the render list so individual renders
    # don't attempt to build the entire project
    cfg = yaml.safe_load(Path('_quarto.yml').read_text())
    if 'project' in cfg and 'render' in cfg['project']:
        cfg['project']['render'] = []
    (BUILD_DIR / '_quarto.yml').write_text(yaml.safe_dump(cfg))
    if Path('obs.lua').exists():
        shutil.copy2('obs.lua', BUILD_DIR / 'obs.lua')
    render_files = load_rendered_files()
    include_map = build_include_map(render_files)
    tree, roots = build_include_tree(render_files)
    anchors = collect_anchors(render_files, include_map)

    files = all_files(render_files, tree)
    mirror_and_modify(files, anchors, roots)
    order = build_order(render_files, tree)
    for f in order:
        fragment = f not in render_files
        render_file(Path(f), BUILD_DIR / f, fragment)
        postprocess_html((BUILD_DIR / f).with_suffix('.html'))


class BrowserReloader:
    def __init__(self, url: str):
        self.url = url
        self.init_browser()

    def init_browser(self):
        try:
            self.browser = webdriver.Chrome()
        except Exception:
            self.browser = webdriver.Firefox()
        self.browser.get(self.url)

    def refresh(self):
        try:
            self.browser.refresh()
        except selenium.common.exceptions.WebDriverException:
            self.browser.quit()
            self.init_browser()


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, build_func, refresher):
        self.build = build_func
        self.refresher = refresher

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.qmd') and '/_build/' not in event.src_path:
            print(f"Change detected: {event.src_path}")
            self.build()
            self.refresher.refresh()


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
    port = 8000
    render_files = load_rendered_files()
    if render_files:
        start_page = Path(render_files[0]).with_suffix('.html').as_posix()
    else:
        start_page = ''
    url = f"http://localhost:{port}/{start_page}"
    threading.Thread(target=serve, kwargs={'dir': str(BUILD_DIR), 'port': port}, daemon=True).start()
    refresher = BrowserReloader(url)
    observer = Observer()
    handler = ChangeHandler(build_all, refresher)
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
