#!/usr/bin/env python3
"""Check the Pages source, and optionally verify downloaded release assets."""

import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs"
RELEASES = "https://github.com/varyagnord/usb-most-downloads/releases"


class Page(HTMLParser):
    def __init__(self, filename):
        super().__init__()
        self.filename = filename
        self.ids = set()
        self.links = set()
        self.references = []
        self.feed(filename.read_text(encoding="utf-8"))
        self.close()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        identifier = attributes.get("id")
        if identifier:
            require(identifier not in self.ids, f"{self.filename.name}: duplicate id {identifier}")
            self.ids.add(identifier)
        for attribute in ("href", "src"):
            reference = attributes.get(attribute)
            if reference:
                self.references.append(reference)
        if tag == "a" and attributes.get("href"):
            self.links.add(attributes["href"])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_site(manifest):
    pages = {file.resolve(): Page(file) for file in SITE.glob("*.html")}
    for filename in ("index.html", "offer.html", "privacy.html"):
        require(SITE / filename in pages, f"Missing page: {filename}")
    for path, page in pages.items():
        for reference in page.references:
            url = urlsplit(reference)
            if url.scheme or url.netloc:
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if target.is_dir():
                target /= "index.html"
            require(target.is_relative_to(SITE) and target.is_file(),
                    f"{path.name}: broken local link {reference}")
            if url.fragment and target in pages:
                require(unquote(url.fragment) in pages[target].ids,
                        f"{path.name}: broken anchor {reference}")

    home = pages[SITE / "index.html"]
    require("payment-return" in home.ids, "Checkout return anchor is missing")
    prefix = f"{RELEASES}/download/{release_tag(manifest)}/"
    package_names = {package["name"] for package in manifest["packages"]}
    require(len(package_names) >= 2 and len(package_names) == len(manifest["packages"]),
            "Expected distinct receiver packages")
    require({link.removeprefix(prefix) for link in home.links if link.startswith(prefix)}
            == package_names | {"SHA256SUMS"}, "Download links do not match receivers.json")
    print(f"Verified {len(pages)} HTML pages, local links, and release references.")


def release_tag(manifest):
    return f"v{manifest['version']}-vc{manifest['androidVersionCode']}"


def check_assets(manifest, directory):
    published = {}
    for line in (directory / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, filename = line.split(maxsplit=1)
        published[filename.removeprefix("*")] = digest
    for package in manifest["packages"]:
        filename = package["name"]
        require(Path(filename).name == filename, f"Invalid release filename: {filename}")
        asset = directory / filename
        require(asset.stat().st_size == package["bytes"], f"{filename}: size mismatch")
        require(published.get(filename) == package["sha256"], f"{filename}: published SHA-256 mismatch")
        with asset.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        require(actual == package["sha256"], f"{filename}: content SHA-256 mismatch")
        print(f"Verified release asset {filename}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tag", action="store_true")
    parser.add_argument("--assets", type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "receivers.json").read_text(encoding="utf-8"))
    if args.release_tag:
        print(release_tag(manifest))
        return
    check_site(manifest)
    if args.assets:
        check_assets(manifest, args.assets)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
