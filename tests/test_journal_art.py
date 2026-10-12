from pokesim.web.journal_art import annotate, species_index

INDEX = species_index({25: 'PIKACHU', 133: 'EEVEE', 197: 'UMBREON', 152: 'CHIKORITA'})


def test_entries_about_one_pokemon_name_its_species():
    cases = [('catch', 'Caught PIKACHU!', 25), ('catch', 'Caught the legendary EEVEE', 133),
             ('obtain', 'Got EEVEE!', 133), ('hatch', 'CHIKORITA hatched from its Egg', 152),
             ('evolve', 'EEVEE evolved into UMBREON!', 197), ('level', 'PIKACHU grew to level 40', 25)]
    for kind, title, dex in cases:
        assert annotate({'type': kind, 'title': title}, INDEX)['species_dex'] == dex, title


def test_other_entries_and_nicknames_are_left_alone():
    assert 'species_dex' not in annotate({'type': 'badge', 'title': 'Got EEVEE!'}, INDEX)
    assert 'species_dex' not in annotate({'type': 'level', 'title': 'SPARKY grew to level 40'}, INDEX)
    assert 'species_dex' not in annotate({'type': 'catch', 'title': 'Caught PIKACHU!'}, {})
