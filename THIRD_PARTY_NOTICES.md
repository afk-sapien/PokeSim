Licensing and distribution boundary

Original pokesim code, generators, documentation, and the neutral default portrait are licensed under the MIT License in LICENSE. This does not grant rights to Pokémon ROMs, graphics, names, or third-party source content. The project is unofficial and unaffiliated with their rights holders.

Release wheels, source archives, and container images do not include the previously bundled sprite PNGs or generated game datasets. Setup generates a local dataset from a user-supplied checkout of [pret/pokered](https://github.com/pret/pokered) at revision `a1a22aaf84d1675bcdbaeb194592379d586d838e`. Every output records its source revision, generator version, schema, and checksums. No source checkout is downloaded by the running app. Users are responsible for supplying content they are entitled to use and for any redistribution of generated content.

The previously bundled images came from [PokéAPI/sprites](https://github.com/PokeAPI/sprites/blob/master/LICENCE.txt). Its notice identifies The Pokémon Company as the image copyright holder alongside a CC0 repository statement. Those files have been removed from the current release tree. Users can supply a local portrait pack in their data directory. The default portrait contains only an original geometric design and a numeric identifier.

This public repository starts from a reviewed current-source snapshot. It contains no imported development history, bundled game datasets, sprite packs, ROMs, or saves.

PyBoy 2.7.0 is distributed under GNU LGPL version 3. The original LGPL text and the incorporated GPL text are retained under `licenses/`. The image includes its exact hash-verified PyPI source archive at `/usr/share/pokesim/sources/pyboy-2.7.0.tar.gz`, a source manifest, all discovered installed Python dependency notices, and the original application source under `/usr/share/pokesim/source`. The Python library is dynamically imported and can be replaced with a compatible modified build. See the dependency modification instructions in `docs/licensing.md`.

Other Python dependencies retain their own licenses. The image records their installed names, versions, license metadata, and notice paths in `/usr/share/pokesim/python-dependencies.json`. Native components and Debian packages retain their installed notices under `/usr/share/doc`. The OCI license label summarizes the application and emulator licenses. It is not an exhaustive license expression for every OS and transitive dependency.

Sources:

- [PyBoy source and LGPL license](https://github.com/Baekalfen/PyBoy/tree/4627b90b878e91faff443b3acd6d4e4be09a4387)
- [GNU GPL version 3](https://www.gnu.org/licenses/gpl-3.0.html)
- [Pinned disassembly source](https://github.com/pret/pokered/tree/a1a22aaf84d1675bcdbaeb194592379d586d838e)
