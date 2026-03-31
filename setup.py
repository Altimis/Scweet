#!/usr/bin/env python3
from __future__ import annotations

import io
import os
from pathlib import Path

from setuptools import find_packages, setup


ROOT = Path(__file__).resolve().parent


def read_text(path: Path) -> str:
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def read_requirements(path: Path) -> list[str]:
    reqs: list[str] = []
    for raw in read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Keep environment markers/version pins; drop inline comments.
        reqs.append(line.split("#", 1)[0].strip())
    return reqs


about: dict[str, str] = {}
exec(read_text(ROOT / "Scweet" / "__version__.py"), about)
version = about["__version__"]


def read_text_optional(path: Path) -> str | None:
    try:
        return read_text(path)
    except FileNotFoundError:
        return None


long_description = (
    read_text_optional(ROOT / "README.md")
    or read_text_optional(ROOT / "DOCUMENTATION.md")
    or ""
)

setup(
    name="Scweet",
    version=version,
    license="MIT",
    description="Scrape tweets, profiles, followers and more from Twitter/X — no API key needed",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Yassine AIT JEDDI",
    author_email="aitjeddiyassine@gmail.com",
    url="https://github.com/Altimis/Scweet",
    download_url=f"https://github.com/Altimis/Scweet/archive/v{version}.tar.gz",
    keywords=[
        "twitter",
        "x",
        "scraper",
        "twitter-scraper",
        "x-scraper",
        "tweets",
        "tweet-search",
        "twitter-search",
        "followers",
        "following",
        "twitter-api-alternative",
        "graphql",
        "web-scraping",
        "social-media",
        "data-collection",
        "python",
    ],
    packages=find_packages(include=("Scweet", "Scweet.*")),
    include_package_data=True,
    package_data={"Scweet": ["default_manifest.json"]},
    install_requires=read_requirements(ROOT / "requirements.txt"),
    entry_points={
        "console_scripts": ["scweet=Scweet.cli:main"],
    },
    python_requires=">=3.9",
    license_files=[],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
