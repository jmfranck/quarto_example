#!/usr/bin/env python3
"""Minimal build script using Pandoc instead of Quarto."""

import hashlib
import os
import re
import subprocess
import time
import traceback
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import threading
import shutil
import yaml
# use a polling observer for wider compatibility
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler
from selenium import webdriver
import selenium
from jinja2 import Environment, FileSystemLoader
import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
from nbconvert.preprocessors.execute import NotebookClient
import html as html_lib


class LoggingExecutePreprocessor(ExecutePreprocessor):
    """Execute notebook cells with progress printed to stdout."""

    def preprocess(self, nb, resources=None, km=None):
        NotebookClient.__init__(self, nb, km)
        self.reset_execution_trackers()
        self._check_assign_resources(resources)
        cell_count = len(self.nb.cells)

        with self.setup_kernel():
            assert self.kc
            info_msg = self.wait_for_reply(self.kc.kernel_info())
            assert info_msg
            self.nb.metadata["language_info"] = info_msg["content"]["language_info"]
            for index, cell in enumerate(self.nb.cells):
                print(f"Executing cell {index + 1}/{cell_count}...", flush=True)
                self.preprocess_cell(cell, resources, index)
        self.set_widgets_metadata()

        return self.nb, self.resources


# Ensure Pandoc can be found even if only Quarto is installed
if not shutil.which("pandoc"):
    quarto_pandoc = Path("/opt/quarto/bin/tools/x86_64/pandoc")
    if quarto_pandoc.exists():
        os.environ["PATH"] += os.pathsep + str(quarto_pandoc.parent)

include_pattern = re.compile(r"\{\{\s*<\s*(include|embed)\s+([^>\s]+)\s*>\s*\}\}")
# Python code block pattern
code_pattern = re.compile(r"```\{python[^}]*\}\n(.*?)```", re.DOTALL)

# Collect anchor definitions {#sec:id}, {#fig:id}, {#tab:id}
anchor_pattern = re.compile(r"\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")
heading_pattern = re.compile(r"^(#+)\s+(.*?)\s*\{#(sec|fig|tab):([A-Za-z0-9_-]+)\}")


def load_rendered_files():
    cfg = yaml.safe_load(Path("_quarto.yml").read_text())
    return list(cfg.get("project", {}).get("render", []))


def load_bibliography_csl():
    cfg = yaml.safe_load(Path("_quarto.yml").read_text())
    bib = None
    csl = None
    if "bibliography" in cfg:
        bib = cfg["bibliography"]
    if "csl" in cfg:
        csl = cfg["csl"]
    fmt = cfg.get("format", {})
    if isinstance(fmt, dict):
        for v in fmt.values():
            if isinstance(v, dict):
                bib = bib or v.get("bibliography")
                csl = csl or v.get("csl")
    return bib, csl


def outputs_to_html(outputs: list[dict]) -> str:
    """Convert Jupyter cell outputs to HTML with embedded images."""
    parts = []
    for out in outputs:
        typ = out.get("output_type")
        if typ == "stream":
            text = out.get("text", "")
            parts.append(f"<pre>{html_lib.escape(text)}</pre>")
        elif typ in {"display_data", "execute_result"}:
            data = out.get("data", {})
            if "text/html" in data:
                parts.append(data["text/html"])
            elif "image/png" in data:
                src = f"data:image/png;base64,{data['image/png']}"
                parts.append(f"<img src='{src}'/>")
            elif "image/jpeg" in data:
                src = f"data:image/jpeg;base64,{data['image/jpeg']}"
                parts.append(f"<img src='{src}'/>")
            elif "text/plain" in data:
                parts.append(f"<pre>{html_lib.escape(data['text/plain'])}</pre>")
        elif typ == "error":
            tb = "\n".join(out.get("traceback", []))
            if not tb:
                tb = f"{out.get('ename', '')}: {out.get('evalue', '')}"
            parts.append(f"<pre style='color:red;'>{html_lib.escape(tb)}</pre>")
    return "\n".join(parts)


NOTEBOOK_CACHE_DIR = Path("_nbcache")


