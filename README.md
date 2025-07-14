# Quarto Example

This repository demonstrates using Quarto with custom helpers.

## Pre-commit Hook

A `pre-commit` script generates `tags` for all labelled sections in QMD
files. To enable it, set the repository's hooks path:

```bash
git config core.hooksPath githooks
```

You can run the hook manually with Git 2.43 or later:

```bash
git hook run pre-commit
```

## Previewing

Use `preview.sh` to install Quarto (if needed), expand cross references, and
start the preview server:

```bash
./preview.sh
```

The script installs Quarto if it isn't available and then runs the preview
server without opening a browser.

## Rendering a Document

To render a single document without executing its code (useful when
dependencies for execution aren't installed), run:

```bash
quarto render project1/example.qmd --no-execute
```

The resulting HTML will be placed in the `_site` directory.

## Fast Build with Watch Mode

Use `fast_build.py` to build the site with Pandoc. Running it with `--watch` automatically rebuilds when watched files change and serves the output. When building in a headless environment, add `--no-browser`.

```bash
python3 fast_build.py --watch --no-browser
```

When a file such as `project1/subproject1/tasks.qmd` is modified, the script prints a "Change detected" message and refreshes the HTML in `_build` without restarting.
