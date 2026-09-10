Using and modifying the release

Original application code is MIT licensed. Game content is supplied and prepared locally. Release artifacts exclude the former game-data JSON and sprite PNGs. Do not include your ROM, local source checkout, generated data, screenshots, or saves when redistributing a release artifact.

This public repository starts with a reviewed source snapshot. Earlier development history is not included.

To obtain the application source, exact PyBoy source, and dependency notices from an image:

```sh
docker create --name pokesim-notices pokesim:0.2.0rc4
docker cp pokesim-notices:/usr/share/pokesim ./pokesim-notices
docker rm pokesim-notices
```

The copy includes the original application source, lockfile, PyBoy source archive and hash manifest, dependency inventory, and license files. Installed dependency notice files are also retained in the Python environment. Debian's native component notices remain under `/usr/share/doc`.

You may modify the application and replace the dynamically imported PyBoy library with an interface-compatible version. Rebuild the image from source with your revised dependency selection. Preserve applicable notices and review any new dependency licenses. Save-state compatibility with a modified emulator is your responsibility. This project imposes no additional restriction on reverse engineering to debug those modifications.

A rebuild using an unpacked modified PyBoy source can install it into `/app/.venv` in a derived image as root during the build, then restore `USER 10001:10001`. The runtime does not perform signature checks or prevent replacement of that library. The original source archive remains available so modifications can be compared with the distributed version.

The package and image checks cover the distribution boundary, source provenance, and notice inclusion. They are not a claim that any user-supplied game content is freely redistributable.
