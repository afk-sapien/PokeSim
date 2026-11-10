"""Whole-word keyword search, ported from PokeSim's screen and nickname robustness tests."""
import pytest

from pokecore import gen2, textmatch
from pokecore.gen2 import screens
from pokecore.textmatch import ScreenText, has_word

# Words the Gen 1 and Gen 2 screen classifiers search for. A nickname equal to or
# containing one of them must not read as that menu word.
KEYWORDS = (
    'CANCEL', 'QUIT', 'USE', 'TYPE', 'FIGHT', 'PACK', 'RUN', 'PKMN', 'SWITCH', 'STATS', 'SAVE', 'DEL', 'END',
    'YES', 'NO', 'ITEM', 'ABLE', 'TOSS', 'GIVE', 'TAKE', 'BUY', 'SELL', 'LEVEL', 'GEAR', 'NAME', 'GAME',
    'FORGET', 'FRESH', 'SODA', 'LEMONADE', 'RELEASED', 'HEAL', 'TECHNIQUE', 'PROTOTYPE', 'MOSQUITO',
    'TROUSERBAT', 'FIEND', 'CANCELLER', 'BALL', 'TURN OFF', 'MOVE', 'POKE',
)


def test_whole_word_search_ignores_embedded_keywords():
    text = ScreenText('PROTOTYPE\nMOSQUITO\nTROUSERBAT\nFIEND\nCANCEL')
    assert 'TYPE' not in text and 'QUIT' not in text and 'USE' not in text and 'END' not in text
    assert 'CANCEL' in text
    assert 'TYPE/' in ScreenText('TYPE/NORMAL')
    assert has_word('SURF here', 'SURF') and not has_word('SURFING', 'SURF')
    assert has_word('349/351', '/')


@pytest.mark.parametrize('word', KEYWORDS)
def test_a_keyword_inside_a_longer_name_is_not_a_match(word):
    for name in ('X' + word, word + 'X', 'X' + word + 'X'):
        assert word not in ScreenText(name), name
        assert not has_word(name, word)
    assert word in ScreenText(f'  {word}  ')
    assert word in ScreenText(f'▶{word}\n')


def test_yes_no_labels_need_the_whole_word():
    assert 'YES' not in ScreenText('     YESMAN\n     NOBODY')
    assert 'NO' not in ScreenText('     YESMAN\n     NOBODY')
    assert 'YES' in ScreenText('     MR MIME    ?YES?') and 'NO' in ScreenText('     HITMONLEE  ?NO ?')


def test_released_nickname_is_not_the_release_message():
    assert 'RELEASED' not in ScreenText('PRERELEASED\nRELEASEDX')
    assert 'RELEASED' in ScreenText('RELEASED!')


def test_screen_text_keeps_plain_string_behaviour():
    text = ScreenText('FIGHT PKMN')
    assert text == 'FIGHT PKMN' and text.split() == ['FIGHT', 'PKMN']
    assert '' in text
    with pytest.raises(TypeError):
        3 in text


def test_gen2_screens_reexport_the_shared_copy():
    assert screens.has_word is textmatch.has_word and screens.ScreenText is textmatch.ScreenText
    assert gen2.has_word is textmatch.has_word and gen2.ScreenText is textmatch.ScreenText
