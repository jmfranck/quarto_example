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
