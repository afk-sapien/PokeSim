"""Answers derived from the Generation II game state, each kept until the state it reads changes.

A question names what it asks. Its inputs are the snapshot regions and policy settings it reads, and its
arguments narrow it, such as one more Pokémon to rate the PC with. The snapshot reader hands back the same
party, box, bag and Pokédex objects while their bytes match, so inputs compare by identity in the common
case and an unchanged state answers from the store. Each question keeps one answer, the latest, so a
store never grows past the questions asked of it.
"""


class Facts:
    """The derived answers of one running policy."""

    def __init__(self):
        self.kept = {}

    def answer(self, question, inputs, compute, *args):
        """``compute(*args)``, kept while ``inputs`` and ``args`` stay as they were asked last."""
        kept = self.kept.get(question)
        if kept is None or kept[1] != args or kept[0] != inputs:
            kept = self.kept[question] = (inputs, args, compute(*args))
        return kept[2]


def facts(policy):
    """The policy's facts. A stand-in policy without them gets its own."""
    store = getattr(policy, 'facts', None)
    if store is None:
        store = policy.facts = Facts()
    return store
