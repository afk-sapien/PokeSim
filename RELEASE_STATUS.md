# Release preparation: 0.3.1

This is a repair release over 0.3.0. It came out of a review of that source rather than new
gameplay work, and the two findings worth the release are things every new adventure did to
itself in its first three minutes.

A Pokémon on the nickname screen is counted by the cartridge before its 44-byte struct is
written, so for 27 seconds it read as species 0 with no HP. That looked like a team that had
fainted, so a new adventure recorded two "Blacked out!" entries, sent the matching
notifications, and showed the new partner as `No Mon`, level 0, fainted. Separately, the memory
the Pokédex flags will later occupy holds other values in Oak's lab before the Pokédex exists,
which read as owning four starters at once and put all four in the journal. Both are fixed by
not trusting memory the cartridge has not made meaningful yet, and both were verified against
Red on a scratch library: the opening journal goes from seven entries to one.

The post-trade verification — party, badges, bag, box counts, untraded slots, and the arriving
Pokémon down to its struct and original trainer, plus the checksum compared before adoption —
was written as bare `assert` statements, which `python -O` removes. Nothing here sets
`PYTHONOPTIMIZE`, so it never fired, but those checks now raise.

The README screenshots were retaken. The old set showed empty squares where portraits go, which
is not what the application renders; a missing portrait has drawn a numbered placeholder since
0.2.0.

There is no database change, no policy state change, and no migration. Existing checkpoints
resume untouched. Adventures that already recorded the false opening entries keep them: nothing
rewrites a journal that has already been written.

The release targets are a Python wheel and source archive, plus a Linux amd64 Docker image and
Compose configuration. The `pokesim-desktop` Python command opens the Library in your browser.
Standalone executable bundles are no longer built.

Publication is gated on Python and browser regression checks, clean package identities, Docker
lifecycle checks, and isolated native Python installations on Windows x86-64, Intel macOS, Apple
Silicon, and Linux x86-64 and ARM64. The workflow uploads a draft, verifies every uploaded
checksum, and only then publishes it.

Publishing this release does not upgrade a running application: change the image or package
where it is deployed. See [release notes](docs/release-notes.md),
[desktop installation](docs/desktop.md), and [self-hosting](docs/self-hosting.md).

Gameplay remains an experimental beta. Synthetic tests and demonstration-ROM worker checks do
not establish uninterrupted multi-day cartridge gameplay on all platforms. Existing private
gameplay and cable-trading receipts retain their original scope. Back up the complete library
before upgrading. Import legacy adventures into a new application folder with the old
application stopped.

Two limits found during the same review are not addressed here. Event screenshots are captured
without checking that the frame is not blank, so a milestone caught during a fade can be a
solid white or solid black card in the journal — one is visible in the shipped Journal image.
The project also has no linter, formatter or type checker, and 15% of its functions carry return
annotations.

[Historical release and deployment records](docs/history/releases-through-rc31.md) remain
available for earlier version receipts and their limitations.
