Licensing and distribution boundary

Original pokesim code, generators, documentation, and the neutral default portrait are licensed under the MIT License in LICENSE. This does not grant rights to Pokémon ROMs, graphics, names, or third-party source content. The project is unofficial and unaffiliated with their rights holders.

Release wheels, source archives, and container images do not include the previously bundled sprite PNGs or generated game datasets. Setup generates a local dataset from a verified archive or user-supplied checkout of [pret/pokered](https://github.com/pret/pokered) at revision `a1a22aaf84d1675bcdbaeb194592379d586d838e`. Every output records its source revision, generator version, schema, and checksums. First-time setup can download the pinned reference archive after a user adds a ROM. Prepared adventures run offline. Users are responsible for supplying content they are entitled to use and for any redistribution of generated content.

The previously bundled images came from [PokéAPI/sprites](https://github.com/PokeAPI/sprites/blob/master/LICENCE.txt). Its notice identifies The Pokémon Company as the image copyright holder alongside a CC0 repository statement. Those files have been removed from the current release tree. By default, portraits are extracted locally from the supplied ROM, with a geometric placeholder if unavailable. Settings also offers an explicit optional download of the 151 colored Red/Blue portraits from PokéAPI at revision `bfb75391935310368065096fa08c51e8970bc43e`. Those PNGs and the upstream license notice are stored only in the user data directory. They are not bundled in PokeSim releases or mirrored by this project. This option does not grant rights to the underlying artwork. Users can also supply a local portrait pack in their data directory.

Generation II setup uses pinned [pret/pokegold](https://github.com/pret/pokegold/tree/62388c7204e5d13aa05b4231e220b6760584d1b5) and [pret/pokecrystal](https://github.com/pret/pokecrystal/tree/5beda23ffa505f62e1dad7e3d7c214d1737b3358) references. The generator verifies the reference archives and the SHA-256 of each symbol file, fetched at a separately pinned revision, and records the source revisions and bundle checksums. Generated datasets, reference sources and symbol files remain local user content. The 251 portraits for each supported cartridge are decoded locally from the owner-supplied ROM and are not bundled in releases.

This public repository starts from a reviewed current-source snapshot. It contains no imported development history, bundled game datasets, sprite packs, ROMs, or saves.

PokeSim 0.5.0 runs games on PyBoy RS, a Rust port of PyBoy 2.7.0, installed through PokeSim Core, which is MIT licensed. PokeSim Core and PyBoy RS are installed from GitHub release files, not from PyPI. PyBoy RS is distributed under GNU LGPL version 3 and retains upstream attribution to PyBoy. The original LGPL text and the incorporated GPL text are retained under `licenses/`. The image includes the exact PyBoy RS source archive at `/usr/share/pokesim/sources/pyboy-rs-<version>.tar.gz`, a source manifest, all discovered installed Python dependency notices, and the original application source under `/usr/share/pokesim/source`. The Python extension module is dynamically imported and can be replaced with a compatible modified build. See the dependency modification instructions in `docs/licensing.md`. PokeSim 0.4.x releases used PyBoy 2.7.0 itself and shipped its source archive instead.

Other Python dependencies retain their own licenses. The image records their installed names, versions, license metadata, and notice paths in `/usr/share/pokesim/python-dependencies.json`. Native components and Debian packages retain their installed notices under `/usr/share/doc`. The OCI license label summarizes the application and emulator licenses. It is not an exhaustive license expression for every OS and transitive dependency.

Sources:

- [PyBoy source and LGPL license](https://github.com/Baekalfen/PyBoy/tree/4627b90b878e91faff443b3acd6d4e4be09a4387), the upstream project that PyBoy RS ports
- [PyBoy RS source](https://github.com/afk-sapien/pyboy-rs)
- [GNU GPL version 3](https://www.gnu.org/licenses/gpl-3.0.html)
- [Pinned Red and Blue disassembly source](https://github.com/pret/pokered/tree/a1a22aaf84d1675bcdbaeb194592379d586d838e)
- [Pinned Gold and Silver disassembly source](https://github.com/pret/pokegold/tree/62388c7204e5d13aa05b4231e220b6760584d1b5)
- [Pinned Crystal disassembly source](https://github.com/pret/pokecrystal/tree/5beda23ffa505f62e1dad7e3d7c214d1737b3358)

The optional item icon pack uses the same pinned PokéAPI revision and download
process. It maps 125 Red/Blue item entries to 86 later-generation images, with
TM/HM discs colored by their Generation I move types. Later-game equivalents
include Exp. Share for Exp. All and Dowsing Machine for Itemfinder. Icons and the
source notice are stored only in the owner’s data directory, never in release
packages. The pack can be installed or hidden independently of Pokémon portraits.
