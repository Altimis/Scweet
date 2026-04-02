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
2. Install in editable mode: `cd Scweet && pip install -e .`
3. Run the test suite: `pytest tests/ -v --ignore=tests/test_integration.py`
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
