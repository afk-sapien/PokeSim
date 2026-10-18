"""Fair wild DVs for Red, Blue and Yellow, an optional adventure setting that is off by default.

The cartridge draws wild DVs from two back-to-back Random calls right after the encounter
check passes. That check only passes in a narrow range, so the two bytes are correlated and a
wild grass, cave or water encounter can never be shiny or perfect. With the setting on, the
shiny tracker's hook at LoadEnemyMonData.storeDVs replaces both stored bytes before CalcStats
reads them.

The bytes are an HMAC of the whole WRAM at that moment, keyed by a per-adventure secret kept
outside checkpoints, as League rewards keep their seed. Every distinct encounter gets uniform
random DVs, and the same saved moment always gives the same Pokémon, as it does on the cartridge.
"""
import hashlib
import hmac
import json
import secrets

from . import config

KEY = 'fair-wild-dvs-v1'
# Red addresses. A Yellow emulator translates them through its memory view.
DVS = 0xcff1
IN_BATTLE, BATTLE_TYPE, ENEMY_STATUS3, LINK_STATE = 0xd057, 0xd05a, 0xd069, 0xd12b
WILD, OLD_MAN, TRANSFORMED = 1, 1, 8


def enabled():
    return getattr(config, 'FAIR_WILD_DVS', False) is True


def secret(store):
    """Return this adventure's key, creating it once."""
    with store.lock, store.db:
        row = store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
        value = json.loads(row[0]) if row else {}
        if not value.get('seed'):
            value['seed'] = secrets.token_hex(32)
            store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (KEY, json.dumps(value)))
    return bytes.fromhex(value['seed'])


def wild(mem):
    """Whether storeDVs was reached on the random wild path.

    Trainer Pokémon have fixed DVs, Transform restores the original DVs through the same
    instruction, cable battles load the partner's party, and the old man's Weedle is a tutorial.
    """
    return (mem[IN_BATTLE] == WILD and mem[BATTLE_TYPE] != OLD_MAN
            and not mem[ENEMY_STATUS3] & TRANSFORMED and not mem[LINK_STATE])


def reroll(mem, key):
    """Replace the wild DVs just stored. Returns the new bytes, or None when left alone."""
    if not wild(mem):
        return None
    dvs = hmac.new(key, bytes(mem[0xc000:0xe000]), hashlib.sha256).digest()[:2]
    mem[DVS] = dvs[0]
    mem[DVS + 1] = dvs[1]
    return dvs
