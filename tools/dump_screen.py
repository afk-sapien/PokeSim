"""Play until a condition, then print the decoded screen text after a scripted input sequence."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyboy import PyBoy
from pokesim.ram import read_snapshot, decode_text, W_TILEMAP
from pokesim.policies import make_policy
from pokesim.policies.base import PolicyContext

def screen_text(m):
    rows = []
    for r in range(18):
        raw = bytes(m[W_TILEMAP + r*20 : W_TILEMAP + r*20 + 20])
        rows.append("".join(decode_text(bytes([c])) or ("▶" if c == 0xED else "·" if c in (0x7F,0) else "#") for c in raw))
    return "\n".join(rows)

pb = PyBoy(os.environ.get("ROM_PATH", "roms/pokered.gb"), window="null", sound_emulated=False); pb.set_emulation_speed(0)
pol = make_policy("guided_random", int(os.environ.get("SEED", "1")))
f = 0
def tick(n):
    global f; pb.tick(n, render=False); f += n
def press(b, hold=8, gap=8):
    pb.button_press(b); tick(hold); pb.button_release(b); tick(gap)
# play until we are in a battle with a party (or start from a given state)
if os.environ.get("STATE"):
    with open(os.environ["STATE"], "rb") as fh:
        pb.load_state(fh)
    print("loaded state", os.environ["STATE"], flush=True)
while True:
    s = read_snapshot(pb.memory, f)
    if s.in_battle == 1 and s.party:
        break
    if f % 20000 < 50:
        print("...", f, s.map_name, (s.x, s.y), "battle", s.in_battle, "party", len(s.party), pol.mode, flush=True)
    if f > int(os.environ.get("MAXF", "400000")):
        print("gave up"); print(screen_text(pb.memory)); sys.exit(1)
    for a in pol.step(PolicyContext(s, 0, time.time())):
        press(a.button, a.hold, a.gap)
print("frame", f, "party", [(p.name, p.hp) for p in s.party], "enemy", s.enemy_species)
# advance text until the main battle menu shows
for i in range(40):
    txt = screen_text(pb.memory)
    if "FIGHT" in txt: break
    press("a", 8, 30)
print("=== main menu ===\n" + screen_text(pb.memory))
press("a", 8, 30); print("=== after A (move menu?) ===\n" + screen_text(pb.memory))
press("b", 8, 30); press("down", 8, 30); press("a", 8, 30); print("=== ITEM menu ===\n" + screen_text(pb.memory))
press("b", 8, 30); press("right", 8, 30); press("a", 8, 30); print("=== PKMN menu ===\n" + screen_text(pb.memory))
press("b", 8, 30); press("b", 8, 30); print("=== back ===\n" + screen_text(pb.memory)[-120:])
import struct
m = pb.memory
print("wCurrentMenuItem CC26=", m[0xCC26], "wMaxMenuItem CC28=", m[0xCC28], "wMenuWatchedKeys CC29=", m[0xCC29], "wTopMenuItemY CC24=", m[0xCC24], "X CC25=", m[0xCC25])
print("enemy hp", (m[0xCFE6]<<8)|m[0xCFE7], "/", (m[0xCFF4]<<8)|m[0xCFF5], "options D355=", hex(m[0xD355]))
pb.save_state(open(os.environ.get("OUT", "/tmp/battle.state"), "wb"))
