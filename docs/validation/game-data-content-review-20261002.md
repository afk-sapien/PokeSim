# Generated game data review

Reviewed October 2, 2026, against the local 0.4.17 candidate generators.

## Conclusion

The three generated files are technical reference data, not a copy of the game
program or its audiovisual assets. They contain no sprite pixels, music, game
dialogue, Pokédex prose, or executable game scripts. A full ROM parsing rewrite
is not justified by this content review alone.

A compact metadata bundle is technically feasible. This review does not establish
permission to redistribute the entire bundle or prove that moving it into our
releases would reduce legal risk. The map geometry and the provenance of the
complete compilation remain the specific questions, rather than every numeric
constant being treated as suspect.

## Method and scope

Ran the current generators against the existing local reference tree identified
as revision `a1a22aaf84d1675bcdbaeb194592379d586d838e`. Traced every source file
read, inspected the resulting JSON fields and string values, and followed the
navigation and collection consumers. Validated every navigation grid against
its declared dimensions and checked that its entries are integer tile IDs.

No ROMs or saves were read. No reference archive was downloaded during this
review. The local source tree was not independently reverified against the
published archive hash. This is a content review of fresh generator output,
not a complete audit of historical releases, Git history, Core, or code licensing.

[Machine-readable counts and output hashes](game-data-content-review-20261002.json)
record the measured output. The generated game datasets remain outside the repo.

## What the files contain

| File | Size | Contents | Recommendation |
| --- | ---: | --- | --- |
| `tables.json` | 27,959 bytes | Display names and IDs for maps, species, items and trainer classes, 165 move summaries, badge and leader names | Retain this useful reference layer. No dialogue or descriptions need removing. |
| `collection.json` | 94,687 bytes | 686 acquisition records per version, 72 evolution records, 322 trainer interaction and event references | Retain the collection model. These describe where and how the planner can acquire Pokémon, not scripts that execute the game. |
| `strategy.json` | 510,485 bytes | Stats for 151 species, 165 moves, 82 type-matchup entries, 507 event identifiers, shop inventories, navigation and puzzle data | Keep mechanical constants and routing data conceptually separate from map geometry when evaluating distribution. |

Total: 633,131 bytes, about 618 KiB. Concatenating and gzip-compressing the three
files produces 78,858 bytes, about 77 KiB. This measures possible download size,
not a proposed archive format or a legal threshold.

## What the map data actually is

The `world` section covers 223 maps and occupies 434,041 bytes. It includes:

- 94,940 movement-grid cells containing tile identifiers, not pixel images.
- 805 exits, 78 connections between maps, and passability rules.
- 918 object positions and 201 background interaction positions.
- Puzzle-related records including 19 locked doors and 71 forced movement paths.
- Encounter summaries and identifiers used to target interactions.

The generator reads `.blk` block arrangements and `.bst` tile-ID arrangements.
It selects a movement-related tile ID for each walking cell. It does not retain
the complete graphical block composition or the pixel artwork required to render
the original maps. The output preserves useful spatial structure, so describing
it as only a list of map names would also be inaccurate.

Navigation uses this data for pathfinding, collision checks, exits, water, ledges,
trees, moving obstacles, and puzzle gates. Removing it without a replacement
would break gameplay. Converting it to a graph would change the representation,
but would not by itself resolve questions about the source of the geometry.

## Why some fields look like text or sprites

`backgrounds`, `objects`, and collection `fragment` fields retain symbolic
interaction labels. An identifier such as `TEXT_...` identifies the target NPC
or sign. It does not contain what that NPC says. Object sprite fields identify
an object category, not its image bytes.

All strings in `strategy.json` and `collection.json` are single whitespace-delimited
tokens, including identifiers, source URL and revision. The longest display string
in `tables.json` is 29 characters. None of the files contains a newline within
a string value. These measurements corroborate the generator inspection rather
than serving as a general-purpose copyright detector.

## What setup downloads versus what it keeps

The inspected reference tree contains 2,875 files, including 668 PNGs and source
directories for dialogue, audio, and game code. The generators read 1,099 files:
898 assembly-text files, 182 map block files, and 19 tile-ID block files.
They read no PNGs, no pixel-format `.1bpp` or `.2bpp` files, and no files under
the dialogue `text/` or `audio/` directories.

They do read map scripts to derive trainer event relationships, gate coordinates,
and movement endpoints. Script instructions are parsed rather than copied into
the generated JSON. After preparation, the temporary extracted reference tree is
removed. The three JSON files and their verification manifest remain locally.

Runtime portraits already come from the user's ROM through
[`sprites.py`](../../pokesim/sprites.py) and
[`Assets.install_portraits`](../../pokesim/app/assets.py).

## Current distribution boundary

Packaging excludes `pokesim/data/` and standalone sprite packs.
[`check_package.py`](../../tools/check_package.py) checks those paths and rejects
ROM and save-file extensions. The generators themselves are shipped.
README gameplay screenshots are included in the repository and source archives.
They are a separate artwork consideration, not evidence that the generated JSON
contains images. This review inspected packaging rules, not every old artifact.

## Recommended next decision

Keep the current architecture and ROM-based portrait extraction. There is no
dialogue corpus to strip out and no reason to regenerate all functional IDs.

If replacing the source download, preserve the existing three-file API and
create a versioned metadata distribution with checksums and honest provenance.
First separate the mechanical and lookup fields from the spatial and puzzle
fields, then decide explicitly whether the latter will be redistributed.
Reviewing those fields is a smaller task than writing a complete cartridge parser.

Do not describe a bundled copy of today's entire output as legally cleared,
independently authored, or necessarily safer than the existing download.
Simply moving it to our release assets changes who distributes it. There is also
no technical need to alter preparation or force a Core release for this review.

No application behavior, downloader, caches, saves, dependencies, or release
publication was changed by this review.

## Legal context and limits

US copyright guidance distinguishes protected expression from ideas, algorithms,
systems and methods. That supports a field-level review, not treating every
constant as protected or declaring an entire derived collection unprotected.
See the [Copyright Office's computer-program guidance](https://www.copyright.gov/register/tx-programs.html).

Fair use is case-specific. The absence of images and dialogue is relevant to what
we distribute, but does not settle every question about a compilation or a game
layout. See the [Copyright Office's fair-use guidance](https://www.copyright.gov/fair-use/more-info.html).
These findings are an engineering inventory and recommendation, not legal clearance.
