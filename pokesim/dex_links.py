"""The Pokédex "Read more" links, shared by every generation."""
from urllib.parse import quote


def links(name: str, dex: int) -> dict:
    """Outside references for players who want more than the cartridge knows."""
    return {"bulbapedia": f"https://bulbapedia.bulbagarden.net/wiki/{quote(name)}_(Pok%C3%A9mon)",
            "serebii": f"https://www.serebii.net/pokedex/{dex:03d}.shtml",
            "wikipedia": f"https://en.wikipedia.org/wiki/Special:Search?search={quote(name + ' Pokémon')}"}
