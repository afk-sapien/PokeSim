"""Fight, catch and switch in Generation II battles."""
from __future__ import annotations

from dataclasses import replace
import re
from types import SimpleNamespace

from ...planning.ledger import LEARN_KEPT
from ...planning.stance import FLEE, STORY, Encounter, stance
from ...runtime.policy import Action
from pokecore.gen2.screens import ScreenText, mask_roster
from ..menus import Attack, Flee, Lead, Learn, Send, Throw
from .reads import Battlers

# The wPlayerSubStatus5 bit the battle engine sets while the player's Pokémon is Transformed.
SUBSTATUS_TRANSFORMED = 8
# Moves with no power of their own that use another move, which may be an attack.
BORROWED_MOVES = frozenset({'EFFECT_TRANSFORM', 'EFFECT_MIMIC', 'EFFECT_METRONOME', 'EFFECT_MIRROR_MOVE', 'EFFECT_SLEEP_TALK'})
# Rest heals with EFFECT_HEAL like Recover, then sleeps two turns. Leech Seed fails on a Grass foe.
REST, GRASS = 156, 22
# Moves that win back HP, so a foe's attacks may never knock out the Pokémon that knows one.
HEALING_MOVES = frozenset({'EFFECT_HEAL', 'EFFECT_MORNING_SUN', 'EFFECT_SYNTHESIS', 'EFFECT_MOONLIGHT',
                           'EFFECT_LEECH_SEED'})
# What long_odds answers when a catch should run and wait for a new move, member or ball.
LEAVE = 'leave'


def transformed(player, mon):
    """The active Pokémon as it fights. After Transform it has the foe's species, stats and moves.

    ``player`` is the player's battler. The party record keeps a Transformed Ditto's own Transform,
    so judging it by the party alone saw a level 100 Ditto with no attack at all.
    """
    if player is None or mon is None or not player.transformed:
        return mon
    return replace(mon, species=player.species, moves=tuple(player.moves), pp=tuple(player.pp),
                   stats=(mon.stats[0],) + tuple(player.stats[1:]))


