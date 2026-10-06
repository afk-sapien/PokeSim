"""Decode Gen II front portraits from the owner's verified cartridge."""
import io
from pathlib import Path

from PIL import Image

from .data import GameData


def offset(bank, address):
    return bank * 0x4000 + (address & 0x3FFF) if bank else address


def decompress(raw, start, limit=65536):
    result = bytearray()
    position = start
    while position < len(raw):
        command = raw[position]
        position += 1
        if command == 255:
            return bytes(result)
        kind = command >> 5
        length = (command & 31) + 1
        if kind == 7:
            kind = (command >> 2) & 7
            length = ((command & 3) << 8 | raw[position]) + 1
            position += 1
        if len(result) + length > limit:
            raise ValueError('Gen II sprite expands beyond its size limit')
        if kind == 0:
            result.extend(raw[position:position + length])
            position += length
        elif kind == 1:
            result.extend([raw[position]] * length)
            position += 1
        elif kind == 2:
            pair = raw[position:position + 2]
            result.extend(pair[index & 1] for index in range(length))
            position += 2
        elif kind == 3:
            result.extend(bytes(length))
        else:
            address = raw[position]
            position += 1
            if address & 128:
                address = len(result) - (address & 127) - 1
            else:
                address = (address << 8) | raw[position]
                position += 1
            for _ in range(length):
                if not 0 <= address < len(result):
                    raise ValueError('Invalid Gen II sprite back reference')
                value = result[address]
                if kind == 5:
                    value = int(f'{value:08b}'[::-1], 2)
                result.append(value)
                address += -1 if kind == 6 else 1
    raise ValueError('Truncated Gen II sprite')


def portrait(raw, data, dex, *, shiny=False):
    base = offset(*data.symbols['BaseData']) + (dex - 1) * 32
    dimensions = raw[base + 17]
    width, height = dimensions >> 4, dimensions & 15
    if not 1 <= width <= 7 or not 1 <= height <= 7:
        raise ValueError('Invalid Gen II portrait dimensions')
    picture = decompress(raw, offset(*data.symbols[data.species[dex]['front_symbol']]))
    palette_at = offset(*data.symbols['PokemonPalettes']) + dex * 8 + (4 if shiny else 0)
    palette = [(255, 255, 255, 0)]
    for index in (0, 2):
        color = int.from_bytes(raw[palette_at + index:palette_at + index + 2], 'little')
        palette.append(tuple(((color >> shift) & 31) * 255 // 31 for shift in (0, 5, 10)) + (255,))
    palette.append((0, 0, 0, 255))
    image = Image.new('RGBA', (width * 8, height * 8))
    for tx in range(width):
        for ty in range(height):
            tile = (tx * height + ty) * 16
            for y in range(8):
                low, high = picture[tile + y * 2:tile + y * 2 + 2]
                for x in range(8):
                    bit = 7 - x
                    image.putpixel((tx * 8 + x, ty * 8 + y), palette[(low >> bit & 1) | ((high >> bit & 1) << 1)])
    canvas = Image.new('RGBA', (56, 56))
    canvas.alpha_composite(image, ((56 - image.width) // 2, 56 - image.height))
    output = io.BytesIO()
    canvas.save(output, format='PNG')
    return output.getvalue()


def install(raw, root, destination, game):
    from ..checkpoints import CheckpointStore
    data = GameData.load(root, game)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for dex in range(1, 252):
        CheckpointStore.atomic_write(destination / f'{dex}.png', portrait(raw, data, dex))
    return 251
