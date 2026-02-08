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

setup(
    name="Scweet",
    version=about["__version__"],
    license="MIT",
    description="Tool for scraping Tweets",
    long_description=read_text(ROOT / "README.md"),
    long_description_content_type="text/markdown",
    author="Yassine AIT JEDDI",
    author_email="aitjeddiyassine@gmail.com",
    url="https://github.com/Altimis/Scweet",
    download_url="https://github.com/Altimis/Scweet/archive/v3.0.tar.gz",
    keywords=[
        "twitter",
        "scraper",
        "python",
        "crawl",
        "following",
        "followers",
        "twitter-scraper",
        "tweets",
    ],
    packages=find_packages(include=("Scweet", "Scweet.*")),
    include_package_data=True,
    install_requires=read_requirements(ROOT / "requirements.txt"),
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
