"""Watch a YAML graph file and regenerate DOT and SVG outputs.

This script uses watchdog to monitor a YAML file. When the file changes,
a DOT file and corresponding SVG are regenerated. A headless Chrome
instance (via Selenium) is used to display the SVG and refresh it when
changes occur.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
import os
import shutil

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

import yaml_graph


class GraphHandler(FileSystemEventHandler):
    def __init__(self, yaml_file: Path, dot_file: Path, svg_file: Path, driver: webdriver.Chrome):
        self.yaml_file = yaml_file
        self.dot_file = dot_file
        self.svg_file = svg_file
        self.driver = driver
        self.graph = {}
        self.build()

    def build(self) -> None:
        """Rebuild the DOT and SVG files and load them in the browser."""
        self.graph = yaml_graph.load_yaml(self.yaml_file)
        self.dot_file.write_text(yaml_graph.to_dot(self.graph))
        subprocess.run([
            "dot",
            "-Tsvg",
            str(self.dot_file),
            "-o",
            str(self.svg_file),
        ], check=True)
        self.driver.get(f"file://{self.svg_file}")

    def on_modified(self, event):
        if Path(event.src_path) == self.yaml_file:
            self.build()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Watch YAML graph and render SVG")
    parser.add_argument("yaml_file", type=Path)
    parser.add_argument("dot_file", type=Path)
    parser.add_argument("svg_file", type=Path)
    args = parser.parse_args()

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
    service = Service(chromedriver_path) if chromedriver_path else None
    driver = webdriver.Chrome(service=service, options=options)

    handler = GraphHandler(args.yaml_file, args.dot_file, args.svg_file, driver)
    observer = Observer()
    observer.schedule(handler, str(args.yaml_file.parent), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    driver.quit()


if __name__ == "__main__":
    main()
