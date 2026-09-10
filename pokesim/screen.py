"""Read what is on screen by decoding the game's shadow tilemap as text.

In Gen 1 the font tiles are placed by character code, so decoding the 20x18 tile map with the
text charset gives the visible text of menus and dialogue — enough to know which menu is open.
"""
from __future__ import annotations

from .ram import W_TILEMAP, decode_text

W_CURRENT_MENU_ITEM = 0xCC26
W_TOP_MENU_Y = 0xCC24
W_TOP_MENU_X = 0xCC25
W_LIST_SCROLL_OFFSET = 0xCC36
W_MAX_MENU_ITEM = 0xCC28
W_PLAYER_MON_NUMBER = 0xCC2F      # index in party of the Pokémon currently out
W_ENEMY_HP = 0xCFE6               # 2 bytes
W_ENEMY_MAX_HP = 0xCFF4           # 2 bytes
W_OPTIONS = 0xD355                # bits 0-2 text speed (1 fast/3 mid/5 slow), bit 6 battle style, bit 7 animations off


def rows(mem) -> list[str]:
    raw = bytes(mem[W_TILEMAP:W_TILEMAP + 20 * 18])
    out = []
    for r in range(18):
        line = raw[r * 20:(r + 1) * 20]
        out.append("".join(decode_text(bytes([c])) or " " for c in line))
    return out


class Screen:
    __slots__ = ("rows", "text", "cursor", "menu_index", "scroll", "top_x", "top_y")

    def __init__(self, mem):
        self.rows = rows(mem)
        self.text = "\n".join(self.rows)
        raw = bytes(mem[W_TILEMAP:W_TILEMAP + 360])
        self.cursor = next(((i % 20, i // 20) for i, tile in enumerate(raw) if tile == 0xED), None)
        self.menu_index = mem[W_CURRENT_MENU_ITEM]
        self.scroll = mem[W_LIST_SCROLL_OFFSET]
        self.top_x = mem[W_TOP_MENU_X]
        self.top_y = mem[W_TOP_MENU_Y]

    def kind(self, snapshot) -> str:
        """Classify visible input states. A filled cursor confirms a menu is accepting input."""
        text = self.text.upper()
        if self.naming:
            return "naming"
        if self.cursor:
            x, y = self.cursor
            if "1F" in text and "2F" in text and ("3F" in text or "B4F" in text):
                return "elevator"
            if "FRESH" in text and "SODA" in text and "LEMONADE" in text:
                return "vending"
            if any(row.strip("? ") == "HEAL" for row in self.rows) and "CANCEL" in text:
                return "heal"
            if self.yes_no:
                return "yes_no"
            if "BOX 1" in text and "BOX12" in text:
                return "change_box"
            if 'PORYGON' in text and ('DRATINI' in text or 'PINSIR' in text):
                return 'prize'
            if self.battle_menu:
                return "battle"
            if "BALL" in text and "BAIT" in text and "ROCK" in text and "RUN" in text:
                return "safari"
            if "SWITCH" in text and "STATS" in text:
                return "party_action"
            if "USE" in text and "TOSS" in text:
                return "item_action"
            if ("FORG" in text or "HM TECHNIQUES" in text) and x == 5 and 8 <= y <= 11:
                return "learn_move"
            if x == 5 and 13 <= y <= 16 and snapshot.in_battle:
                return "moves"
            if x == 0 and y <= 11 and snapshot.party and not self.pause_menu:
                return "party"
            if self.shop:
                return "shop"
            if self.pause_menu:
                return "pause"
            if "LOG OFF" in text and "PC" in text:
                return "pc_root"
            if self.pc:
                return "pc"
            if self.list_menu or (self.top_x == 5 and self.top_y == 4 and x == 5 and 4 <= y <= 8):
                return "list"
        if "HOW MANY" in text:
            return "quantity"
        if snapshot.textbox or (snapshot.in_battle and not self.cursor):
            return "dialogue"
        return "overworld"

    def has(self, *words: str) -> bool:
        return all(w in self.text for w in words)

    @property
    def battle_menu(self) -> bool:
        return "FIGHT" in self.rows[14] and "RUN" in self.rows[16]

    @property
    def list_menu(self) -> bool:
        """An item / Pokémon list with a CANCEL entry (bag, party, PC, shop)."""
        return "CANCEL" in self.text and not self.battle_menu

    @property
    def yes_no(self) -> bool:
        return self.has("YES") and self.has("NO") and "MON" not in self.text[: self.text.find("NO")].split("\n")[-1]

    @property
    def shop(self) -> bool:
        return self.has("BUY", "SELL")

    @property
    def pc(self) -> bool:
        return self.has("WITHDRAW") or self.has("DEPOSIT")

    @property
    def naming(self) -> bool:
        # The cursor replaces a space between letters as it crosses the first row.
        return any(r[2:19:2] in ("ABCDEFGHI", "abcdefghi") for r in self.rows)

    @property
    def pause_menu(self) -> bool:
        return self.has("EXIT") and (self.has("ITEM") or self.has("SAVE") or self.has("OPTION"))