def execute_code_blocks(blocks: dict[str, list[tuple[str, str]]]) -> dict[tuple[str, int], str]:
    """Run code blocks as Jupyter notebooks with caching."""
    NOTEBOOK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[tuple[str, int], str] = {}
    for src, cells in blocks.items():
        if not cells:
            continue
        codes = [c for c, _ in cells]
        md5s = [m for _, m in cells]
        combined = "".join(md5s).encode()
        nb_hash = hashlib.md5(combined).hexdigest()
        nb_path = NOTEBOOK_CACHE_DIR / f"{nb_hash}.ipynb"
        if nb_path.exists():
            nb = nbformat.read(nb_path, as_version=4)
        else:
            nb = nbformat.v4.new_notebook()
            nb.cells = [nbformat.v4.new_code_cell(c) for c in codes]
            ep = ExecutePreprocessor(kernel_name="python3", timeout=300, allow_errors=True)
            try:
                ep.preprocess(nb, {"metadata": {"path": str(Path(src).parent)}})
            except Exception as e:
                tb = traceback.format_exc()
                if nb.cells:
                    nb.cells[0].outputs = [
                        {
                            "output_type": "error",
                            "ename": type(e).__name__,
                            "evalue": str(e),
                            "traceback": tb.splitlines(),
                        }
                    ]
                    for cell in nb.cells[1:]:
                        cell.outputs = [
                            {
                                "output_type": "stream",
                                "name": "stderr",
                                "text": "previous cell failed to execute\n",
                            }
                        ]
            nbformat.write(nb, nb_path)
        for idx, cell in enumerate(nb.cells, start=1):
            html = outputs_to_html(cell.get("outputs", []))
            results[(src, idx)] = html
    return results


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
                    target_rel = target.relative_to(Path(".").resolve())
                    current_rel = current.relative_to(Path(".").resolve())
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
    for path in Path(".").rglob("*.qmd"):
        if BUILD_DIR in path.parents:
            continue
        lines = path.read_text().splitlines()
        for line in lines:
            for m in anchor_pattern.finditer(line):
                kind, ident = m.group(1), m.group(2)
                key = f"{kind}:{ident}"
                text = ident
                hm = heading_pattern.match(line)
                if hm:
                    text = hm.group(2).strip()
                render_file = resolve_render_file(
                    path.as_posix(), included_by, render_files
                )
                anchors[key] = (render_file, text)
    return anchors


ref_pattern = re.compile(r"@(sec|fig|tab):([A-Za-z0-9_-]+)")


def replace_refs_text(text, anchors, dest_dir: Path):
    def repl(match):
        kind, ident = match.group(1), match.group(2)
        key = f"{kind}:{ident}"
        if key in anchors:
            file, label = anchors[key]
            html_path = BUILD_DIR / file.replace(".qmd", ".html")
            rel = os.path.relpath(html_path, dest_dir)
            link = f"{rel}#{key}"
            return f"[{label}]({link})"
        return match.group(0)

    return ref_pattern.sub(repl, text)


def replace_refs(path, anchors):
    content = path.read_text()
    new_content = replace_refs_text(content, anchors, path.parent)
    if new_content != content:
        path.write_text(new_content)
        return True
    return False


BUILD_DIR = Path("_build")
BODY_TEMPLATE = Path("body-only.html").resolve()
PANDOC_TEMPLATE = Path("pandoc_template.html").resolve()
NAV_TEMPLATE = Path("nav_template.html").resolve()
MATHJAX_DIR = Path("mathjax").resolve()


def ensure_mathjax():
    """Ensure MathJax is available locally using npm if necessary."""
    script = MATHJAX_DIR / "es5" / "tex-mml-chtml.js"
    if script.exists():
        return
    tmp = Path("_mjtmp")
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(["npm", "init", "-y"], cwd=tmp, check=True)
    subprocess.run(["npm", "install", "mathjax-full"], cwd=tmp, check=True)
    src = tmp / "node_modules" / "mathjax-full" / "es5"
    (MATHJAX_DIR / "es5").mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, MATHJAX_DIR / "es5", dirs_exist_ok=True)
    shutil.rmtree(tmp)


