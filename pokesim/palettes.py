"""Whole-screen DMG colors that preserve existing checkpoint hardware mode.

The twelve presets use the background colors of the GBC startup choices.
Sprite-specific GBC palettes require separate renderer support.
Color data: https://github.com/LIJI32/SameBoy/blob/master/BootROMs/cgb_boot.asm
"""


def rgb(value):
    channels = [(value >> shift) & 31 for shift in (0, 5, 10)]
    red, green, blue = [(part << 3) | (part >> 2) for part in channels]
    return red << 16 | green << 8 | blue


PALETTES = {'original': (0xffffff, 0x999999, 0x555555, 0x000000)}
PALETTES['brown'] = tuple(map(rgb, (32767, 12991, 208, 0)))
PALETTES['red'] = tuple(map(rgb, (32767, 16927, 7410, 0)))
PALETTES['dark-brown'] = tuple(map(rgb, (25503, 17017, 5552, 1227)))
PALETTES['pastel'] = tuple(map(rgb, (21503, 19039, 32338, 0)))
PALETTES['orange'] = tuple(map(rgb, (32767, 1023, 31, 0)))
PALETTES['yellow'] = tuple(map(rgb, (32767, 1023, 303, 0)))
PALETTES['blue'] = tuple(map(rgb, (32767, 32396, 31744, 0)))
PALETTES['dark-blue'] = tuple(map(rgb, (32767, 28209, 17738, 0)))
PALETTES['gray'] = tuple(map(rgb, (32767, 21140, 10570, 0)))
PALETTES['green'] = tuple(map(rgb, (32767, 1002, 287, 0)))
PALETTES['dark-green'] = tuple(map(rgb, (32767, 7151, 24960, 0)))
PALETTES['reverse'] = tuple(map(rgb, (0, 16896, 895, 32767)))


def validate_palette(value):
    if not isinstance(value, str) or value not in PALETTES:
        raise ValueError('Choose a listed screen palette')
    return value


def _lookup(colors):
    table = []
    for shift in (16, 8, 0):
        channel = list(range(256))
        for source, target in zip(PALETTES['original'], colors):
            channel[source & 255] = (target >> shift) & 255
        table.extend(channel)
    return table


LOOKUPS = {name: _lookup(colors) for name, colors in PALETTES.items()}


def recolor(image, palette):
    """Map the emulator's fixed grayscale output without touching game state."""
    return image if palette == 'original' else image.point(LOOKUPS[palette])
