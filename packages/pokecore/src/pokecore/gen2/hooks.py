"""Gold, Silver and Crystal ROM code addresses for emulator hooks, each verified on the cartridge.

Every finder takes the emulator's ``memory`` (read as ``memory[bank, start:stop]``) and the
consumer's game tables ``data``, and returns the (bank, address) to pass to ``hook_register``.
A finder raises ValueError when the bytes there are not the instructions it expects, so a
hook is never placed in the middle of other code. What a hook does when it fires stays with
the consumer.

ROM labels are read from ``data.symbols`` first, then from :data:`LABELS`, which holds the
labels these finders need from the pinned pret symbol files. Core's memory map carries RAM only.
"""
from __future__ import annotations

# Capture completion: the two places the game finishes adding a caught Pokémon to the party or
# a box. These are local labels, so they are fixed addresses with their first 8 bytes.
HOOKS = {
    'gold': ((3, 27495, '21496ecd5e0ffa04'), (3, 27600, 'cdf13021496ecd5e')),
    'silver': ((3, 27493, '21476ecd5e0ffa04'), (3, 27598, 'cdf13021476ecd5e')),
    'crystal': ((3, 27384, '21f56dcd5710fa08'), (3, 27495, 'cde12f21f56dcd57')),
}
# The first 8 bytes of CountStep, which runs once for every completed step.
STEP_SIGNATURES = {'gold': 'fa42d0a7204a3e24', 'silver': 'fa42d0a7204a3e24', 'crystal': 'fadcc2a7204a3e24'}

_GOLD = {
    'BattleStartMessage': (15, 31899), 'BattleCheckEnemyShininess': (15, 22761),
    'BugContest_SetCaughtContestMon': (3, 26450), 'HatchEggs': (5, 29476), 'CountStep': (37, 27308),
    'BuyMenu': (5, 24299), 'BuyMenuLoop': (5, 24432), 'SelectQuantityToBuy': (9, 20266),
    'BuySell_DisplaySubtotal': (9, 20525), 'wPartyMon1Happiness': (1, 55877), 'wMartItemID': (1, 53251),
    'hProduct': (0, 65461), 'hMoneyTemp': (0, 65477),
}
LABELS = {
    'gold': _GOLD,
    'silver': {**_GOLD, 'BugContest_SetCaughtContestMon': (3, 26448)},
    'crystal': {
        'BattleStartMessage': (15, 31883), 'BattleCheckEnemyShininess': (15, 23161),
        'BugContest_SetCaughtContestMon': (3, 26318), 'HatchEggs': (5, 28528), 'CountStep': (37, 27513),
        'BuyMenu': (5, 23650), 'BuyMenuLoop': (5, 23791), 'SelectQuantityToBuy': (9, 20425),
        'BuySell_DisplaySubtotal': (9, 20689), 'wPartyMon1Happiness': (1, 56570), 'wMartItemID': (1, 53511),
        'hProduct': (0, 65459), 'hMoneyTemp': (0, 65475),
    },
}


def label(data, name):
    """(bank, address) of ``name`` from ``data.symbols``, else from :data:`LABELS`. KeyError if neither has it."""
    if name in data.symbols:
        return tuple(data.symbols[name])
    return LABELS[data.game][name]


def _has(data, name):
    return name in data.symbols or name in LABELS.get(data.game, {})


def _code(memory, bank, address, size):
    return bytes(memory[bank, address:address + size])


def _word(value):
    return bytes((value & 0xFF, value >> 8))


def capture_hooks(memory, data):
    """The (bank, address) of each capture completion in :data:`HOOKS`, verified on the cartridge."""
    for bank, address, signature in HOOKS[data.game]:
        if _code(memory, bank, address, 8).hex() != signature:
            raise ValueError('The Gen II capture completion signature does not match the cartridge')
    return tuple((bank, address) for bank, address, _ in HOOKS[data.game])


def encounter_hook(memory, data):
    """(bank, address) of BattleStartMessage.wild, where every wild battle checks for a shiny.

    The local label is not in the symbol table, so it is found from the ``jr z`` that the routine
    opens with and both instruction sequences are verified on the cartridge.
    """
    bank, address = label(data, 'BattleStartMessage')
    _, mode = label(data, 'wBattleMode')
    _, check = label(data, 'BattleCheckEnemyShininess')
    head = _code(memory, bank, address, 6)
    if head[:5] != b'\xfa' + _word(mode) + b'\x3d\x28':
        raise ValueError('The Gen II wild battle signature does not match the cartridge')
    wild = address + 6 + (head[5] ^ 0x80) - 0x80
    if _code(memory, bank, wild, 4) != b'\xcd' + _word(check) + b'\x30':
        raise ValueError('The Gen II shiny check signature does not match the cartridge')
    return bank, wild


