"""Identify visible ground items in the locally generated world data."""
import re

from .strategy_data import ITEMS


def ground_item(obj):
    if obj[2] != 'SPRITE_POKE_BALL':
        return None
    # Generated text labels name the object within its map. Match the entire item
    # name so starter balls and disguised Voltorb are never treated as supplies.
    token = obj[4].removeprefix('TEXT_').partition('_')[2]
    token = re.sub(r'\d+$', '', token)
    # The Safari Zone East object label differs from its actual item constant.
    if obj[4] == 'TEXT_SAFARIZONEEAST_MAX_RESTORE':
        token = 'MAX_POTION'
    if token in ITEMS:
        return {'item': ITEMS[token], 'name': token.replace('_', ' ').title()}
    if token.startswith('TM_'):
        return {'item': None, 'name': 'TM ' + token[3:].replace('_', ' ').title()}
    return None

