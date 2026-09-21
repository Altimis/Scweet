# Contributing to Scweet

Thanks for taking the time. Contributions are welcome — bug reports, fixes, and well-scoped feature additions.

**A note on issue history:** v5 is a complete rewrite using a fundamentally different approach (direct GraphQL API calls via `curl_cffi`) compared to v1–v3, which used browser automation. All issues filed against prior versions were closed when v4 launched — they simply don't apply to the current codebase.

---

## Reporting a bug

Open an issue using the **Bug Report** template. Include:

- Scweet version (`pip show Scweet`)
- Python version and OS
- Minimal code to reproduce
- Full error output (traceback + any log lines)

---

## Submitting a pull request

1. Fork the repo and create a branch off `master`
2. Install in editable mode, with the test dependencies: `cd Scweet && pip install -e . -r requirements-dev.txt`
3. Run the test suite: `pytest tests/ -v --ignore=tests/test_integration.py`
4. A new method of the client needs its CLI subcommand in the same change, and a new keyword needs its flag. `tests/test_cli_parity.py` fails otherwise.
4. All tests must pass. Add tests for new behaviour.
5. Keep the PR focused — one change per PR is easier to review and merge

---

## What we're looking for

Good contributions:
- Bug fixes with a regression test
- Improvements to error messages or log output
- Documentation corrections
- New structured search filter fields (if they map directly to X's GraphQL parameters)
- Login with username/password credentials (currently only cookie/token auth is supported — a credential-based login flow would be a valuable addition)
- Any other useful functionality that fits the library's scope

Out of scope (for now):
- Alternative HTTP backends (curl_cffi is intentional — TLS fingerprint spoofing matters)
- Browser automation (v5 removed this deliberately)

If you're unsure whether something is in scope, open a discussion in [GitHub Discussions](https://github.com/Altimis/Scweet/discussions) before writing code.

## Working on the documentation

`DOCUMENTATION.md`, `CHANGELOG.md` and `CONTRIBUTING.md` at the root of the repository hold the text. The site
copies them before each build, so you edit the file at the root and never a copy.

```bash
make docs-install   # install mkdocs and the theme
make docs-serve     # read the site at http://127.0.0.1:8000/Scweet/ while you edit
make docs-check     # build the site, then verify it
```

`make docs-check` answers three questions: does every page exist, does each page hold every section of its
source file, and does every internal link reach a page. The same file runs in the workflow, so a result on
your machine and a result in CI agree.

A pull request builds the site and keeps it as an artifact for 14 days. Nothing reaches the public site until
a maintainer starts the deploy.
