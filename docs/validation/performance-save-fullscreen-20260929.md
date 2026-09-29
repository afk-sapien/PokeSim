# Rendering, cartridge exports, and fullscreen

## Rendering measurement

An isolated Blue checkpoint was advanced by 24,000 frames in chunks of four on
the home server. Two baseline runs rendered every chunk. Two comparison runs
rendered only chunks crossing a 30-frame observation boundary.

| Run | Baseline CPU seconds | Reduced rendering CPU seconds |
| --- | ---: | ---: |
| 1 | 2.731 | 2.308 |
| 2 | 2.802 | 2.123 |
| Mean | 2.767 | 2.216 |

The measured reduction is 19.9% for this emulation loop. This is not a whole-app
benchmark. At Max pace, the application can still saturate a core while making
more progress per second. No simulation speed settings were changed.

All four runs ended with identical WRAM and rendered screen bytes, checked by
SHA-256. Frame publishing tests also check that every observation and every
published frame has a freshly rendered image, including partial tick chunks.

## Cartridge exports

Private Red and Blue checkpoints each produced a 32,768-byte cartridge save.
Each file was booted from scratch, selecting Continue and checking the party's
raw records, all PC box records, Pokédex, badges, money, bag, trainer names, and
location against the exported checkpoint. The final checks took approximately
0.25 seconds per cartridge on the server. Screen transitions and unsupported
menus correctly refused export. The live games were not modified.

The optional `test_real_cartridge_export_restarts_with_current_collection` test
can repeat this with `POKESIM_EXPORT_ROM` and `POKESIM_EXPORT_CHECKPOINT` pointing
to private local files. Do not commit those files.

## Browser checks

Chromium checks cover fullscreen at 1920×1080, 900×700, and 390×844. The original
grid let the picture exceed the fullscreen container's height. The fix uses a
bounded flex layout with aspect-preserving image fitting, black bars, and no
reserved scrollbar gutter.

Nine live-page browser tests passed, including normal layouts from 320 to 1280
pixels wide, viewer-only controls, fullscreen entry and exit, a `.sav` download,
and a recoverable export error. Export endpoint tests cover current-checkpoint
selection, safe filenames, private caching, view-only refusal, and failures
without downloadable save bytes.