class BattlePart:
    """Battle choices, catches, switches and move scores."""

    def move_power(self, move):
        entry = self.data.moves.get(move) or {}
        return entry.get('power') or entry.get('effect') in BORROWED_MOVES

    def matchup(self, snapshot):
        """The scorer of the party's matchup with a boss's ace (readiness.readiness), by boss key."""
        from ..readiness import readiness
        return lambda key: readiness(self, snapshot.party, key)

    def battle(self, snapshot, mem):
        # Roster nicknames are blanked so a mon named QUIT or FIGHT is not a menu.
        text = ScreenText(snapshot.text)
        if snapshot.tiles and '\n'.join(snapshot.tiles) == text:
            text = ScreenText('\n'.join(mask_roster(snapshot.tiles)))
        reads = self.reads
        battle, player, enemy = reads.battle, reads.player, reads.enemy
        opponent = self.battle_target(snapshot) if self.collection.get('tower') else snapshot
        # The native capture routine restores transformed wild opponents as Ditto.
        catch_species = 132 if enemy.transformed else snapshot.enemy_species
        needed = self.needed_move(snapshot)
        partner = (not any(needed in self.data.species[mon.species]['machines'] for mon in snapshot.party if not mon.egg)
                   and needed in self.data.species.get(catch_species, {}).get('machines', []))
        requested = (self.demand.get(catch_species, 0)
                     and sum(mon.species == catch_species and not mon.egg
                             for mon in snapshot.party + snapshot.stored) <= self.demand[catch_species])
        requested |= (catch_species in self.collection.get('prerequisites', ())
                      and not any(mon.species == catch_species and not mon.egg
                                  for mon in snapshot.party + snapshot.stored))
        own_rule = False
        if snapshot.in_battle == 1:
            # A wild carrier is caught only for the trade item it holds, never as one more copy.
            from ..collection import item_hunts
            carried = item_hunts(self, snapshot).get(catch_species)
            own_rule = bool(carried) and enemy.held_item == carried
        if catch_species == 201:
            # Each Unown letter counts separately in the Unown Pokédex, so catch every missing letter.
            from ..collection import unown_letter, unown_missing
            own_rule |= unown_letter(enemy.shown_dvs) in unown_missing(self, snapshot)
        # A wild shiny is always caught, an owned species too. Trainers' Pokémon never count.
        shiny = self.wild_shiny(snapshot)
        # A peer's request, a postgame better-DV hunt and a returned Pokémon catch an owned species only
        # when the PC would keep the copy (release.keeps_another, the one catch rule). A missing entry,
        # a field-move partner, a shiny, a missing Unown letter and an item carrier keep their own rules.
        from ..postgame import quality_species, wild_dvs
        from ..release import keeps_another
        upgrade = (snapshot.in_battle == 1 and catch_species in snapshot.owned and not (partner or shiny or own_rule)
                   and bool(requested or catch_species == quality_species(self) or catch_species in self.returned)
                   and keeps_another(self, snapshot, catch_species, dvs=wild_dvs(enemy.shown_dvs)))
        if (snapshot.in_battle == 1 and catch_species in self.returned and catch_species in {243, 244, 245, 249, 250, 251}
                and catch_species in snapshot.owned and not (upgrade or partner or shiny or own_rule)):
            # Close the return so neither the plan nor the retry timers bring back a refused legendary.
            self.declined = getattr(self, 'declined', set()) | {catch_species}
            self.returned = self.returned - {catch_species}
        catch = (snapshot.in_battle == 1 and (catch_species not in snapshot.owned or partner or own_rule or shiny or upgrade)
                 and snapshot.can_catch and any(self.data.item_names.get(item, '').casefold() in
                    {label.casefold() for label in self.ball_labels(snapshot)} for item, count in snapshot.pockets['balls'] if count))
        from ..ledger import spare_throw
        if catch and not partner and not shiny and not spare_throw(self.data, snapshot, snapshot.enemy_species):
            catch = False
        if catch and not upgrade:
            # The last free slot is kept for an upgrade. Any other catch takes it only when a release can
            # follow, and a missing entry refused asks the owner for help (boxes_full).
            from ..release import reserve_allows
            catch = reserve_allows(self, snapshot, catch_species, lambda: wild_dvs(enemy.shown_dvs))
            self.boxes_full = not catch and catch_species not in snapshot.owned
        elif catch:
            self.boxes_full = False
        # A shiny that cannot be caught is run from, as Red, Blue and Yellow do, never knocked out.
        # The Bug-Catching Contest uses Park Balls and has its own rules in contest.control.
        self.shiny_missed = (self.shiny_miss_reason(snapshot)
                             if shiny and not catch and not snapshot.bug_contest else None)
        weaken = self.capture_move(snapshot) if catch else None
        roaming = snapshot.enemy_species in {243, 244} or snapshot.enemy_species == 245 and self.data.game != 'crystal'
        trapped = battle.trapped
        # Scripted trap, red Gyarados, Celebi and Suicune battles forbid escape even without Mean Look.
        can_escape = not trapped and battle.battle_type not in {7, 9, 11, 12}
        # Core shortcuts pick moves, balls and switches. Any pack or party submenu still open
        # here belongs to no running shortcut, so it is closed.
        if 'SWITCH' in text and 'STATS' in text:
            return Action('b', 8, 32)
        # The screen state costs more than the screen text, so the pocket is read last.
        if ('QUIT' in text or '×' in text
                or ('CANCEL' in text or '▶' in text or '▷' in text)
                and (any(re.match(r'(?:H[1-7]|\d{2})[ ▶▷]', row[5:]) for row in snapshot.tiles)
                     and reads.ui.pocket == 'tms_hms'
                     or any(self.data.item_names.get(item, '').upper() in text
                            for item, _ in snapshot.pockets.get('key', ()))
                     and reads.ui.pocket == 'key_items')
                or 'CANCEL' in text and '/' not in text and 'ABLE' not in text):
            return Action('b')
        if any(row.startswith('ぐげござ') for row in snapshot.tiles[:2]):
            return Action('b', 8, 64)
        if 'already out' in text:
            return Action('b', 8, 24)
        if 'no will' in text:
            return Action('b', 8, 48)
        if 'CANCEL' in text and '/' in text and 'TYPE' not in text:
            active = min(battle.player_slot, max(0, len(snapshot.party) - 1))
            if snapshot.party and snapshot.party[active].hp:
                return Action('b')
            target = max((i for i, mon in enumerate(snapshot.party) if mon.hp and not mon.egg),
                         key=lambda i: max((self.move_score(move, snapshot.party[i], opponent)
                                            for move, pp in zip(snapshot.party[i].moves, snapshot.party[i].pp) if pp), default=0),
                         default=0)
            action = self.battle_task(Send(target), snapshot, mem)
            if action:
                return action
            cursor = reads.ui.menu_cursor[1]
            return Action('a' if target + 1 == cursor else 'down' if cursor < target + 1 else 'up')
        if 'FIGHT' in text and 'TYPE' not in text:
            action = self.stance_flee(snapshot, mem, catch=catch, shiny=shiny, escape=can_escape)
            if action:
                return action
            active = battle.player_slot
            switch = None
            # A static legendary only ever calls for the sleeper, and only while it is awake and
            # unguarded: a switch costs a sleep turn that a ball would use better.
            static = self.static_legend(snapshot)
            sleepable = static and not enemy.status and 'safeguard' not in battle.enemy_screens
            if (catch and not roaming and not trapped and (partner or shiny or snapshot.enemy_species in {245, 249, 250, 251})
                    and weaken is None and (sleepable if static else snapshot.enemy_hp > snapshot.enemy_max_hp // 2)):
                candidates = [(self.capture_move(snapshot, slot=i), i)
                              for i, mon in enumerate(snapshot.party)
                              if i != active and not mon.egg and mon.hp > mon.max_hp // 2
                              and (partner or mon.level * 2 >= snapshot.enemy_level)]
                if static:
                    candidates = [row for row in candidates if row[0] is not None and self.data.moves.get(
                        snapshot.party[row[1]].moves[row[0]], {}).get('effect') == 'EFFECT_SLEEP']
                switch = next((i for move, i in candidates if move is not None), None)
            if catch and weaken is None and switch is None and not (partner or trapped):
                odds = self.long_odds(snapshot, catch_species, active, escape=can_escape)
                if odds == LEAVE:
                    # Nobody can weaken it, so the balls are kept and the species waits for a new
                    # move, member or ball (planning.throws). A refused run fights the battle out.
                    from ..collection import defer
                    defer(self, snapshot, catch_species)
                    catch = False
                    action = self.battle_task(Flee(), snapshot, mem)
                    if action:
                        return action
                else:
                    switch = odds
            if switch is None and not catch and not trapped and self.collection.get('tower'):
                switch = self.tower_switch(snapshot, active)
            fighters = [transformed(player, mon) if index == active else mon for index, mon in enumerate(snapshot.party)]
            scores = [max((self.move_score(move, mon, opponent) for move, pp in zip(mon.moves, mon.pp) if pp), default=0)
                      if mon.hp and not mon.egg else 0 for mon in fighters]
            if (switch is None and not catch and not trapped and scores
                    and scores[min(active, len(scores) - 1)] == 0 and max(scores) > 0):
                switch = max(range(len(scores)), key=scores.__getitem__)
            if switch is None and not catch and not trapped and not self.collection.get('tower'):
                switch = self.trainee_switch(snapshot, active)
            action = switch is not None and self.battle_task(Send(switch), snapshot, mem)
            if action:
                return action
            if self.constant(snapshot) != 'BATTLE_TOWER_BATTLE_ROOM' and self.remedy(snapshot, active=battle.player_slot):
                return Action(None, 0, 24)
            self.learning = False
            if (roaming and not catch and can_escape and snapshot.in_battle == 1
                    and (snapshot.enemy_species not in snapshot.owned or snapshot.enemy_species in self.returned)):
                # A fainted roaming beast never returns, so leave it for a visit with room and balls.
                action = self.battle_task(Flee(), snapshot, mem)
                if action:
                    return action
            if catch and weaken is None:
                labels = [label.casefold() for label in self.ball_labels(snapshot)]
                balls = {self.data.item_names.get(item, '').casefold(): item for item, count in snapshot.pockets['balls'] if count}
                ball = next((balls[label] for label in labels if label in balls), None)
                action = ball is not None and self.battle_task(Throw(ball), snapshot, mem)
                if action:
                    return action
            mon = transformed(player, snapshot.party[min(active, len(snapshot.party) - 1)]) if snapshot.party else None
            move = weaken if catch and weaken is not None else self.move_choice(snapshot, mon, opponent, None) if mon else None
            if move is None and mon and not any(mon.pp):
                move = 0  # FIGHT with no PP left is Struggle, which the Core shortcut runs.
            action = move is not None and self.battle_task(Attack(move), snapshot, mem)
            if action:
                return action
            # No move has PP (Struggle) or the game refused the shortcut, so FIGHT is pressed and
            # the move list below picks the move. The cartridge remembers this cursor between turns.
            column, row = reads.ui.menu_cursor
            if column > 1:
                return Action('left')
            if row > 1:
                return Action('up')
            return Action('a')
        if any(phrase in text for phrase in ('trying to learn', 'Which move', 'HM moves', 'Forget an')):
            self.learning = True
            if snapshot.party:
                action = self.battle_task(Learn(self.learn_slot(snapshot.party[min(
                    reads.ui.party_slot, len(snapshot.party) - 1)])), snapshot, mem)
                if action:
                    return action
        if ('TYPE/' in text or 'Disabled!' in text or 'No PP' in text or 'TYPE' in text and '/' in text
                or self.learning and '▶' in text and 'Which move' in text):
            slot = min(reads.ui.party_slot if self.learning else battle.player_slot, max(0, len(snapshot.party) - 1))
            if snapshot.party:
                mon = snapshot.party[slot]
                if self.learning:
                    # The Core shortcut was refused, so the move list is answered directly.
                    forget = self.learn_slot(mon)
                    if forget == 'keep':
                        return Action('b')
                    target = forget + 1
                else:
                    move = self.move_choice(snapshot, transformed(player, mon), opponent, weaken)
                    target = 1 if move is None else move + 1
                cursor = reads.ui.menu_cursor[1]
                if cursor != target:
                    return Action('down' if cursor < target else 'up', 8, 40)
            return Action('a', 8, 40)
        return Action('a', 8, 24)

    @staticmethod
    def wild_shiny(snapshot):
        """The wild opponent is shiny. Trainers' Pokémon and a Ditto's borrowed look never count."""
        return getattr(snapshot, 'in_battle', 0) == 1 and bool(getattr(snapshot, 'enemy_shiny', False))

    def shiny_miss_reason(self, snapshot):
        """Why a wild shiny cannot be caught, in the words of the Red, Blue and Yellow notice."""
        if not snapshot.can_catch:
            return 'no storage space'
        if dict(snapshot.pockets['balls']).get(self.data.items['MASTER_BALL']):
            return 'only the Master Ball, kept for a legendary'
        return 'no balls'

    def static_legend(self, snapshot):
        """Lugia, Ho-Oh and Crystal's Tin Tower Suicune: catch rate 3, met once at a fixed spot."""
        return snapshot.enemy_species in {249, 250} or snapshot.enemy_species == 245 and self.data.game == 'crystal'

    def static_capture_move(self, snapshot, mon):
        """Sleep first, then chip a sleeping legendary to half HP without the risk of a KO.

        In Gen II only sleep and freeze raise the catch chance (+10 on a catch rate of 3, against at
        most +3 for low HP), and paralysis would block sleep, so it is never used. Lugia and Ho-Oh
        open with Safeguard and cast it again as it ends, and an awake one Recovers any chip, so while
        Safeguard is up the balls wait: Disable the Safeguard, else chip or stall until it drops.
        """
        usable = [(index, self.data.moves.get(move, {})) for index, move in enumerate(mon.moves) if mon.pp[index]]
        battle = self.reads.battle
        enemy = self.reads.enemy
        status = enemy.status
        guarded = 'safeguard' in battle.enemy_screens
        types = self.data.species[snapshot.enemy_species]['types']
        sleeper = not status and self.party_sleeper(snapshot)
        if not status and not guarded:
            sleep = [(entry['accuracy'], index) for index, entry in usable if entry.get('effect') == 'EFFECT_SLEEP'
                     and all(self.data.matchups.get((entry['type'], kind), 1) for kind in types)]
            if sleep:
                return max(sleep)[1]
            if sleeper:
                return None
        if guarded and sleeper:
            last = self.data.moves.get(enemy.last_move, {}).get('effect')
            if last == 'EFFECT_SAFEGUARD' and enemy.disabled_move is None:
                disable = next((index for index, entry in usable if entry.get('effect') == 'EFFECT_DISABLE'), None)
                if disable is not None:
                    return disable
        elif not status and any(self.data.moves.get(move, {}).get('effect') in {'EFFECT_HEAL', 'EFFECT_MORNING_SUN'}
                                for move in enemy.moves):
            return None  # Recover undoes the chip, so throw.
        # Each sleep turn spent chipping is a throw lost (13/256 asleep), while half HP adds about 2/256
        # per throw, so chip only while plenty of sleep remains (the low bits count the turns left).
        if status and (snapshot.enemy_hp <= snapshot.enemy_max_hp // 2 or status & 0x07 < 3):
            return None
        if not status and not guarded and snapshot.enemy_hp <= snapshot.enemy_max_hp // 2:
            return None
        options = []
        for index, entry in usable:
            effect = entry.get('effect')
            if not entry.get('power'):
                if guarded and sleeper and ('_UP' in (effect or '') or effect == 'EFFECT_DEFENSE_CURL'):
                    options.append((0, 0, index))  # A harmless stall beats a 3/256 throw.
                continue
            hits = {'EFFECT_NORMAL_HIT': 1, 'EFFECT_FALSE_SWIPE': 1, 'EFFECT_DOUBLE_HIT': 2, 'EFFECT_MULTI_HIT': 5}.get(effect)
            if not hits:
                continue
            special = entry['type'] >= 20
            defense = enemy.stats[5 if special else 2]
            attack = mon.stats[4 if special else 1]
            factor = 1.5 if entry['type'] in self.data.species[mon.species]['types'] else 1
            for kind in set(types):
                factor *= self.data.matchups.get((entry['type'], kind), 1)
            damage = (((2 * mon.level // 5 + 2) * entry['power'] * attack / max(1, defense)) / 50 + 2) * factor * hits
            # A critical hit doubles damage in Gen II; 2.5x leaves room for that and the top damage roll.
            if effect == 'EFFECT_FALSE_SWIPE':
                options.append((2, 0, index))
            elif 0 < damage * 2.5 < snapshot.enemy_hp:
                options.append((1, damage, index))
        return max(options)[2] if options else None

    def party_sleeper(self, snapshot):
        """Some healthy party Pokémon can still put the static legendary to sleep."""
        types = self.data.species[snapshot.enemy_species]['types']
        return any(mon.hp and not mon.egg and any(pp and self.data.moves.get(move, {}).get('effect') == 'EFFECT_SLEEP'
                                                  and all(self.data.matchups.get((self.data.moves[move]['type'], kind), 1)
                                                          for kind in types)
                                                  for move, pp in zip(mon.moves, mon.pp))
                   for mon in snapshot.party)

    LEARN_PROTECTED = LEARN_KEPT

    def learn_slot(self, mon):
        """The move slot a new level-up move replaces: the weakest unprotected one, or 'keep'."""
        if all(move in self.LEARN_PROTECTED for move in mon.moves):
            return 'keep'
        return min(range(4), key=lambda i: 999 if mon.moves[i] in self.LEARN_PROTECTED
                   else self.data.moves.get(mon.moves[i], {}).get('power', 0))

    def stance_flee(self, snapshot, mem, *, catch, shiny, escape):
        """Start running from this battle when the goal's stance says to flee, else None.

        The stance (planning/stance.py) decides from the goal's kind and the party's HP and PP. A
        failed run brings the FIGHT menu back, which counts one failed try. After ``FLEE_TRIES`` of
        them the battle is fought out.
        """
        if self.fleeing:
            # The FIGHT menu came back after a run attempt, so the escape failed.
            self.fleeing = False
            self.flee_tries += 1
            self.flees['failures'] += 1
        # A shiny the Bug-Catching Contest cannot catch is not a plain battle, and contest.control
        # owns it, so the stance sees no wild battle there.
        wild = snapshot.in_battle == 1 and (not shiny or catch or bool(self.shiny_missed))
        encounter = Encounter(wild=wild, wanted=catch, shiny=bool(self.shiny_missed), escape=escape,
                              tries=self.flee_tries)
        kind = getattr(self.goal, 'kind', STORY)
        from ..ledger import battle_ledger
        books = battle_ledger(self.data)
        if stance(kind, encounter, books, goal=getattr(self.goal, 'key', kind),
                  resources=lambda: books.snapshot(snapshot)) is not FLEE:
            return None
        action = self.battle_task(Flee(), snapshot, mem)
        if action:
            self.fleeing = True
            self.flees['attempts'] += 1
        return action

    def battle_task(self, task, snapshot, mem):
        """Start a Core battle shortcut now, or return None when the game refused it recently."""
        if not self.allowed(task, snapshot) or self.reads.battle.battle_type == 3:
            # Battle type 3 is the catching tutorial, which takes no input from the player.
            return None
        self.menu = task
        button = self.menu_step(snapshot, mem)
        if button:
            return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 28)
        if self.menu is task:
            self.menu = None
        return None

    def hopeless_battle(self, snapshot):
        """Whether a trainer battle under way can never be won.

        Nobody standing has an attack with PP that touches the foe, and each still has PP for some
        other move, so not even Struggle is left. A Vaporeon with only Rest and Growl left faced
        Lance's Gyarados this way, and Growl kept the foe from ever knocking it out. An Elixir in
        the bag would restore an attack, so the battle is not lost while one is there. A move that
        borrows another, like Transform or Metronome, may still bring an attack. A level 100 Ditto
        last in line at Koga was reloaded away before it could Transform, and once Transformed it
        was reloaded again for spending the copied attack, though Struggle was a few turns away.
        With no move that wins back HP the foe knocks everyone out in the end, so the battle ends in
        a loss. A Metapod with only Harden left at Falkner was reloaded back into the same battle.
        A healer the foe hits harder each turn than it heals is knocked out in the end too. A level 5
        Hoppip with Splash, Synthesis and Tail Whip, last in line at Chuck, was reloaded back into his
        Poliwrath's battle instead of blacking out and going to train.

        While the trainer sends out the next Pokémon the enemy slot reads species 0, so there is no
        foe to judge yet. A Silver run asked between two of Koga's Pokémon and the check crashed.
        """
        if snapshot.in_battle != 2 or snapshot.enemy_species not in self.data.species:
            return False
        from ..champion_shop import elixir
        standing = [mon for mon in snapshot.party if mon.hp and not mon.egg]
        if not standing or any(not any(mon.pp) or elixir(self.data, snapshot, mon) for mon in standing):
            return False
        # The emulator asks between presses, so the battlers come from live memory, not one decision's reads.
        memory = getattr(self, 'memory', None)
        battlers = Battlers(memory, self.data.game) if memory is not None else None
        if not any(self.outlasts(snapshot, battlers, mon) for mon in standing):
            return False
        if battlers.player.transformed:
            # A Transformed battler has five PP for each borrowed move, so Struggle is never far off.
            # Only a healer that outlasts the foe gets this far, so the battlers were read for it.
            return False
        return not any(pp and (self.move_score(move, mon, snapshot) > 0
                               or self.data.moves.get(move, {}).get('effect') in BORROWED_MOVES)
                       for mon in standing for move, pp in zip(mon.moves, mon.pp))

    def outlasts(self, snapshot, battlers, mon):
        """Whether ``mon`` wins back more HP each turn than the foe's best hit takes from it.

        Rest heals fully and then sleeps two turns, so it wins back a third of the maximum each turn.
        Recover and the other full heals win back half, Morning Sun, Synthesis and Moonlight a quarter
        at least, and Leech Seed an eighth of the foe's maximum, unless the foe is Grass. Without the
        battle memory the foe's moves are unknown, so no healer counts and the battle timeout decides.
        A scenario asks before the policy's first step, when it holds no memory yet.
        """
        heals = [(move, self.data.moves[move]['effect']) for move, pp in zip(mon.moves, mon.pp)
                 if pp and self.data.moves.get(move, {}).get('effect') in HEALING_MOVES]
        if not heals or battlers is None:
            return False
        foe = battlers.enemy
        stats = foe.stats
        grass = GRASS in self.data.species.get(snapshot.enemy_species, {}).get('types', ())

        def heal(move, effect):
            if effect == 'EFFECT_LEECH_SEED':
                return 0 if grass else stats[0] / 8
            if effect == 'EFFECT_HEAL':
                return mon.max_hp / (3 if move == REST else 2)
            return mon.max_hp / 4
        enemy = SimpleNamespace(species=snapshot.enemy_species, level=snapshot.enemy_level, stats=stats)
        target = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=mon.hp,
            enemy_defense=mon.stats[2], enemy_special_defense=mon.stats[5])
        hit = max((self.move_score(move, enemy, target) for move in foe.moves), default=0)
        return hit < max(heal(move, effect) for move, effect in heals)

    def move_choice(self, snapshot, mon, opponent, weaken):
        """The move slot to use this turn, or None when no move has PP."""
        disabled = self.reads.player.disabled_move
        options = [(self.move_score(move, mon, opponent), index)
                   for index, move in enumerate(mon.moves) if move and mon.pp[index] and move != disabled]
        if self.collection.get('tower'):
            reflected = {self.data.moves.get(move, {}).get('effect') for move in self.reads.enemy.moves}
            options = [(score * (0.1 if score < snapshot.enemy_hp
                        and ('EFFECT_COUNTER' if self.data.moves[mon.moves[index]]['type'] < 20
                             else 'EFFECT_MIRROR_COAT') in reflected else 1), index)
                       for score, index in options]
        if snapshot.in_battle == 2 and not self.collection.get('tower'):
            normal_available = any(self.data.moves.get(move, {}).get('type') == 0 and mon.pp[index]
                                   and self.move_score(move, mon, opponent) > 0
                                   for index, move in enumerate(mon.moves) if move)
            if normal_available:
                options = [(score * (0.25 if mon.pp[index] <= 5
                                    and self.data.moves[mon.moves[index]]['type'] != 0 else 1), index)
                           for score, index in options]
        recovery = self.recovery_move(snapshot, mon, options) if self.collection.get('tower') else None
        poison = self.poison_move(snapshot, mon, options) if self.collection.get('tower') else None
        for choice in (recovery, poison, weaken):
            if choice is not None:
                return choice
        return max(options)[1] if options else None

    def ball_labels(self, snapshot):
        from ..quests import beasts_roaming, static_wanted
        master = ()
        if snapshot.enemy_species in {243, 244, 245, 249, 250, 251}:
            master = ('MASTER BALL',)
            # A static legend waits for its own room, so the roaming beasts keep the Master Ball.
            if self.static_legend(snapshot) and beasts_roaming(self, snapshot):
                master = ()
        elif self.wild_shiny(snapshot) and not beasts_roaming(self, snapshot) and not static_wanted(self, snapshot):
            # A shiny may have the Master Ball once every other ball is spent, as it may never be seen
            # again, but not while a legend still to catch needs it.
            master = ('MASTER BALL',)
        regular = ('ULTRA BALL', 'GREAT BALL', 'POKé BALL', 'LURE BALL', 'FAST BALL',
                   'HEAVY BALL', 'LEVEL BALL', 'LOVE BALL', 'FRIEND BALL', 'MOON BALL')
        roaming = snapshot.enemy_species in {243, 244} or snapshot.enemy_species == 245 and self.data.game != 'crystal'
        return master + regular if roaming else regular + master

    def long_odds(self, snapshot, species, active, *, escape):
        """What a catch does when its battler cannot weaken the target and the next throw is under
        1 in 10 (planning.throws): the slot of a party member that can weaken it, LEAVE when nobody can
        and the target is untouched, or None to throw.

        A shiny, a legendary, a roamer, a one-time encounter and a contest catch always get throws, and
        so does a battle with no escape. So does a wild battle a map script started, which a run only
        meets again by talking to it, as the story does with the transmitter's Electrodes. Paralysis
        adds nothing to a Gen II throw, so a member that can only paralyze is not switched in for it.
        """
        from ...planning.throws import GEN2_BALLS, THROW_BAR, gen2_throw
        from ..ledger import ONE_CHANCE
        if self.wild_shiny(snapshot) or species in ONE_CHANCE or snapshot.bug_contest or self.reads.battle.from_script:
            return None
        held = {self.data.item_names.get(item, '').casefold() for item, count in snapshot.pockets['balls'] if count}
        ball = next((label for label in self.ball_labels(snapshot) if label.casefold() in held), None)
        if ball is None:
            return None
        rate, multiplier = self.data.species[species]['catch_rate'], GEN2_BALLS.get(ball, 1)
        enemy = self.reads.enemy
        chance = gen2_throw(rate, multiplier, snapshot.enemy_hp, snapshot.enemy_max_hp, enemy.status)
        if chance >= THROW_BAR:
            return None
        foe = SimpleNamespace(species=snapshot.enemy_species, level=snapshot.enemy_level, stats=enemy.stats)
        attacks = [move for move in enemy.moves if move]
        for slot, mon in enumerate(snapshot.party):
            if slot == active or mon.egg or mon.hp <= mon.max_hp // 2:
                continue
            # A member the target knocks out in one hit weakens nothing. A level 40 Ursaring on Route 28
            # knocked out three members of level 26 or less in turn, and the run then left it anyway.
            target = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=mon.hp,
                                     enemy_defense=mon.stats[2], enemy_special_defense=mon.stats[5])
            if max((self.move_score(move, foe, target) for move in attacks), default=0) >= mon.hp:
                continue
            move = self.capture_move(snapshot, slot=slot)
            if move is not None and self.data.moves.get(mon.moves[move], {}).get('effect') != 'EFFECT_PARALYZE':
                return slot
        untouched = chance <= gen2_throw(rate, multiplier, snapshot.enemy_max_hp, snapshot.enemy_max_hp, 0)
        return LEAVE if escape and untouched else None

    def capture_move(self, snapshot, slot=None):
        master = self.data.items['MASTER_BALL']
        if (dict(snapshot.pockets['balls']).get(master) and (self.ball_labels(snapshot)[0] == 'MASTER BALL'
                or not any(item != master and count for item, count in snapshot.pockets['balls']))):
            return None
        if not snapshot.party:
            return None
        mon = snapshot.party[min(self.reads.battle.player_slot if slot is None else slot, len(snapshot.party) - 1)]
        enemy = self.reads.enemy
        roaming = snapshot.enemy_species in {243, 244} or snapshot.enemy_species == 245 and self.data.game != 'crystal'
        if roaming and mon.stats[3] // (4 if mon.status & 64 else 1) <= enemy.stats[3]:
            return None
        if roaming:
            # Beasts flee after a faster lead moves unless the lead has Mean Looked them or they sleep.
            # Sleep is also the only status that raises the Gen II catch rate, so never paralyze or hit.
            usable = [(index, self.data.moves.get(move, {})) for index, move in enumerate(mon.moves) if mon.pp[index]]
            if not self.reads.player.holds_foe:
                trap = next((index for index, entry in usable if entry.get('effect') == 'EFFECT_MEAN_LOOK'), None)
                if trap is not None:
                    return trap
            if not enemy.status:
                sleep = [(entry['accuracy'], index) for index, entry in usable if entry.get('effect') == 'EFFECT_SLEEP'
                         and all(self.data.matchups.get((entry['type'], kind), 1)
                                 for kind in self.data.species[snapshot.enemy_species]['types'])]
                if sleep:
                    return max(sleep)[1]
            return None
        if self.static_legend(snapshot):
            return self.static_capture_move(snapshot, mon)
        if not enemy.status:
            for index, move in enumerate(mon.moves):
                entry = self.data.moves.get(move, {})
                if (mon.pp[index] and entry.get('effect') in {'EFFECT_SLEEP', 'EFFECT_PARALYZE'}
                        and all(self.data.matchups.get((entry['type'], kind), 1)
                                for kind in self.data.species[snapshot.enemy_species]['types'])):
                    return index
        if snapshot.enemy_hp <= snapshot.enemy_max_hp // 2:
            return None
        options = []
        for index, move in enumerate(mon.moves):
            entry = self.data.moves.get(move, {})
            if not mon.pp[index] or not entry.get('power') or entry.get('effect') not in {'EFFECT_NORMAL_HIT', 'EFFECT_FALSE_SWIPE'}:
                continue
            special = entry['type'] >= 20
            defense = enemy.stats[5 if special else 2]
            attack = mon.stats[4 if special else 1]
            factor = 1.5 if entry['type'] in self.data.species[mon.species]['types'] else 1
            for kind in set(self.data.species[snapshot.enemy_species]['types']):
                factor *= self.data.matchups.get((entry['type'], kind), 1)
            damage = (((2 * mon.level // 5 + 2) * entry['power'] * attack / max(1, defense)) / 50 + 2) * factor
            if entry.get('effect') == 'EFFECT_FALSE_SWIPE' or 0 < damage * 2.5 < snapshot.enemy_hp:
                options.append((damage, index))
        return max(options)[1] if options else None

    def battle_target(self, snapshot):
        enemy = self.reads.enemy
        return SimpleNamespace(enemy_species=snapshot.enemy_species, enemy_level=snapshot.enemy_level,
            enemy_hp=snapshot.enemy_hp, enemy_defense=enemy.stats[2], enemy_special_defense=enemy.stats[5])

    def level_lead(self, snapshot):
        """Move the highest-level Pokémon to the front when the lead lags well behind it."""
        from ..quests import beasts_roaming
        from ..tower import holds_lead
        from ..training import trainee_slot
        # Without an Exp. Share the partner in training leads instead, so it joins every battle.
        trainee = trainee_slot(self, snapshot)
        # The roaming-beast sleeper stays on record after the search is set aside for later, and the search
        # names it again when it resumes. On the training walk it would keep the trainee out of every battle.
        training = trainee is not None and self.goal is not None and self.goal.key == 'collection_train'
        # Once every beast is caught the search never runs again to clear its sleeper. Crystal kept a level 20
        # sleeper in front of a level 100 team, and each Sudowoodo return lost it in Victory Road and went back.
        if self.collection.get('roam_lead') and not beasts_roaming(self, snapshot):
            self.collection.pop('roam_lead')
        # A roaming-beast or static-legendary sleeper leads on purpose even when it is far below the rest of the
        # party, and so does the Tower team's chosen lead, which the Tower preparation would otherwise swap back.
        # The static-legendary sleeper also keeps the lead while the journey is still on the legendary quest
        # under another goal, and through a PC visit to free box slots, which comes and goes between quest steps.
        # Chaotic Escape swapped the sleeper and its level 100 lead back and forth for half an hour at a PC.
        sleeper = getattr(self, 'static_sleeper', None)
        storage = self.goal is not None and self.goal.key in {'collection_release', 'collection_box'}
        quest = getattr(self, 'legend_decision', None)
        questing = (quest is not None and quest == getattr(self, 'decisions', None) or storage) and not training
        if (self.collection.get('roam_lead') and not training or holds_lead(self)
                or self.goal and self.goal.key in {'legend_lugia', 'legend_ho_oh', 'legend_suicune', 'collection_static_lead'}
                or questing and sleeper and snapshot.party
                and (snapshot.party[0].trainer_id, tuple(snapshot.party[0].dvs)) == sleeper):
            return None
        if trainee is not None:
            mon = snapshot.party[trainee]
            return Lead(trainee, (mon.trainer_id, mon.dvs)) if trainee else None
        strongest = max((i for i, mon in enumerate(snapshot.party) if not mon.egg),
                        key=lambda i: snapshot.party[i].level, default=0)
        if not strongest or snapshot.party[strongest].level <= snapshot.party[0].level + 5:
            return None
        mon = snapshot.party[strongest]
        return Lead(strongest, (mon.trainer_id, mon.dvs))

    def trainee_switch(self, snapshot, active):
        """Swap a leading trainee for the strongest healthy partner when it would lose the battle.

        A switch comes before the opponent's move, and every Pokémon sent out shares the experience, so the
        trainee still levels without an Exp. Share. It only happens while the trainee is out, so it never repeats.
        """
        from ..training import trainee_slot
        if active != trainee_slot(self, snapshot) or active >= len(snapshot.party):
            return None
        mon = snapshot.party[active]
        if mon.level >= snapshot.enemy_level + 5 and mon.hp * 2 > mon.max_hp:
            return None
        healthy = [i for i, row in enumerate(snapshot.party) if i != active and not row.egg and row.hp * 4 > row.max_hp]
        best = max(healthy, key=lambda i: snapshot.party[i].level, default=None)
        return best if best is not None and snapshot.party[best].level > mon.level else None

    def tower_switch(self, snapshot, active):
        if active >= len(snapshot.party):
            return None
        foe = self.reads.enemy
        enemy = SimpleNamespace(species=snapshot.enemy_species, level=snapshot.enemy_level, stats=foe.stats)
        moves = foe.moves
        opponent = self.battle_target(snapshot)
        rows = []
        for slot, mon in enumerate(snapshot.party):
            if not mon.hp or mon.egg:
                continue
            target = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=mon.hp,
                enemy_defense=mon.stats[2], enemy_special_defense=mon.stats[5])
            received = max((self.move_score(move, enemy, target) for move in moves), default=0)
            dealt = max((self.move_score(move, mon, opponent) for move, pp in zip(mon.moves, mon.pp) if pp), default=0)
            rows.append((slot, received / mon.hp, dealt, received))
        current = next((row for row in rows if row[0] == active), None)
        if current is None:
            return None
        healing = any(self.data.moves.get(move, {}).get('effect') in {'EFFECT_HEAL', 'EFFECT_MORNING_SUN',
                      'EFFECT_MOONLIGHT', 'EFFECT_SYNTHESIS', 'EFFECT_REST'} for move in moves)
        if (healing and not foe.status and 92 not in snapshot.party[active].moves
                and not {3, 9}.intersection(self.data.species[snapshot.enemy_species]['types'])
                and current[2] * 2 < snapshot.enemy_hp):
            poison = next((slot for slot, _, _, received in rows
                           if slot != active and {92, 105} <= set(snapshot.party[slot].moves)
                           and snapshot.party[slot].pp[snapshot.party[slot].moves.index(92)]
                           and snapshot.party[slot].hp > received * 2.25), None)
            if poison is not None:
                return poison
        if current[1] < 0.65:
            return None
        def speed(mon):
            return mon.stats[3] / (4 if getattr(mon, 'status', 0) & 64 else 1)
        if current[2] >= snapshot.enemy_hp and speed(snapshot.party[active]) >= enemy.stats[3]:
            return None
        candidates = []
        for slot, danger, dealt, received in rows:
            mon = snapshot.party[slot]
            margin = 1.25 if speed(mon) >= enemy.stats[3] else 2.25
            if (slot != active and danger < current[1] * 0.65 and mon.hp > received * margin
                    and dealt >= snapshot.enemy_hp * 0.15):
                candidates.append((dealt / max(1, snapshot.enemy_hp) - danger, slot))
        return max(candidates)[1] if candidates else None

    def poison_move(self, snapshot, mon, options):
        if self.reads.enemy.status or {3, 9}.intersection(self.data.species[snapshot.enemy_species]['types']):
            return None
        if max((score for score, _ in options), default=0) * 2 >= snapshot.enemy_hp:
            return None
        return next((i for i, move in enumerate(mon.moves) if mon.pp[i]
                     and self.data.moves.get(move, {}).get('effect') == 'EFFECT_TOXIC'
                     and any(index == i for _, index in options)), None)

    def recovery_move(self, snapshot, mon, options):
        player, foe = self.reads.player, self.reads.enemy
        slot = next((i for i, move in enumerate(mon.moves) if mon.pp[i]
                     and self.data.moves.get(move, {}).get('effect') == 'EFFECT_HEAL'), None)
        if slot is None or player.disabled_move == mon.moves[slot]:
            return None
        reflected = {self.data.moves.get(move, {}).get('effect') for move in foe.moves}
        attacks = [self.data.moves.get(move, {}) for move in mon.moves if self.data.moves.get(move, {}).get('power')]
        if (foe.status & 8 and attacks
                and all(('EFFECT_COUNTER' if move['type'] < 20 else 'EFFECT_MIRROR_COAT') in reflected for move in attacks)):
            return slot
        hp, maximum = player.hp, player.stats[0]
        if not 0 < hp < maximum * 0.55 or max((score for score, _ in options), default=0) >= snapshot.enemy_hp:
            return None
        enemy = SimpleNamespace(species=snapshot.enemy_species, level=snapshot.enemy_level, stats=foe.stats)
        target = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=hp,
            enemy_defense=player.stats[2], enemy_special_defense=player.stats[5])
        damage = max((self.move_score(move, enemy, target) for move in foe.moves), default=0)
        return slot if damage < maximum / 2 else None

    def move_score(self, mid, mon, snapshot):
        move = self.data.moves.get(mid, {})
        power = move.get('power', 0)
        if not power:
            return 0
        kind = move['type']
        factor = 1
        for target_type in set(self.data.species.get(snapshot.enemy_species, {}).get('types', [])):
            factor *= self.data.matchups.get((kind, target_type), 1)
        if not factor:
            return 0
        accuracy = move.get('accuracy', 100) / 100
        effect = move.get('effect')
        if effect == 'EFFECT_STATIC_DAMAGE':
            return power * accuracy
        if effect == 'EFFECT_LEVEL_DAMAGE':
            return mon.level * accuracy
        if effect == 'EFFECT_SUPER_FANG':
            return getattr(snapshot, 'enemy_hp', 0) / 2 * accuracy
        attack = mon.stats[1 if kind < 20 else 4]
        if kind < 20 and getattr(mon, 'status', 0) & 16:
            attack /= 2
        enemy = self.data.species.get(snapshot.enemy_species, {}).get('stats', [50] * 6)
        defense = getattr(snapshot, 'enemy_defense' if kind < 20 else 'enemy_special_defense', None)
        if defense is None:
            defense = (enemy[2 if kind < 20 else 5] + 8) * 2 * getattr(snapshot, 'enemy_level', mon.level) / 100 + 5
        stab = 1.5 if kind in self.data.species[mon.species]['types'] else 1
        score = ((2 * mon.level / 5 + 2) * power * attack / max(1, defense) / 50 + 2) * factor * stab * accuracy
        if effect == 'EFFECT_MULTI_HIT':
            score *= 3
        if effect in {'EFFECT_DOUBLE_HIT', 'EFFECT_POISON_MULTI_HIT'}:
            score *= 2
        if move.get('effect') in {'EFFECT_EXPLOSION', 'EFFECT_SELFDESTRUCT'}:
            score *= 0.1
        if move.get('effect') in {'EFFECT_RECHARGE', 'EFFECT_RAZOR_WIND', 'EFFECT_SOLARBEAM'}:
            score *= 0.5
        return score