def contest_hook(memory, data):
    """(bank, address) of BugContest_SetCaughtContestMon.firstcatch, where a contest catch is kept.

    A Bug-Catching Contest catch skips the party and box code, so the capture hooks never see it.
    It reaches ``.firstcatch`` as the first catch or once a swap for the held Pokémon is accepted.
    """
    bank, address = label(data, 'BugContest_SetCaughtContestMon')
    _, held = label(data, 'wContestMon')
    head = _code(memory, bank, address, 6)
    if head[:5] != b'\xfa' + _word(held) + b'\xa7\x28':
        raise ValueError('The Gen II contest catch signature does not match the cartridge')
    first = address + 6 + (head[5] ^ 0x80) - 0x80
    if _code(memory, bank, first, 1) != b'\xcd':
        raise ValueError('The Gen II contest catch signature does not match the cartridge')
    return bank, first


def hatch_hook(memory, data):
    """(bank, address) of HatchEggs, which hatches every party Egg whose cycles have run out.

    Every Egg reaches it, the Odd Egg and the gift Eggs included. The opening that sets up its
    party loop is verified on the cartridge.
    """
    bank, address = label(data, 'HatchEggs')
    species, happiness, slot = (_word(label(data, name)[1]) for name in ('wPartySpecies', 'wPartyMon1Happiness',
                                                                          'wCurPartyMon'))
    expected = b'\x11' + species + b'\x21' + happiness + b'\xaf\xea' + slot
    if _code(memory, bank, address, len(expected)) != expected:
        raise ValueError('The Gen II Egg hatch signature does not match the cartridge')
    return bank, address


def step_hook(memory, data):
    """(bank, address) of CountStep, which runs once for every step the player completes.

    It also runs during link sessions. A consumer counting walked steps checks ``wLinkMode``.
    """
    bank, address = label(data, 'CountStep')
    if _code(memory, bank, address, 8).hex() != STEP_SIGNATURES[data.game]:
        raise ValueError('The Gen II walking instruction signature does not match the cartridge')
    return bank, address


def mart_hooks(memory, data):
    """Verified (bank, address) of the Poké Mart BUY menu code, by role.

    - ``opened``: BuyMenu, as a BUY list opens
    - ``priced``: in SelectQuantityToBuy, right after GetItemPrice leaves the unit price in ``de``
    - ``subtotal``: BuySell_DisplaySubtotal, before it shows the total in ``hMoneyTemp``
    - ``bought``: in BuyMenuLoop, once ReceiveItem has put the item in the bag

    Returns {} when BuyMenu or SelectQuantityToBuy is unknown. ``subtotal`` and ``bought`` are
    left out unless BuySell_DisplaySubtotal, BuyMenuLoop, hProduct and hMoneyTemp are all known.
    """
    if not _has(data, 'BuyMenu') or not _has(data, 'SelectQuantityToBuy'):
        return {}
    bank, address = label(data, 'SelectQuantityToBuy')
    # farcall GetItemPrice (ld a, BANK / ld hl, addr / rst FarCall), then ld a, d.
    code = _code(memory, bank, address, 7)
    if code[0] != 0x3E or code[2] != 0x21 or code[5] != 0xCF or code[6] != 0x7A:
        raise ValueError('The Gen II buy price instruction signature does not match the cartridge')
    hooks = {'opened': label(data, 'BuyMenu'), 'priced': (bank, address + 6)}
    if all(_has(data, name) for name in ('BuySell_DisplaySubtotal', 'BuyMenuLoop', 'hProduct', 'hMoneyTemp')):
        bank, address = label(data, 'BuySell_DisplaySubtotal')
        # push hl / ld hl, hMoneyTemp / ldh a, [hProduct + 1]
        money, product = label(data, 'hMoneyTemp')[1], label(data, 'hProduct')[1] + 1
        if _code(memory, bank, address, 6) != b'\xe5\x21' + _word(money) + bytes((0xF0, product & 0xFF)):
            raise ValueError('The Gen II buy subtotal instruction signature does not match the cartridge')
        hooks['subtotal'] = bank, address
        # ReceiveItem succeeded: ld a, [wMartItemID] / ld e, a / ld d, 0, once in BuyMenuLoop.
        bank, address = label(data, 'BuyMenuLoop')
        code = _code(memory, bank, address, 160)
        signature = b'\xfa' + _word(label(data, 'wMartItemID')[1]) + b'\x5f\x16\x00'
        if code.count(signature) != 1:
            raise ValueError('The Gen II purchase instruction signature does not match the cartridge')
        hooks['bought'] = bank, address + code.index(signature)
    return hooks


def bcd(value):
    """``value`` (0 to 999999) as the game's 3-byte big-endian BCD, as money and prices are stored."""
    digits = f'{value:06d}'
    return [int(digits[i]) << 4 | int(digits[i + 1]) for i in range(0, 6, 2)]
