"""Run the policy's menu tasks and count the shortcuts the game refuses."""
from __future__ import annotations

from ...runtime.supervision import REFUSED_SHORTCUT
from ..menus import MAX_STEPS, RADIO_MAX_STEPS, SLOT_MAX_STEPS, Release, Remedy, Storage


class MenuPart:
    """Menu tasks and refused shortcuts."""

    MENU_STEP_LIMIT = MAX_STEPS
    MENU_STEP_LIMITS = {'Radio': RADIO_MAX_STEPS, 'Slots': SLOT_MAX_STEPS}

    def menu_step(self, snapshot, mem):
        """Run the current menu task, giving up when it takes implausibly many steps."""
        menu = self.menu
        name = type(menu).__name__
        if menu is not self.menu_ref:
            self.menu_ref, self.menu_steps = menu, 0
            if hasattr(menu, 'key') and self.blocked.get(menu.key(), -1) > self.clock:
                # The game refused this shortcut recently, so it is not tried again yet.
                return self.refused(f'The game keeps refusing the {name} shortcut')
            from ..release import may_release
            if isinstance(menu, Release) and not may_release(self, snapshot, menu.box, menu.position):
                # The one release rule refuses it, as a team member or a Keep, so it waits as a refused shortcut.
                self.blocked[self.task_key(menu)] = REFUSED_SHORTCUT.until(self.clock)
                self.menu = None
                return self.refused('A release chose a Pokémon the PC values keep')
        self.menu_steps += 1
        limit = self.MENU_STEP_LIMITS.get(name, self.MENU_STEP_LIMIT)
        if self.menu_steps > limit:
            self.fail(f'The {name} menu task made no progress after {limit} steps')
            return None
        button = menu.step(snapshot, mem)
        failure = getattr(menu, 'failure', '')
        if failure:
            # A Game Corner task saw its screen stop changing and failed itself.
            self.fail(failure)
            return None
        result = getattr(menu, 'result', None)
        if result is not None and menu is not self.result_ref:
            self.result_ref = menu
            if result.completed:
                self.refused_in_row = 0
            elif getattr(menu, 'battle', False) and not isinstance(menu, Remedy) and not snapshot.in_battle:
                pass  # The battle ended under the shortcut, which is no refusal.
            elif not getattr(menu, 'box_full', False):
                self.blocked[self.task_key(menu)] = REFUSED_SHORTCUT.until(self.clock)
                if len(self.blocked) > 64:
                    self.blocked = {key: frame for key, frame in self.blocked.items() if frame > self.clock}
                self.refused(f'The game keeps refusing the {name} shortcut')
                if self.menu is not menu:
                    return None
        return button

    REFUSAL_LIMIT = 20

    @staticmethod
    def task_key(menu):
        key = getattr(menu, 'key', None)
        return key() if key else (type(menu).__name__,)

    def allowed(self, task, snapshot):
        """Whether the game has not refused this shortcut recently, and its PC list can reach the slot.

        Without the stack pointer a nickname holding a text command can stop Bill's PC list, so
        pc_list guards every release and withdrawal in that box.
        """
        if getattr(self, 'sp', None) is None and self.unlisted_box(task, snapshot):
            return False
        return self.blocked.get(self.task_key(task), -1) <= self.clock

    @staticmethod
    def unlisted_box(task, snapshot):
        from ...pc_list import gen2_unlisted_boxes
        if isinstance(task, Release):
            box = task.box
        elif isinstance(task, Storage) and task.operation != 'DEPOSIT':
            box = getattr(snapshot, 'active_box', None)
        else:
            return False
        return box in gen2_unlisted_boxes(getattr(snapshot, 'stored', ()))

    def refused(self, reason):
        """Count a refusal. Many in a row mean the plan keeps asking for something impossible."""
        self.refused_in_row += 1
        if self.refused_in_row > self.REFUSAL_LIMIT:
            self.refused_in_row = 0
            self.fail(reason)
        return None
