Contributing to pokesim

This is an experimental self-hosting project. Original code is MIT licensed. Release artifacts exclude user-supplied game content. Keep changes focused and include the reason, affected behavior, and validation in each pull request.

Prepare the pinned reference checkout described in the README, then install the locked environment:

```sh
uv sync --locked --extra dev
uv run --locked python -m pokesim.prepare_data .reference/pokered
uv run --locked pytest --ignore=tests/test_rom.py -q
node --check pokesim/web/static/app.js
uv build
python tools/check_package.py
```

Run ROM-dependent tests privately with your own supported ROM using `uv run --locked pytest tests/test_rom.py -q`. Never add ROM files or cartridge saves to source control, CI artifacts, or issue attachments. Recorded policy scenarios should use synthetic state or private local checkpoints.

Changes to save formats need a format version, upgrade and rollback notes, and a recovery test. PyBoy is pinned deliberately. Test existing checkpoints before upgrading it. Use `uv lock --upgrade-package PACKAGE` for an intentional dependency update, then rerun the affected checks and container build.

For generated game data, retain the upstream revision and generator command. See the detailed guide and third-party notices. Do not replace generated data from an unidentified source.

Bug reports should include the release or commit, operating system and CPU architecture, ROM hash, sanitized relevant settings, logs, and reproduction steps. Do not include tokens, ROMs, or private save files. The maintainer can explain a suitable private reproduction process when needed.