def build_include_tree(render_files):
    """Return mapping of each file to the files it includes and their root dirs."""
    tree = {}
    visited = set()
    stack = [Path(f).resolve() for f in render_files]
    root = Path(".").resolve()
    root_dirs = {Path(f).resolve(): Path(f).parent.resolve() for f in render_files}
    while stack:
        current = stack.pop()
        if current in visited or not current.exists():
            continue
        visited.add(current)
        root_dir = root_dirs.get(current, current.parent)
        includes = []
        text = current.read_text()
        for _kind, inc in include_pattern.findall(text):
            target = (current.parent / inc).resolve()
            if not target.exists():
                target = (root_dir / inc).resolve()
            if not target.exists():
                target = (root_dir.parent / inc).resolve()
            if not target.exists():
                continue
            try:
                rel = target.relative_to(root).as_posix()
            except ValueError:
                rel = target.as_posix()
            includes.append(rel)
            stack.append(target)
            # propagate the original root directory so includes are
            # resolved relative to the main document rather than the
            # including file
            root_dirs.setdefault(target, root_dir)
        try:
            key = current.relative_to(root).as_posix()
        except ValueError:
            key = current.as_posix()
        tree[key] = includes
    # convert keys to posix strings
    root_dirs_str = {
        p.relative_to(root).as_posix(): d for p, d in root_dirs.items() if p.exists()
    }
    return tree, root_dirs_str


def all_files(render_files, tree):
    files = {f for f in render_files if Path(f).exists()}
    for src, incs in tree.items():
        if Path(src).exists():
            files.add(src)
        for inc in incs:
            if Path(inc).exists():
                files.add(inc)
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
    code_blocks: dict[str, list[tuple[str, str]]] = {}
    for file in files:
        src = Path(file)
        dest = BUILD_DIR / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text()
        text = replace_refs_text(text, anchors, dest.parent)

        root_dir = roots.get(file, src.parent)

        def repl(match: re.Match) -> str:
            kind, inc = match.groups()
            # include paths are now relative to the main document root
            target_src = (root_dir / inc).resolve()
            if not target_src.exists():
                target_src = (src.parent / inc).resolve()
            if not target_src.exists():
                target_src = (root_dir.parent / inc).resolve()
            target_rel = target_src.relative_to(project_root)
            html_path = (BUILD_DIR / target_rel).with_suffix(".html")
            inc_path = os.path.relpath(html_path, dest.parent)
            # use an element marker preserved by Pandoc
            return f'<div data-{kind.lower()}="{inc_path}"></div>'

        text = include_pattern.sub(repl, text)

        idx = 0

        def repl_code(match: re.Match) -> str:
            nonlocal idx
            idx += 1
            code = match.group(1)
            md5 = hashlib.md5(code.encode()).hexdigest()
            src_rel = str(src)
            code_blocks.setdefault(src_rel, []).append((code, md5))
            return f"<div data-script=\"{src_rel}\" data-index=\"{idx}\" data-md5=\"{md5}\"></div>"
        text = code_pattern.sub(repl_code, text)
        dest.write_text(text)
    return code_blocks


PROJECT_ROOT = Path(".").resolve()


