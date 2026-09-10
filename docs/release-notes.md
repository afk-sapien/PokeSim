PokeSim 0.2.0rc4 is an experimental self-hosting beta for Linux amd64.

The browser viewer now downloads and decodes one game image at a time, capped at 10 display frames per second independently of game speed. It keeps the last good image during failed or invalid responses, retries automatically, and stops downloading frames in hidden tabs. This avoids depending on the browser's long-lived MJPEG display connection. The `/stream` endpoint remains available for other clients.

Four JavaScript controller tests and Chromium and Firefox checks cover slow responses, invalid images, timeouts, and recovery. The 200 Python tests pass. Emulator behavior, game speed, save formats, and health thresholds are unchanged from 0.2.0rc3.

Supply your own supported Pokémon Red ROM and prepare game data locally using the README. Pokémon ROMs, sprites, and generated game datasets are excluded. PyBoy includes its own small demo ROM, which is not a Pokémon game. Public downloads require no GitHub account or registry login.

This is still an early beta. The fresh 48-hour validation continues on the unchanged 0.2.0rc3 backend image and is not a completed pass. That test's streaming measurements cover MJPEG, not this new browser viewer. The policy can get stuck or make poor choices. ARM, Blue, and ROM hacks are not validated release targets.

See [installation instructions](https://github.com/afk-sapien/PokeSim/blob/main/README.md) and [current validation results](https://github.com/afk-sapien/PokeSim/blob/main/RELEASE_STATUS.md). Use GitHub issues for feedback and private vulnerability reporting for security problems.
