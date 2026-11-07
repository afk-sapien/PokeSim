"""PC menu state and partner selection with explicit goals and protection data."""
from dataclasses import dataclass, field

from .menus import MenuDecision, select, tap
from .collection import Collection
from .team import release_rated, release_target, reserve_to_deposit
from . import league_rotation
from ..strategy_data import SPECIES


FIELD_MOVE_GOALS = {'party_cut': 15, 'party_surf': 57, 'party_strength': 70}

@dataclass
class StorageController:
    operation: str | None = None
    species: int | None = None
    destination: int | None = None
    # Slots whose release failed recently. The planner refreshes this before every PC decision.
    avoid: frozenset = frozenset()
    # Trainer ids of linked adventures (trade/partners.py), refreshed with ``avoid``.
    partners: frozenset = frozenset()
    # The planner's own release ranking (snapshot -> (box, position) or None), so the menu takes the
    # Pokémon it chose with every input: League rewards, owner requests and the Favor setting.
    ranker: object = field(default=None, compare=False, repr=False)

    def _release(self, snapshot, project, preferences, collection):
        if self.ranker is not None:
            return self.ranker(snapshot)
        return self.release_target(snapshot, project, preferences, collection, self.avoid, self.partners)

    @staticmethod
    def release_target(snapshot, project, preferences, collection=None, avoid=(), partners=frozenset(),
                       rewards=frozenset(), requested=None, favor=None):
        """The Pokémon to let go as (box, position), lowest value first (pcvalue.py). ``avoid`` holds
        slots whose release just failed.

        The running project's family, a League rotation parent and a trade's give are stock, which holds
        a plan role for its best copies. Peer demand keeps the copies it asks for. ``partners`` are the
        linked adventures, ``rewards`` the League reward marks and ``requested`` the owner's release
        requests.
        """
        stock, roles, gifts, demand = StorageController.plan_inputs(project, collection)
        return release_target(snapshot, stock, avoid, partners, gifts, preferences, demand, rewards, requested, roles, favor)

    @staticmethod
    def plan_inputs(project, collection=None):
        """The stock species, role keys, gift species and copy demand the running plan gives a release.
        Stock maps each species to 'plan' or, for a trade's give, 'trade'."""
        project = project or {}
        stock = set(project.get('family', [project['parent']])) if project.get('method') in ('evolve', 'train') and project.get('parent') else set()
        if project.get('league_rotation') and not project.get('rotation_ready'):
            stock.add(project['parent'])
        stock = dict.fromkeys(stock, 'plan')
        if project.get('method') == 'trade':
            stock.setdefault(project['give'], 'trade')
        roles = {project['trainee_key']} if isinstance(project.get('trainee_key'), str) else set()
        return (stock, roles, collection.gift_species() if hasattr(collection, 'gift_species') else frozenset(),
                collection.demand() if collection else {})

    @staticmethod
    def rated(snapshot, project, preferences, collection=None, partners=frozenset(), rewards=frozenset(),
              requested=None, favor=None):
        """Every Pokémon scored as release_target scores it, for the PC tab."""
        stock, roles, gifts, demand = StorageController.plan_inputs(project, collection)
        return release_rated(snapshot, preferences, roles, stock, partners, gifts, rewards, requested, demand, favor)

    @staticmethod
    def field_move_box(snapshot, goal_key):
        """Box holding the strongest stored partner for a field move, preferring the open box."""
        move = FIELD_MOVE_GOALS.get(goal_key)
        boxes = [(box == snapshot.active_box, level, box) for box, species, level, _ in snapshot.stored_pokemon
                 if move in SPECIES.get(species, {}).get('hms', [])]
        return max(boxes)[2] if move and boxes else None

    def target(self, snapshot, goal_key, project, preferences, collection=None):
        if goal_key == 'party_release':
            release = self._release(snapshot, project, preferences, collection)
            return release[1] if release and release[0] == snapshot.active_box else None
        if self.operation == 'deposit':
            if len(snapshot.party) < 6 or snapshot.box_full:
                return None
            project = project or {}
            if goal_key == 'party_league':
                return league_rotation.deposit_target(snapshot, preferences, collection.league_appearances)
            if goal_key == 'party_collection' and project.get('method') == 'trade':
                return collection.trade_deposit_target(snapshot, project) if collection else None
            return reserve_to_deposit(snapshot, prefer_completed=goal_key == 'party_collection'
                                      and project.get('method') == 'train')
        if goal_key == 'party_collection_space':
            return None
        if goal_key in ('party_collection', 'party_league') and project:
            if project.get('trainee_key'):
                matches = [mon for mon in Collection.partner_matches(snapshot, project) if 'party_index' not in mon]
                return (matches[0]['position'] if len(matches) == 1 and len(snapshot.party) < 6
                        and matches[0]['box'] == snapshot.active_box else None)
            if project.get('method') == 'trade':
                partner = collection.trade_candidate(snapshot, project) if collection else None
                return partner['position'] if partner and partner.get('box') == snapshot.active_box and len(snapshot.party) < 6 else None
            return next((i for i, (species, level) in enumerate(snapshot.boxed_pokemon)
                         if species == project['parent']), None) if len(snapshot.party) < 6 else None
        move = FIELD_MOVE_GOALS.get(goal_key)
        candidates = [(level, i) for i, (species, level) in enumerate(snapshot.boxed_pokemon)
                      if (species == self.species if goal_key == 'party_upgrade'
                          else move in SPECIES.get(species, {}).get('hms', []))]
        return max(candidates)[1] if candidates and len(snapshot.party) < 6 else None

    def confirmation(self, snapshot, screen, text, goal_key, project, preferences, context, collection=None):
        if 'GONE FOREVER' in text or 'RELEASED' in text or 'BYE BYE' in text:
            # Releases run as Core shortcuts, which answer their own prompt. Any other is refused.
            return MenuDecision(select(screen, 1))
        if context == 'pc' and goal_key.startswith('party_'):
            return MenuDecision(select(screen, 0), 'Confirm the storage prompt')
        return None

    def box_target(self, snapshot, goal_key, project, preferences, collection=None):
        """The box a storage goal wants as the current box, or None."""
        if goal_key == 'party_release':
            release = self._release(snapshot, project, preferences, collection)
            return release[0] if release else None
        if goal_key == 'party_box':
            return snapshot.next_free_box
        if goal_key in FIELD_MOVE_GOALS:
            return self.field_move_box(snapshot, goal_key)
        return project.get('box') if goal_key in ('party_collection', 'party_league') and project else None

    @staticmethod
    def change_box(screen, box, reason):
        """Change boxes with the Core shortcut. CHANGE BOX is opened by hand if Core refuses."""
        if box is None:
            return MenuDecision(select(screen, 3), reason)
        return MenuDecision(select(screen, 3), reason, request=('change_box', box))

    def step(self, snapshot, screen, kind, goal_key, project, preferences, collection=None):
        if kind == 'pc_root':
            return MenuDecision(select(screen, 0) if goal_key.startswith('party_') else tap('b'))
        if kind == 'change_box':
            target = self.box_target(snapshot, goal_key, project, preferences, collection)
            return MenuDecision(tap('b') if target is None or target == snapshot.active_box else select(screen, target),
                                'Select a storage box with room for new catches')
        if kind == 'pc':
            if not goal_key.startswith('party_') or screen.cursor and screen.cursor[0] == 10:
                return MenuDecision(tap('b'))
            if goal_key == 'party_release':
                release = self._release(snapshot, project, preferences, collection)
                if release is None:
                    return MenuDecision(tap('b'))
                if release[0] != snapshot.active_box:
                    return self.change_box(screen, release[0], 'Open the box holding the spare duplicate')
                return MenuDecision(tap('b'), 'Let a spare duplicate go, keeping one of every species',
                                    request=('release', release[1]))
            if goal_key == 'party_box' or (goal_key in ('party_collection', 'party_league') and len(snapshot.party) < 6
                                           and project and project.get('box') != snapshot.active_box):
                return self.change_box(screen, self.box_target(snapshot, goal_key, project, preferences, collection),
                                       'Change the active storage box without releasing any Pokémon')
            if (goal_key in FIELD_MOVE_GOALS and len(snapshot.party) < 6
                    and self.field_move_box(snapshot, goal_key) not in (None, snapshot.active_box)):
                return self.change_box(screen, self.field_move_box(snapshot, goal_key),
                                       'Open the box holding a partner that can learn the field move')
            self.operation = 'deposit' if len(snapshot.party) >= 6 else 'withdraw'
            target = self.target(snapshot, goal_key, project, preferences, collection)
            if target is None:
                return MenuDecision(tap('b'))
            return MenuDecision(tap('b'), 'Deposit a reserve Pokémon' if self.operation == 'deposit'
                                else 'Withdraw a stored partner', request=(self.operation, target))
        raise ValueError(f'Unsupported PC menu: {kind}')
