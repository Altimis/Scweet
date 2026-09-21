# The commands for a contributor. Run `make help` for the list.
#
# `PYTHON` selects the interpreter. A virtual environment holds the tools that build the site, and a `mkdocs`
# of the system usually holds no theme, so the commands call the interpreter and never the command `mkdocs`.
PYTHON ?= python3

.PHONY: help test docs-install docs docs-serve docs-check

help:  ## show this list
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

test:  ## run the tests
	$(PYTHON) -m pytest tests/ -q

docs-install:  ## install the tools that build the site
	$(PYTHON) -m pip install -r docs-requirements.txt

docs:  ## build the site into site/, and stop for a broken link
	$(PYTHON) -m mkdocs build --strict

docs-serve:  ## read the site at http://127.0.0.1:8000/Scweet/ while you edit it
	$(PYTHON) -m mkdocs serve

docs-check: docs  ## build the site, then prove that it holds every section of each document
	$(PYTHON) scripts/check_docs_site.py
