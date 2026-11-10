"""Read visible English Red/Blue menu choices without selecting a policy."""
from .gen1 import read_party


def menu_options(memory, screen, kind=None, *, party_reader=read_party):
    """Read active menu rows up to their visible right border, excluding the HUD."""
    cursor = screen["cursor"]
    if cursor is None:
        return []
    # The party cursor sits on the HP row, beneath the Pokemon's name.
    # Require the visible names to match the owned party before labeling slots.
    party = party_reader(memory)
    if (party and cursor[0] == 0 and memory[0xCC24] == 1
            and memory[0xCC28] + 1 == len(party)
            and all(screen["rows"][2 * i][3:13].strip() == mon["nick"] for i, mon in enumerate(party))):
        return [{"text": f"{i + 1}: {mon['nick']}", "cursor": [0, 1 + 2 * i]}
                for i, mon in enumerate(party)]
    if kind == "move_menu":
        x, y, count, spacing = 5, 13, 4, 1
    else:
        x, y, count, spacing = memory[0xCC25], memory[0xCC24], memory[0xCC28] + 1, 2
        if kind == "naming" or cursor != (x, y + spacing * memory[0xCC26]) or not 1 <= count <= 8:
            return []
    options = []
    for row in range(y, min(y + spacing * count, 18), spacing):
        end = next((col for col in range(x + 1, 20) if screen["tiles"][row * 20 + col] == 0x7C), 20)
        text = screen["rows"][row][x + 1:end].strip()
        if text:
            options.append({"text": text, "cursor": [x, row]})
    return options

