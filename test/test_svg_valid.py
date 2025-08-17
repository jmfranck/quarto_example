from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import sys
import shutil
import urllib.request
import zipfile

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

sys.path.append(str(Path(__file__).resolve().parents[1]))
import yaml_graph


def test_generated_svg_is_valid(tmp_path):
    root = Path(__file__).resolve().parents[1]
    yaml_path = root / "graph" / "graph.yaml"
    dot_path = tmp_path / "graph.dot"
    svg_path = tmp_path / "graph.svg"

    yaml_graph.write_dot_from_yaml(yaml_path, dot_path)
    subprocess.run([
        "dot", "-Tsvg", str(dot_path), "-o", str(svg_path)
    ], check=True)

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    chrome_version = subprocess.check_output(["google-chrome", "--version"]).decode().split()[2]
    url = f"https://storage.googleapis.com/chrome-for-testing-public/{chrome_version}/linux64/chromedriver-linux64.zip"
    zip_path = tmp_path / "chromedriver.zip"
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp_path)
    driver_path = tmp_path / "chromedriver-linux64" / "chromedriver"
    driver_path.chmod(0o755)
    service = Service(str(driver_path))
    driver = webdriver.Chrome(service=service, options=options)
    try:
        driver.get(f"file://{svg_path}")
        assert "<svg" in driver.page_source
    finally:
        driver.quit()

    root_tag = ET.parse(svg_path).getroot().tag
    assert "svg" in root_tag
