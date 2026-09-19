# Validation records

These JSON files preserve sanitized test results, copied-save comparisons, monitoring
observations, and deployment receipts. They are historical evidence, not live status.
ROMs, cartridge saves, private checkpoints, and tokens belong outside the repository.

## Finding evidence

- `release-*.json`: deployed revisions, backups, and startup checks.
- `monitor-*.json`: timestamped observations of the documented installation.
- `public-install-*.json`: checks of the specified public installation artifacts.
- Other descriptive filenames: focused experiments and regression comparisons.

Start with [release status](../../RELEASE_STATUS.md) for the latest recorded deployment
or the [archived release log](../history/release-status.md) for earlier context.
A passing targeted comparison does not demonstrate a complete autonomous campaign or
uninterrupted endurance. Review each record's revision, inputs, duration, and limitations.

Preserve existing filenames when adding new evidence. Link new records from the owning
guide or changelog instead of copying their full narrative into multiple documents.