def render_file(src: Path, dest: Path, fragment: bool, bibliography=None, csl=None):
    """Render ``src`` to ``dest`` using Pandoc with embedded resources."""

    template = BODY_TEMPLATE if fragment else PANDOC_TEMPLATE
    args = [
        "pandoc",
        src.name,
        "--from",
        "markdown+raw_html",
        "--standalone",
        "--embed-resources",
        "--lua-filter",
        os.path.relpath(BUILD_DIR / "obs.lua", dest.parent),
        f"--mathjax={os.path.relpath(BUILD_DIR / 'mathjax' / 'es5' / 'tex-mml-chtml.js', dest.parent)}",
        "--template",
        os.path.relpath(template, dest.parent),
        "-o",
        dest.with_suffix(".html").name,
    ]
    if bibliography:
        args += ["--bibliography", os.path.relpath(bibliography, dest.parent)]
    if csl:
        args += ["--csl", os.path.relpath(csl, dest.parent)]
    try:
        subprocess.run(args, check=True, cwd=dest.parent, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{e.stderr}")


from lxml import html as lxml_html


def parse_headings(html_path: Path):
    """Return a nested list of headings found in ``html_path``."""
    parser = lxml_html.HTMLParser(encoding="utf-8")
    tree = lxml_html.parse(str(html_path), parser)
    root = tree.getroot()
    headings = root.xpath("//h1|//h2|//h3|//h4|//h5|//h6")
    # Skip headings used for the page title which Quarto renders with the
    # ``title`` class. Including these in the navigation duplicates the page
    # title entry in the section list.
    def is_page_title(h):
        cls = h.get('class') or ''
        return 'title' in cls.split()

    headings = [h for h in headings if not is_page_title(h)]
    items: list[dict] = []
    stack = []
    for h in headings:
        level = int(h.tag[1])
        text = "".join(h.itertext()).strip()
        ident = h.get("id")
        node = {"level": level, "text": text, "id": ident, "children": []}
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            items.append(node)
        stack.append(node)
    return items


def read_title(qmd: Path) -> str:
    text = qmd.read_text()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(text[3:end])
                if isinstance(meta, dict) and "title" in meta:
                    return str(meta["title"])
            except Exception:
                pass
    m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return qmd.stem


def add_navigation(html_path: Path, pages: list[dict], current: str):
    """Insert navigation menu for ``html_path`` using ``pages`` data."""
    parser = lxml_html.HTMLParser(encoding="utf-8")
    tree = lxml_html.parse(str(html_path), parser)
    root = tree.getroot()
    body = root.xpath("//body")
    if not body:
        return
    env = Environment(loader=FileSystemLoader(str(NAV_TEMPLATE.parent)))
    tmpl = env.get_template(NAV_TEMPLATE.name)
    local_pages = []
    for page in pages:
        href_path = (BUILD_DIR / page["file"]).with_suffix(".html")
        href = os.path.relpath(href_path, html_path.parent)
        local_pages.append({**page, "href": href})
    rendered = tmpl.render(pages=local_pages, current=current)
    frags = lxml_html.fragments_fromstring(rendered)
    head = root.xpath("//head")
    head = head[0] if head else None
    for frag in frags:
        if frag.tag == "style" and head is not None:
            head.append(frag)
        else:
            body[0].insert(0, frag)
    tree.write(str(html_path), encoding="utf-8", method="html")


def postprocess_html(html_path: Path):
    """Replace placeholder nodes with referenced HTML bodies."""
    root = lxml_html.fromstring(html_path.read_text())
    for node in list(root.xpath("//*[@data-include] | //*[@data-embed]")):
        target_rel = node.get("data-include") or node.get("data-embed")
        target = (html_path.parent / target_rel).resolve()
        if target.exists():
            frag_text = target.read_text()
            frag = lxml_html.fromstring(frag_text)
            body = frag.xpath("body")
            if body:
                elems = list(body[0])
            else:
                elems = [frag]
            parent = node.getparent()
            idx = parent.index(node)
            parent.remove(node)
            end_c = lxml_html.HtmlComment(f"END include {target_rel}")
            start_c = lxml_html.HtmlComment(f"BEGIN include {target_rel}")
            parent.insert(idx, end_c)
            for elem in reversed(elems):
                parent.insert(idx, elem)
            parent.insert(idx, start_c)
        else:
            node.getparent().remove(node)
    # add MathJax if math is present
    has_math = bool(root.xpath('//*[@class="math inline" or @class="math display"]'))
    has_script = bool(root.xpath('//script[contains(@src, "MathJax")]'))
    if has_math and not has_script:
        head = root.xpath("//head")
        if head:
            path = os.path.relpath(
                BUILD_DIR / "mathjax" / "es5" / "tex-mml-chtml.js", html_path.parent
            )
            script = lxml_html.fragment_fromstring(
                f'<script id="MathJax-script" async src="{path}"></script>',
                create_parent=False,
            )
            head[0].append(script)
    html_path.write_text(lxml_html.tostring(root, encoding="unicode"))


def substitute_code_placeholders(html_path: Path, outputs: dict[tuple[str, int], str]):
    """Replace script placeholders in ``html_path`` using executed outputs."""
    parser = lxml_html.HTMLParser(encoding="utf-8")
    tree = lxml_html.parse(str(html_path), parser)
    root = tree.getroot()
    changed = False
    for node in list(root.xpath("//div[@data-script][@data-index]")):
        src = node.get("data-script")
        try:
            idx = int(node.get("data-index", "0"))
        except ValueError:
            idx = 0
        html = outputs.get((src, idx), "")
        frags = lxml_html.fragments_fromstring(html) if html else []
        parent = node.getparent()
        if parent is None:
            continue
        pos = parent.index(node)
        parent.remove(node)
        for frag in reversed(frags):
            parent.insert(pos, frag)
        changed = True
    if changed:
        tree.write(str(html_path), encoding="utf-8", method="html")


def build_all():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    ensure_mathjax()
    shutil.copytree(MATHJAX_DIR, BUILD_DIR / "mathjax", dirs_exist_ok=True)
    # copy project configuration without the render list so individual renders
    # don't attempt to build the entire project
    cfg = yaml.safe_load(Path("_quarto.yml").read_text())
    if "project" in cfg and "render" in cfg["project"]:
        cfg["project"]["render"] = []
    (BUILD_DIR / "_quarto.yml").write_text(yaml.safe_dump(cfg))
    if Path("obs.lua").exists():
        shutil.copy2("obs.lua", BUILD_DIR / "obs.lua")
    render_files = load_rendered_files()
    bibliography, csl = load_bibliography_csl()
    include_map = build_include_map(render_files)
    tree, roots = build_include_tree(render_files)
    anchors = collect_anchors(render_files, include_map)

    files = all_files(render_files, tree)
    code_blocks = mirror_and_modify(files, anchors, roots)
    order = build_order(render_files, tree)
    for f in order:
        fragment = f not in render_files
        render_file(Path(f), BUILD_DIR / f, fragment, bibliography, csl)
        html_file = (BUILD_DIR / f).with_suffix(".html")
        postprocess_html(html_file)

    pages = []
    for qmd in render_files:
        html_file = (BUILD_DIR / qmd).with_suffix(".html")
        if html_file.exists():
            sections = parse_headings(html_file)
            pages.append(
                {
                    "file": qmd,
                    "href": html_file.name,
                    "title": read_title(Path(qmd)),
                    "sections": sections,
                }
            )

    for page in pages:
        html_file = (BUILD_DIR / page["file"]).with_suffix(".html")
        add_navigation(html_file, pages, page["file"])

    outputs = execute_code_blocks(code_blocks)
    for f in files:
        html_file = (BUILD_DIR / f).with_suffix(".html")
        if html_file.exists():
            substitute_code_placeholders(html_file, outputs)


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

    def handle(self, path, is_directory):
        if not is_directory and path.endswith('.qmd') and '/_build/' not in path:
            print(f"Change detected: {path}")
            self.build()
            self.refresher.refresh()

    def on_modified(self, event):
        self.handle(event.src_path, event.is_directory)

    def on_created(self, event):
        self.handle(event.src_path, event.is_directory)

    def on_moved(self, event):
        self.handle(event.dest_path, event.is_directory)


def serve(dir: str = "_build", port: int = 8000):
    handler = SimpleHTTPRequestHandler
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
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
    include_map = build_include_map(render_files)
    files_to_watch = sorted(set(render_files) | set(include_map.keys()))

    if render_files:
        start_page = Path(render_files[0]).with_suffix(".html").as_posix()
    else:
        start_page = ""
    url = f"http://localhost:{port}/{start_page}"

    print("Watching files:")
    for f in files_to_watch:
        print(" ", f)

    threading.Thread(target=serve, kwargs={'dir': str(BUILD_DIR), 'port': port}, daemon=True).start()
    refresher = BrowserReloader(url)
    observer = Observer()
    handler = ChangeHandler(build_all, refresher)
    watched_dirs = {str(Path(f).parent) for f in files_to_watch}
    watched_dirs.add('.')
    for d in sorted(watched_dirs):
        observer.schedule(handler, d, recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build site using Pandoc")
    parser.add_argument(
        "--watch", action="store_true", help="Watch files and serve site"
    )
    args = parser.parse_args()
    if args.watch:
        watch_and_serve()
    else:
        build_all()
