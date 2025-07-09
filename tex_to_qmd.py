#!/usr/bin/env python3
import re
import sys
import subprocess
import tempfile
from pathlib import Path


def preprocess_latex(src: str) -> str:
    """Convert custom environments and observation macros before pandoc."""
    # replace python environment with verbatim + markers
    src = re.sub(r"\\begin{python}.*?\n", r"\\begin{verbatim}\n%%PYTHON_START%%\n", src)
    src = re.sub(r"\\end{python}", r"%%PYTHON_END%%\n\\end{verbatim}", src)

    # convert err environment so pandoc will parse inside
    src = src.replace("\\begin{err}", '<div class="err">')
    src = src.replace("\\end{err}", '</div>')

    # handle \o[...]{} observations
    out = []
    i = 0
    while True:
        idx = src.find('\\o[', i)
        if idx == -1:
            out.append(src[i:])
            break
        out.append(src[i:idx])
        j = idx + 2
        if j >= len(src) or src[j] != '[':
            out.append(src[idx:])
            break
        j += 1
        k = src.find(']', j)
        if k == -1:
            out.append(src[idx:])
            break
        attrs = src[j:k]
        j = k + 1
        if j >= len(src) or src[j] != '{':
            out.append(src[idx:])
            break
        j += 1
        depth = 1
        start = j
        while j < len(src) and depth > 0:
            if src[j] == '{':
                depth += 1
            elif src[j] == '}':
                depth -= 1
            j += 1
        body = src[start:j - 1]
        m = re.match(r'(.*?)\s*(\(([^)]+)\))?$', attrs.strip())
        time = m.group(1).strip() if m else attrs.strip()
        author = m.group(3) if m else None
        tag = f'<obs time="{time}"' + (f' author="{author}"' if author else '') + f'>{body}</obs>'
        out.append(tag)
        i = j
    return ''.join(out)


def clean_html_escapes(text: str) -> str:
    return text.replace('\\<', '<').replace('\\>', '>').replace('\\"', '"')


def finalize_markers(text: str) -> str:
    lines = []
    in_py = False
    for line in text.splitlines():
        if re.match(r'^\s*%%PYTHON_START%%', line):
            lines.append('```{python}')
            in_py = True
            continue
        if re.match(r'^\s*%%PYTHON_END%%', line):
            lines.append('```')
            in_py = False
            continue
        if in_py and line.startswith('    '):
            lines.append(line[4:])
        else:
            lines.append(line)
    content = "\n".join(lines)
    return content.replace('<div class="err">', '<err>').replace('</div>', '</err>')


def main():
    if len(sys.argv) != 2:
        print("Usage: tex_to_qmd.py file.tex", file=sys.stderr)
        sys.exit(1)

    inp = Path(sys.argv[1])
    if not inp.exists():
        print(f"File not found: {inp}", file=sys.stderr)
        sys.exit(1)

    base = inp.with_suffix('')
    src = inp.read_text()
    pre_content = preprocess_latex(src)

    with tempfile.NamedTemporaryFile(delete=False, suffix='.tex') as pre:
        pre.write(pre_content.encode())
        pre_path = pre.name

    mid_fd, mid_path = tempfile.mkstemp()
    Path(mid_path).unlink()  # we just want the name; pandoc will create it

    try:
        subprocess.run(['quarto', 'pandoc', pre_path, '-f', 'latex', '-t', 'markdown', '-o', mid_path], check=True)
    finally:
        Path(pre_path).unlink(missing_ok=True)

    mid_text = Path(mid_path).read_text()
    Path(mid_path).unlink(missing_ok=True)

    clean_text = clean_html_escapes(mid_text)
    final_text = finalize_markers(clean_text)
    out_path = base.with_suffix('.qmd')
    out_path.write_text(final_text)
    print(f"Wrote {out_path}")


if __name__ == '__main__':
    main()
