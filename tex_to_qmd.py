#!/usr/bin/env python3
import re
import sys
import subprocess
import tempfile
from pathlib import Path


def find_matching(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Return index of matching close_ch for open_ch at *start* or -1."""
    depth = 1
    i = start + 1
    while i < len(text):
        c = text[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def preprocess_latex(src: str) -> str:
    """Convert custom environments and observation macros before pandoc."""

    def repl_python(m: re.Match) -> str:
        """Preserve python blocks exactly using markers."""
        code = m.group(1)
        return ("\\begin{verbatim}\n%%PYTHON_START%%\n" + code +
                "%%PYTHON_END%%\n\\end{verbatim}")

    # replace python environment with verbatim + markers without touching
    # the whitespace contained in the block
    src = re.sub(
        r"\\begin{python}(?:\[[^\]]*\])?\n(.*?)\\end{python}",
        repl_python,
        src,
        flags=re.S,
    )

    # convert err environment so pandoc will parse inside while preserving
    # the whitespace exactly
    src = re.sub(
        r"\\begin{err}\n?(.*?)\\end{err}",
        lambda m: f"<err>{m.group(1)}</err>",
        src,
        flags=re.S,
    )

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
        end_attrs = find_matching(src, j, '[', ']')
        if end_attrs == -1:
            out.append(src[idx:])
            break
        attrs = src[j + 1:end_attrs]
        j = end_attrs + 1
        if j >= len(src) or src[j] != '{':
            out.append(src[idx:])
            break
        end_body = find_matching(src, j, '{', '}')
        if end_body == -1:
            out.append(src[idx:])
            break
        body = src[j + 1:end_body]
        j = end_body + 1
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
    for line in text.splitlines(keepends=True):
        if re.match(r'^\s*%%PYTHON_START%%', line):
            lines.append('```{python}\n')
            in_py = True
            continue
        if re.match(r'^\s*%%PYTHON_END%%', line):
            lines.append('```\n')
            in_py = False
            continue
        if in_py and line.startswith('    '):
            lines.append(line[4:])
        else:
            lines.append(line)
    return ''.join(lines)


def format_observations(text: str, width: int = 80) -> str:
    """Wrap observation tags so opening/closing are on the same line."""

    obs_re = re.compile(r'(<obs[^>]*>)(.*?)(</obs>)', flags=re.S)

    def repl(match: re.Match) -> str:
        open_tag = re.sub(r'\s+', ' ', match.group(1).strip())
        body = re.sub(r'\s+', ' ', match.group(2).strip())
        words = body.split()
        prefix = open_tag
        lines = []
        line = prefix
        avail = width - len('</obs>')
        for w in words:
            if len(line) + 1 + len(w) > avail:
                lines.append(line)
                line = ' ' * len(prefix) + w
            else:
                if line == prefix:
                    line += ' ' + w
                else:
                    line += ' ' + w
        lines.append(line + '</obs>')
        return '\n'.join(lines)

    return obs_re.sub(repl, text)


def format_tags(text: str, indent_str: str = '    ') -> str:
    """Format <err> blocks with indentation and wrap <obs> tags."""
    text = format_observations(text)
    # ensure opening obs tags start on a new line
    text = re.sub(r'\n[ \t]*(<obs)', r'\n\1', text)
    text = re.sub(r'(?<!^)(?<!\n)(<obs)', r'\n\1', text)
    text = re.sub(r'<err>[ \t]*\n+', '<err>\n', text)
    # ensure exactly one newline after closing obs tags
    text = re.sub(r'</obs>\s*', '</obs>\n', text)
    pattern = re.compile(r'(<err>|</err>)')
    parts = pattern.split(text)
    out = []
    indent = 0
    prev_tag = None
    for part in parts:
        if not part:
            continue
        if part == '<err>':
            if out and not out[-1].endswith('\n'):
                out[-1] = out[-1].rstrip() + '\n'
            out.append(indent_str * indent + '<err>\n')
            indent += 1
            prev_tag = '<err>'
        elif part == '</err>':
            if out and not out[-1].endswith('\n'):
                out[-1] = out[-1].rstrip() + '\n'
            indent -= 1
            out.append(indent_str * indent + '</err>\n')
            prev_tag = '</err>'
        else:
            if prev_tag in ('<err>', '</err>') and part.startswith('\n'):
                part = part[1:]
            lines = part.splitlines(True)
            for line in lines:
                if line.strip():
                    out.append(indent_str * indent + line.lstrip())
                else:
                    out.append(line)
            prev_tag = None
    formatted = ''.join(out)
    return re.sub(r'[ \t]+(?=\n)', '', formatted)


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
    formatted = format_tags(final_text)
    out_path = base.with_suffix('.qmd')
    out_path.write_text(formatted)
    print(f"Wrote {out_path}")


if __name__ == '__main__':
    main()
