"""The control lease: one account at a time plays an adventure by hand.

The first request wins and later requests queue in order. The holder hands over, refuses or
lets go, and an owner or manager can always take control back. A lease ends when its page
stops sending heartbeats, when its holder stops pressing buttons, when a trade or backup
starts, or when the holder loses Can play. A queued page sends heartbeats too, and leaves the
queue when it stops. Leases live in memory, and every change goes to the audit log, so a
manager restart drops them and startup puts the autopilot back.

Two locks keep a slow worker from stalling every page. `lock` guards the leases and is never
held across a worker request. Each adventure's turn lock lines up the changes that ask its
worker, so a hung worker holds up only its own adventure. A turn is always taken before `lock`,
and before the registry's lock, so nobody may end a lease while holding the registry's lock.

Each grant and end gives the adventure a new generation before its worker hears of it. A press
carries the generation of the lease it was checked against, so the library and the worker
refuse a press from a lease that has since changed hands.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import itertools
import logging
import os
import threading
import time

from ..web.security import LEASE_HEADER
from . import inbox
from .policy import can

log = logging.getLogger(__name__)
# A page sends a heartbeat every 15 s. A hidden tab may skip a few before its lease ends.
HEARTBEAT_GRACE_SECONDS = 45
# Browsers run a hidden tab's timers about once a minute, so a waiting page may miss two.
QUEUE_GRACE_SECONDS = 150
# The holder is warned this long before an idle lease ends.
IDLE_WARNING_LEAD = 30
END_CHOICES = ('resume', 'pause')


def idle_limit():
    try:
        return max(30, int(os.environ.get('CONTROL_IDLE_SECONDS', '120')))
    except ValueError:
        return 120


class LeaseRefused(ValueError):
    """A lease request that cannot be granted, with the reason to show."""


@dataclass
class Lease:
    user_id: str
    name: str
    since: float
    last_input: float
    last_beat: float
    queue: list = field(default_factory=list)
    generation: int = 0


def label(user):
    return user.get('display_name') or user['username']


class Leases:
    def __init__(self, manager, clock=time.monotonic):
        self.manager = manager
        self.clock = clock
        self.lock = threading.RLock()
        self.leases = {}
        # Each adventure's turn lock and how many threads hold or wait for it.
        self.turns = {}
        # People who left a line without asking, with the reason, until their page hears it.
        self.dropped = {}
        # Each adventure's newest generation. The count never repeats, so a worker that kept an
        # old one never mistakes it for a new one.
        self.generations = {}
        self.counter = itertools.count(1)
        # Adventures whose worker did not answer whether it made a control change, with the
        # change that puts it back once it answers again (see reconcile).
        self.unsettled = {}
        self.stop = threading.Event()

    @property
    def enforced(self):
        """Leases apply under accounts. Under AUTH=none Take Control works as it always has."""
        return self.manager.auth_mode == 'accounts'

    @contextmanager
    def turn(self, aid):
        """Line up the lease changes of one adventure. The lock goes once nobody uses it and no lease is left."""
        with self.lock:
            entry = self.turns.setdefault(aid, [threading.RLock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self.lock:
                entry[1] -= 1
                if not entry[1] and aid not in self.leases:
                    self.turns.pop(aid, None)

    def waiting(self, aid, lease, now):
        """Drop the queued pages that went quiet and return who is left. Called with `lock` held."""
        for entry in lease.queue:
            if now - entry['beat'] > QUEUE_GRACE_SECONDS:
                self.dropped[aid, entry['user_id']] = 'quiet'
        lease.queue = [entry for entry in lease.queue if now - entry['beat'] <= QUEUE_GRACE_SECONDS]
        return list(lease.queue)

    # Reading ----------------------------------------------------------------------------
    def holder(self, aid):
        with self.lock:
            lease = self.leases.get(aid)
            return lease.user_id if lease else None

    def current(self, aid):
        """The lease itself, to end later only if it is still the same one."""
        with self.lock:
            return self.leases.get(aid)

    def holds(self, aid, actor):
        return actor.id is not None and self.holder(aid) == actor.id

    def generation(self, aid):
        """The adventure's newest generation. Safe to read on the event loop: it takes no lock."""
        return self.generations.get(aid, 0)

    def stamp(self, aid, actor):
        """The generation a press from `actor` carries, or None when they do not hold control."""
        with self.lock:
            lease = self.leases.get(aid)
            if lease is None or actor.id is None or lease.user_id != actor.id:
                return None
            return lease.generation

    def advance(self, aid):
        """Start a new generation, before the worker hears of a change."""
        with self.lock:
            generation = self.generations[aid] = next(self.counter)
            return generation

    def reserve(self):
        """A generation for a change the worker has yet to make. Presses keep theirs until it does."""
        with self.lock:
            return next(self.counter)

    def restamp(self, aid, lease, generation):
        """A change the worker may have made without answering: the library starts its generation
        too, and the lease still in control carries it, so both sides agree."""
        with self.lock:
            self.generations[aid] = max(self.generations.get(aid, 0), generation)
            if lease is not None and self.leases.get(aid) is lease:
                lease.generation = self.generations[aid]

    def end_choice(self, aid):
        choice = self.manager.registry.setting('lease_end:' + aid)
        return choice if choice in END_CHOICES else 'resume'

    def status(self, aid, actor, adventure):
        """What one page shows: who holds control, the queue, and what this person may do."""
        role = self.role(actor, adventure)
        base = {'enforced': self.enforced, 'role': role, 'end': self.end_choice(aid)}
        if not self.enforced:
            return {**base, 'holder': None, 'you_hold': False, 'queue': [], 'queued': False}
        now = self.clock()
        with self.lock:
            # A page that fell out of the line hears why once, so it can say so.
            left = self.dropped.pop((aid, actor.id), None)
            if left:
                base['left_line'] = left
            lease = self.leases.get(aid)
            if lease is None:
                return {**base, 'holder': None, 'you_hold': False, 'queue': [], 'queued': False}
            mine = actor.id == lease.user_id
            ends_in = max(0, int(idle_limit() - (now - lease.last_input)))
            # Watchers see who holds control. The queue names people only to those who decide on it.
            sees_queue = mine or role in {'manager', 'owner'}
            return {**base, 'holder': {'name': lease.name, **({'id': lease.user_id} if sees_queue else {})},
                    'you_hold': mine, 'idle_ends_in': ends_in if mine else None,
                    'idle_warning': mine and ends_in <= IDLE_WARNING_LEAD,
                    'queued': any(entry['user_id'] == actor.id for entry in lease.queue),
                    'queue': [{'id': entry['user_id'], 'name': entry['name']} for entry in lease.queue] if sees_queue else
                             [{'name': entry['name']} for entry in lease.queue if entry['user_id'] == actor.id]}

    @staticmethod
    def role(actor, adventure):
        from .policy import adventure_role
        return adventure_role(actor, adventure)

    # Changing ---------------------------------------------------------------------------
    def act(self, aid, actor, adventure, action, target=None):
        """One lease action from a page. Returns the new status."""
        if not self.enforced:
            raise LeaseRefused('Take Control needs no lease when PokeSim has no accounts')
        if actor.user is None:
            raise PermissionError('Only an account can hold control')
        handler = {'request': self.request, 'release': self.release, 'heartbeat': self.heartbeat,
                   'handover': self.handover, 'refuse': self.refuse, 'take': self.take}.get(action)
        if handler is None:
            raise ValueError('Unknown lease action')
        if action in {'handover', 'refuse'}:
            handler(aid, actor, adventure, target)
        else:
            handler(aid, actor, adventure)
        return self.status(aid, actor, adventure)

    def request(self, aid, actor, adventure):
        if not can(actor, 'adventure.play', adventure):
            raise PermissionError('You can watch this adventure but not play it')
        with self.turn(aid):
            with self.lock:
                self.dropped.pop((aid, actor.id), None)
                lease = self.leases.get(aid)
                if lease is not None:
                    if lease.user_id == actor.id or any(entry['user_id'] == actor.id for entry in lease.queue):
                        return
                    lease.queue.append({'user_id': actor.id, 'name': label(actor.user), 'at': time.time(),
                                        'beat': self.clock()})
                    holder = lease.user_id
            if lease is None:
                self._grant(aid, actor.user, 'lease.grant')
                return
            self.audit('lease.request', actor.id, aid)
        inbox.lease_requested(self.manager, aid, holder, actor)

    def release(self, aid, actor, adventure):
        """The holder lets go, which passes control to the next in line. A queued person leaves the queue."""
        with self.turn(aid):
            with self.lock:
                lease = self.leases.get(aid)
                if lease is None:
                    return
                if lease.user_id != actor.id:
                    lease.queue = [entry for entry in lease.queue if entry['user_id'] != actor.id]
                    return
            self._pass_on(aid, lease, 'release')

    def heartbeat(self, aid, actor, adventure):
        """The holder's page, or a queued page, is still open."""
        with self.lock:
            lease = self.leases.get(aid)
            if lease is not None:
                if lease.user_id == actor.id:
                    lease.last_beat = self.clock()
                    return
                entry = next((entry for entry in lease.queue if entry['user_id'] == actor.id), None)
                if entry is not None:
                    entry['beat'] = self.clock()
                    return
            raise LeaseRefused('You do not hold control of this adventure')

    def handover(self, aid, actor, adventure, target):
        with self.turn(aid):
            with self.lock:
                lease = self.leases.get(aid)
                if lease is None or lease.user_id != actor.id:
                    raise LeaseRefused('You do not hold control of this adventure')
                entry = next((entry for entry in lease.queue if entry['user_id'] == target), None)
                if entry is None:
                    raise LeaseRefused('That person is not waiting for control')
            user = self.playable(target, adventure)
            if user is None:
                with self.lock:
                    lease.queue = [row for row in lease.queue if row is not entry]
                    self.dropped[aid, target] = 'no_longer_allowed'
                raise LeaseRefused('That person can no longer play this adventure')
            with self.lock:
                queue = [row for row in lease.queue if row is not entry]
            self._grant(aid, user, 'lease.handover', queue=queue)

    def refuse(self, aid, actor, adventure, target):
        with self.turn(aid), self.lock:
            lease = self.leases.get(aid)
            if lease is None or not (lease.user_id == actor.id or can(actor, 'adventure.manage', adventure)):
                raise LeaseRefused('You do not hold control of this adventure')
            before = len(lease.queue)
            lease.queue = [entry for entry in lease.queue if entry['user_id'] != target]
            if len(lease.queue) != before:
                self.dropped[aid, target] = 'refused'
                self.audit('lease.refuse', actor.id, aid, target)

    def take(self, aid, actor, adventure):
        """An owner or manager takes control at once, whoever holds it."""
        if not can(actor, 'adventure.manage', adventure):
            raise PermissionError('Only an owner or manager can take control back')
        with self.turn(aid):
            with self.lock:
                lease = self.leases.get(aid)
                if lease is not None and lease.user_id == actor.id:
                    return
                queue = [entry for entry in lease.queue if entry['user_id'] != actor.id] if lease else []
            self._grant(aid, actor.user, 'lease.take', queue=queue)
        if lease is not None:
            inbox.lease_taken(self.manager, aid, lease.user_id, actor)

    def touch(self, aid, actor):
        """A button press from the holder. Returns False when this person does not hold control."""
        with self.lock:
            lease = self.leases.get(aid)
            if lease is None or lease.user_id != actor.id:
                return False
            lease.last_input = lease.last_beat = self.clock()
            return True

    def end(self, aid, reason, *, apply=True, audited=False, only=None):
        """End the lease on this adventure, if any, and put the autopilot back or keep it paused.

        With `only`, end it only while that same lease still holds control, not one granted since.
        """
        with self.turn(aid):
            with self.lock:
                if only is not None and self.leases.get(aid) is not only:
                    return False
                lease = self.leases.pop(aid, None)
                # The line goes with the lease, and each page still in it hears so once.
                for entry in lease.queue if lease else ():
                    self.dropped[aid, entry['user_id']] = 'ended'
            if lease is None:
                return False
            # Presses checked against the ended lease are refused from here on.
            generation = self.advance(aid)
            if not audited:
                self.audit('lease.end', lease.user_id, aid, reason)
            if apply:
                self.worker(aid, 'pause' if self.end_choice(aid) == 'pause' else 'resume', generation)
            return True

    def end_all(self, reason):
        """End every lease, including one a change already under way is about to grant.

        Call it after setting `manager.suspended`, so later grants are refused, and never while
        holding the registry's lock.
        """
        with self.lock:
            held = list(dict.fromkeys([*self.leases, *self.turns]))
        return [aid for aid in held if self.end(aid, reason)]

    def forget(self, aid, uid):
        """A grant, user or session went away: end their lease and drop their requests."""
        with self.turn(aid):
            with self.lock:
                self.dropped.pop((aid, uid), None)
                lease = self.leases.get(aid)
                if lease is None:
                    return
                if lease.user_id != uid:
                    lease.queue = [entry for entry in lease.queue if entry['user_id'] != uid]
                    return
            self._pass_on(aid, lease, 'revoked')

    def sweep(self):
        """End leases that went quiet or whose holder can no longer play, and drop quiet queued pages."""
        with self.lock:
            held = list(self.leases)
        for aid in held:
            with self.turn(aid):
                now = self.clock()
                with self.lock:
                    lease = self.leases.get(aid)
                    if lease is None:
                        continue
                    self.waiting(aid, lease, now)
                try:
                    adventure = self.manager.registry.adventure(aid)
                except KeyError:
                    self.end(aid, 'deleted', apply=False)
                    continue
                if adventure['state'] != 'running':
                    self.end(aid, 'stopped', apply=False)
                elif self.playable(lease.user_id, adventure) is None:
                    self._pass_on(aid, lease, 'revoked')
                elif now - lease.last_beat > HEARTBEAT_GRACE_SECONDS:
                    self._pass_on(aid, lease, 'heartbeat')
                elif now - lease.last_input > idle_limit():
                    self._pass_on(aid, lease, 'idle')

    def run(self, interval=5):
        def loop():
            while not self.stop.wait(interval):
                try:
                    self.sweep()
                    self.settle()
                except Exception:
                    log.exception('The control lease sweep failed')
        threading.Thread(target=loop, name='control-lease', daemon=True).start()

    def close(self):
        self.stop.set()

    # Inside the adventure's turn ---------------------------------------------------------
    def playable(self, uid, adventure):
        """This user, when they may still hold control of this adventure."""
        user = self.manager.auth.user(uid)
        if user is None or user['disabled'] or user['placeholder']:
            return None
        return user if can(self.manager.actor_for(user), 'adventure.play', adventure) else None

    def _pass_on(self, aid, lease, reason):
        """Give control to the next person in line who can still play, or end the lease."""
        try:
            adventure = self.manager.registry.adventure(aid)
        except KeyError:
            # The adventure was deleted. Its line hears so, and there is no worker to resume.
            self.end(aid, 'deleted', apply=False)
            return
        now = self.clock()
        with self.lock:
            queue = self.waiting(aid, lease, now)
        while queue:
            entry = queue.pop(0)
            user = self.playable(entry['user_id'], adventure)
            if user is not None:
                self.audit('lease.end', lease.user_id, aid, reason)
                try:
                    self._grant(aid, user, 'lease.next', queue=queue)
                    return
                except LeaseRefused:
                    self.end(aid, reason, audited=True)
                    return
            # They can no longer play, so they leave the line and their page hears why.
            with self.lock:
                lease.queue = [left for left in lease.queue if left['user_id'] != entry['user_id']]
                self.dropped[aid, entry['user_id']] = 'no_longer_allowed'
        self.end(aid, reason)

    def _grant(self, aid, user, event, queue=()):
        """Give control to `user`. The worker enters manual mode and drops queued presses first."""
        blocked = self.blocked(aid)
        if blocked:
            raise LeaseRefused(blocked)
        # The new generation starts once the worker answered, so the old holder's presses still go
        # out meanwhile, and the worker drops any that reach it after the take_control. One that
        # failed or timed out may still have reached the worker, so the worker says what it did.
        generation = self.reserve()
        if not self.worker(aid, 'take_control', generation):
            generation = self.reconcile(aid, 'take_control', generation)
            if generation is None:
                raise LeaseRefused('The adventure is busy with a trade or did not answer. Try again in a moment.')
        now = self.clock()
        with self.lock:
            self.generations[aid] = generation
            self.leases[aid] = Lease(user['id'], label(user), now, now, now, list(queue), generation)
        self.audit(event, user['id'], aid)

    def reconcile(self, aid, action, reserved):
        """A take_control, resume or pause sent with `reserved` got no answer. Ask the worker
        whether it made the change, and make the lease match the worker. Call it in the turn.

        Returns the generation to carry on with when the worker made the change, else None. A
        take_control it made leaves the caller to record the new lease. A worker in manual mode
        keeps the lease that holds it, or resumes when nobody does, and a worker back on its
        autopilot ends the lease.
        """
        fence = self.reserve()
        try:
            state = self.manager.supervisor.child(aid).request(
                'POST', '/internal/control-status', {}, timeout=5, headers={LEASE_HEADER: str(fence)})
            applied = int(state['lease_seen']) >= reserved
            manual = action == 'take_control' if applied else bool(state['manual'])
        except Exception as error:
            # Nobody knows what the game is doing, so nobody keeps control, and the game gets
            # the autopilot back once its worker answers again (see settle).
            log.warning('Adventure %s did not say whether it made %s: %s', aid, action, error)
            with self.lock:
                self.unsettled[aid] = 'pause' if action == 'pause' else 'resume'
            self.end(aid, 'unanswered', apply=False)
            return None
        # The worker refuses anything older than the fence now, so the library starts it too.
        with self.lock:
            self.generations[aid] = max(self.generations.get(aid, 0), fence)
        if applied and action == 'take_control':
            return fence
        lease = self.current(aid)
        if manual and lease is not None:
            self.restamp(aid, lease, fence)
        elif manual:
            # Paused for a player nobody is: the game plays on by itself.
            if not self.worker(aid, 'resume', self.advance(aid)):
                with self.lock:
                    self.unsettled[aid] = 'resume'
        elif lease is not None:
            self.end(aid, action if applied else 'autopilot', apply=False)
        return fence if applied else None

    def settle(self):
        """Send each worker that went unanswered the change that puts it back, once it answers."""
        with self.lock:
            unsettled = list(self.unsettled.items())
        for aid, action in unsettled:
            with self.turn(aid):
                with self.lock:
                    if self.unsettled.get(aid) != action:
                        continue
                    if aid in self.leases:
                        # Control was granted since, so the worker answered and is in manual mode.
                        self.unsettled.pop(aid, None)
                        continue
                try:
                    running = self.manager.registry.adventure(aid)['state'] == 'running'
                except KeyError:
                    running = False
                # A stopped adventure starts again on its autopilot.
                if not running or self.worker(aid, action, self.advance(aid)):
                    with self.lock:
                        self.unsettled.pop(aid, None)

    def blocked(self, aid):
        coordinator = self.manager.coordinator
        if self.manager.suspended:
            return 'A backup is running. Try again when it finishes.'
        if coordinator.reserved(aid):
            return 'A trade holds this adventure. Control opens again when it finishes.'
        return None

    def worker(self, aid, action, generation):
        try:
            self.manager.supervisor.child(aid).request('POST', '/api/control', {'action': action}, timeout=5,
                                                       headers={LEASE_HEADER: str(generation)})
            return True
        except Exception as error:
            log.warning('Adventure %s refused %s for the control lease: %s', aid, action, error)
            return False

    def audit(self, action, uid, aid, target=None):
        try:
            self.manager.auth.audit(action, user_id=uid, adventure_id=aid, target=target)
        except Exception:
            log.exception('Could not record %s in the audit log', action)
