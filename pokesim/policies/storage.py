"""PC menu state and partner selection with explicit goals and protection data."""
from dataclasses import dataclass

from .menus import MenuDecision, select, tap
from .collection import Collection, held_count
from .team import release_target, reserve_to_deposit
from ..strategy_data import SPECIES
from ..trade.preferences import identity


FIELD_MOVE_GOALS = {'party_cut': 15, 'party_surf': 57, 'party_strength': 70}

@dataclass
class StorageController:
    operation: str | None = None
    species: int | None = None
    destination: int | None = None
    pending_release: tuple | None = None

    @staticmethod
    def release_target(snapshot, project, preferences, collection=None):
        project = project or {}
        protected = set(project.get('family', [project['parent']])) if project.get('method') in ('evolve', 'train') and project.get('parent') else set()
        demand = collection.demand() if collection else {}
        protected.update(sid for sid, data in SPECIES.items()
                         if demand.get(data['dex'], 0) and held_count(snapshot, sid) <= demand[data['dex']])
        if project.get('method') == 'trade':
            protected.add(project['give'])
        reserved = {(mon['box'], mon['position']) for mon in snapshot.storage_entries()
                    if preferences.get(identity(mon), {}).get('state') in ('offered', 'locked')}
        return release_target(snapshot, protected, reserved)

    @staticmethod
    def field_move_box(snapshot, goal_key):
        """Box holding the strongest stored partner for a field move, preferring the open box."""
        move = FIELD_MOVE_GOALS.get(goal_key)
        boxes = [(box == snapshot.active_box, level, box) for box, species, level, _ in snapshot.stored_pokemon
                 if move in SPECIES.get(species, {}).get('hms', [])]
        return max(boxes)[2] if move and boxes else None

    def target(self, snapshot, goal_key, project, preferences, collection=None):
        if goal_key == 'party_release':
            release = self.release_target(snapshot, project, preferences, collection)
            return release[1] if release and release[0] == snapshot.active_box else None
        if self.operation == 'deposit':
            if len(snapshot.party) < 6 or snapshot.box_full:
                return None
            project = project or {}
            if goal_key == 'party_collection' and project.get('method') == 'trade':
                return collection.trade_deposit_target(snapshot, project) if collection else None
            return reserve_to_deposit(snapshot, prefer_completed=goal_key == 'party_collection'
                                      and project.get('method') == 'train')
        if goal_key == 'party_collection_space':
            return None
        if goal_key == 'party_collection' and project:
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
            pending = self.pending_release
            current = next((mon for mon in snapshot.storage_entries()
                            if pending and (mon['box'], mon['position']) == pending[:2]), None)
            allowed = (goal_key == 'party_release' and pending and current == pending[2]
                       and self.release_target(snapshot, project, preferences, collection) == pending[:2])
            return MenuDecision(select(screen, 0 if allowed else 1))
        if context == 'pc' and goal_key.startswith('party_'):
            return MenuDecision(select(screen, 0), 'Confirm the storage prompt')
        return None

    def step(self, snapshot, screen, kind, goal_key, project, preferences, collection=None):
        if kind == 'pc_root':
            return MenuDecision(select(screen, 0) if goal_key.startswith('party_') else tap('b'))
        if kind == 'change_box':
            release = self.release_target(snapshot, project, preferences, collection) if goal_key == 'party_release' else None
            target = ((release[0] if release else None) if goal_key == 'party_release' else
                      snapshot.next_free_box if goal_key == 'party_box' else
                      self.field_move_box(snapshot, goal_key) if goal_key in FIELD_MOVE_GOALS else
                      project.get('box') if goal_key == 'party_collection' and project else None)
            return MenuDecision(tap('b') if target is None or target == snapshot.active_box else select(screen, target),
                                'Select a storage box with room for new catches')
        if kind == 'pc':
            if not goal_key.startswith('party_'):
                return MenuDecision(tap('b'))
            if screen.cursor and screen.cursor[0] == 10:
                return MenuDecision(select(screen, 0))
            if goal_key == 'party_release':
                release = self.release_target(snapshot, project, preferences, collection)
                if release is None:
                    return MenuDecision(tap('b'))
                if release[0] != snapshot.active_box:
                    return MenuDecision(select(screen, 3), 'Open the box holding the spare duplicate')
                return MenuDecision(select(screen, 2), 'Let a spare duplicate go, keeping one of every species')
            if goal_key == 'party_box' or (goal_key == 'party_collection' and len(snapshot.party) < 6
                                           and project and project.get('box') != snapshot.active_box):
                return MenuDecision(select(screen, 3), 'Change the active storage box without releasing any Pokémon')
            if (goal_key in FIELD_MOVE_GOALS and len(snapshot.party) < 6
                    and self.field_move_box(snapshot, goal_key) not in (None, snapshot.active_box)):
                return MenuDecision(select(screen, 3), 'Open the box holding a partner that can learn the field move')
            self.operation = 'deposit' if len(snapshot.party) >= 6 else 'withdraw'
            if self.target(snapshot, goal_key, project, preferences, collection) is None:
                return MenuDecision(tap('b'))
            return MenuDecision(select(screen, 1 if self.operation == 'deposit' else 0))
        if kind == 'list':
            target = self.target(snapshot, goal_key, project, preferences, collection)
            if target is None:
                return MenuDecision(tap('b'))
            actions = select(screen, target, scroll=True)
            if goal_key == 'party_release' and actions[0].button == 'a':
                chosen = next((mon for mon in snapshot.storage_entries()
                               if (mon['box'], mon['position']) == (snapshot.active_box, target)), None)
                self.pending_release = (snapshot.active_box, target, chosen) if chosen else None
            return MenuDecision(actions)
        raise ValueError(f'Unsupported PC menu: {kind}')
