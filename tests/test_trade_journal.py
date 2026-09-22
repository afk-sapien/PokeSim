"""A completed cable trade should say what crossed, not just that something did."""
from pokesim.runtime.participant import _trade_story, _traded_mon
from pokesim.ram import SPECIES_NAMES
from pokesim.trade import boxes


def species_id(name):
    return next(sid for sid, label in SPECIES_NAMES.items() if label.upper() == name)


def side(name, level, nick, trainer):
    struct = bytearray(boxes.BOX_STRUCT)
    struct[boxes.SPECIES] = species_id(name)
    struct[boxes.LEVEL] = level
    return {'struct': bytes(struct).hex(), 'nickname': boxes.encode_text(nick).hex(),
            'ot_name': boxes.encode_text(trainer).hex()}


def test_the_entry_names_both_pokemon_and_the_trainer_on_the_other_end():
    record = {'outgoing': side('WEEDLE', 13, 'CRUMBOSS', 'ZIGGY'),
              'incoming': side('RATTATA', 9, 'BORKUS', 'BLUE')}
    title, body, detail = _trade_story(record)
    assert title == 'Traded CRUMBOSS for BORKUS'
    assert 'Weedle at level 13' in body and 'Rattata at level 9' in body
    assert 'first trained by BLUE' in body
    assert detail['kind'] == 'trade' and detail['peer'] == 'BLUE'
    assert detail['sent']['dex'] == 13 and detail['received']['dex'] == 19
    assert detail['sent']['nick'] == 'CRUMBOSS' and detail['received']['nick'] == 'BORKUS'


def test_a_record_written_before_this_keeps_the_old_wording():
    """Records staged by an older build have no incoming side, and must still read sensibly."""
    title, body, detail = _trade_story({'outgoing': side('WEEDLE', 13, 'CRUMBOSS', 'ZIGGY')})
    assert title == 'Cable Club trade completed'
    assert body == 'Both cartridges completed their exchange and saved the result.'
    assert detail is None


def test_damaged_or_missing_sides_never_raise():
    for bad in ({}, {'struct': ''}, {'struct': 'nothex'}, {'struct': '00'}, None, 'text'):
        assert _traded_mon(bad) is None
    title, _, detail = _trade_story({'outgoing': {'struct': 'nothex'}, 'incoming': {'struct': 'zz'}})
    assert title == 'Cable Club trade completed' and detail is None


def test_a_nameless_pokemon_falls_back_to_its_species():
    record = {'outgoing': side('WEEDLE', 5, '', 'ZIGGY'), 'incoming': side('RATTATA', 5, '', '')}
    title, body, detail = _trade_story(record)
    assert title == 'Traded Weedle for Rattata'
    assert 'first trained by' not in body
    assert detail['peer'] == ''
