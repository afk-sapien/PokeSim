# Repository consolidation validation, September 18, 2026

The rc32 candidate combines the latest Adventure Library, gameplay and cable
trading work with DV ratings, PC filters, collection milestones, extracted
controllers, and release preparation. Eight dependency PRs were squash merged
before consolidating the app. The earlier branches and unfinished worktrees
were preserved in an external recovery archive before branch removal.

Local checks on the combined source:

- 1,115 Python tests passed, including 13 real Chromium scenarios. 31 optional
  tests were skipped. The private ROM suite was excluded from this run.
- 67 JavaScript tests passed across nine files, including adventure-scoped PC
  navigation, Elite Four sorting, DV ratings, catch counts, and trading views.
- Markdown destinations and GitHub Actions definitions passed their checkers.
- Wheel and source packages passed required-resource and private-file exclusions.
- A fresh installed wheel launched the Library outside the checkout, rejected
  unprotected writes, reopened an existing application, and shut down cleanly.
- Two installed workers used independent save directories and private credentials,
  then saved and exited when their parent pipes closed.
- The Python 3.14 container built successfully. Disposable Compose checks passed
  reference setup, offline retry, legacy save and resume, Library startup, static
  assets, session creation, graceful shutdown, and restart.

Hosted CI adds Python 3.11, 3.12, and 3.14 regression jobs, optional Numba checks,
and isolated native Python installations on Windows x86-64, Intel macOS, Apple
Silicon, and Linux x86-64 and ARM64. Consult the checks on the consolidated main
commit for their final outcomes. These tests use synthetic states and PyBoy's
own demonstration ROM. They do not establish uninterrupted multi-day cartridge
play or requalify private Pokémon gameplay on every platform.

No version tag, downloadable release, or running deployment was published or
upgraded as part of this repository cleanup.
