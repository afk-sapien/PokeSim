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

Every change to what the worker should do is recorded first, in the adventure's turn, as its
desired state: take_control (manual), resume (autopilot) or pause, with a new generation.
Recording it starts `converge` in the background, which sends that state outside every lock.
The worker ignores a generation older than one it saw, runs a second send of the same
take_control as nothing, and answers whether it ran the change. The newest change wins however
the sends cross. The worker's answer decides what happens next:

- applied: the state is confirmed against the worker's boot. A worker that restarts says a new
  boot in its summary, and the sweep sends the state again.
- deferred: the game held it back for now, so the sweep sends it again.
- refused: a definite no, such as a trade hold. A grant, Resume or Pause from a page is undone
  and the page hears the worker's reason. Anything else is sent again less and less often.
- no answer: never guessed at. The sweep sends it again until the worker answers.

A press carries the generation of the lease it was checked against, so the library and the
worker refuse a press from a lease that has since changed hands.
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
from .supervisor import WorkerError

log = logging.getLogger(__name__)
# A page sends a heartbeat every 15 s. A hidden tab may skip a few before its lease ends.
HEARTBEAT_GRACE_SECONDS = 45
# Browsers run a hidden tab's timers about once a minute, so a waiting page may miss two.
QUEUE_GRACE_SECONDS = 150
# The holder is warned this long before an idle lease ends.
IDLE_WARNING_LEAD = 30
END_CHOICES = ('resume', 'pause')
# How long a page waits for the worker's answer, a send and one more after no answer.
ANSWER_SECONDS = 12
# How long a backup waits for every worker to confirm the end of its lease.
END_ALL_SECONDS = 10
# The sweep sends a state the worker refused again after 10 s, doubling up to 5 minutes.
REFUSED_RETRY_SECONDS = 10
REFUSED_RETRY_LIMIT = 300
# How often a settle checks whether its caller gave up, should nobody wake it.
SETTLE_CHECK_SECONDS = 1


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


@dataclass
class Desired:
    """What the worker should be doing, as the control action that gets it there."""
    action: str
    generation: int
    confirmed: bool = False
    # The worker run that confirmed it.
    boot: str | None = None
    # How many sends got an answer or none, and how the last one went.
    attempts: int = 0
    outcome: str | None = None
    detail: str = ''
    status: int | None = None
    # What a definite refusal puts back, called with the turn and `lock` held.
    undo: object = None
    undone: bool = False
    # What runs once the worker applies it, with no lock held.
    applied: object = None
    # How many definite refusals in a row, and when the sweep may send it again.
    refusals: int = 0
    retry_at: float = 0


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
        # Each adventure's desired state, the adventures with a send to it under way, and those
        # whose desired state changed during that send.
        self.desired = {}
        self.converging = set()
        self.again = set()
        # Told whenever a send gets its answer or a send thread ends.
        self.settled = threading.Condition(self.lock)
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

    def end_choice(self, aid):
        choice = self.manager.registry.setting('lease_end:' + aid)
        return choice if choice in END_CHOICES else 'resume'

    def status(self, aid, actor, adventure):
        """What one page shows: who holds control, the queue, and what this person may do."""
        role = self.role(actor, adventure)
        base = {'enforced': self.enforced, 'role': role, 'end': self.end_choice(aid)}
        with self.lock:
            desired = self.desired.get(aid)
            # A page waiting on a Pause or Resume stops waiting once this no longer names it.
            base['pending'] = (None if desired is None or desired.confirmed else
                               {'action': desired.action, 'generation': desired.generation})
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
        with self.lock:
            before = self.desired.get(aid)
        if action in {'handover', 'refuse'}:
            handler(aid, actor, adventure, target)
        else:
            handler(aid, actor, adventure)
        with self.lock:
            desired = self.desired.get(aid)
        # The page waits for the worker, so a refused grant reaches it. A release worked even if
        # the next in line was refused.
        if desired is not None and desired is not before:
            if self.answer(aid, desired) == 'refused' and desired.undone and action in {'request', 'handover', 'take'}:
                raise LeaseRefused(desired.detail or 'The adventure refused control')
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
            # The old holder hears only once the worker ran it, since a refusal gives control back.
            told = (lambda: inbox.lease_taken(self.manager, aid, lease.user_id, actor)) if lease else None
            self._grant(aid, actor.user, 'lease.take', queue=queue, applied=told)

    def touch(self, aid, actor):
        """A button press from the holder. Returns False when this person does not hold control."""
        with self.lock:
            lease = self.leases.get(aid)
            if lease is None or lease.user_id != actor.id:
                return False
            lease.last_input = lease.last_beat = self.clock()
            return True

    def end(self, aid, reason, *, apply=True, audited=False, only=None):
        """End the lease on this adventure, if any. The worker should then resume or pause, as the
        owner chose, and a lease action or the sweep sends it. Without `apply` the worker is gone,
        so it is sent nothing.

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
            if not audited:
                self.audit('lease.end', lease.user_id, aid, reason)
            # Presses checked against the ended lease are refused from here on.
            if apply:
                self.want(aid, self.end_choice(aid))
            else:
                with self.lock:
                    self.advance(aid)
                    self.desired.pop(aid, None)
            return True

    def want(self, aid, action, undo=None, applied=None):
        """Record what the worker should do next, under a new generation, and start sending it.
        Call it in the turn. `undo` puts back the state before, should the worker refuse, and
        `applied` runs once the worker ran it."""
        with self.lock:
            desired = self.desired[aid] = Desired(action, self.advance(aid), undo=undo, applied=applied)
            self.kick(aid)
            return desired

    def intended(self, aid):
        """The control action the worker should have run last, or None when there is none."""
        with self.lock:
            desired = self.desired.get(aid)
            return desired.action if desired else None

    def converge(self, aid):
        """Send the worker its desired state, outside every lock, so a hung worker holds up only
        this send. It takes the turn to read the state and to record the answer."""
        with self.lock:
            desired = self.desired.get(aid)
            if desired is None or desired.confirmed:
                return
        with self.turn(aid), self.lock:
            desired = self.desired.get(aid)
            if desired is None or desired.confirmed:
                return
        outcome, detail, status, boot = self.worker(aid, desired.action, desired.generation)
        with self.turn(aid):
            with self.lock:
                refused = told = None
                warn = False
                desired.attempts += 1
                desired.outcome, desired.detail, desired.status = outcome, detail, status
                # A newer change may have been recorded meanwhile. It is still to be sent.
                if self.desired.get(aid) is desired:
                    if outcome == 'applied':
                        # Once it ran there is nothing to put back. A later refusal of a resend
                        # to a restarted worker is retried like any other.
                        desired.confirmed, desired.boot, desired.refusals = True, boot, 0
                        desired.undo, told, desired.applied = None, desired.applied, None
                    elif outcome == 'refused' and desired.undo is not None:
                        refused, warn = self.leases.get(aid), True
                        desired.undo()
                        desired.undo, desired.undone = None, True
                        if self.leases.get(aid) is refused:
                            refused = None
                    elif outcome == 'refused':
                        desired.refusals += 1
                        warn = desired.refusals == 1
                        desired.retry_at = self.clock() + min(
                            REFUSED_RETRY_LIMIT, REFUSED_RETRY_SECONDS * 2 ** (desired.refusals - 1))
                self.settled.notify_all()
            if warn:
                log.warning('Adventure %s refused %s for the control lease with %s: %s',
                            aid, desired.action, status, detail)
            if refused is not None:
                self.audit('lease.end', refused.user_id, aid, 'refused')
        if told is not None:
            try:
                told()
            except Exception:
                log.exception('Could not tell adventure %s about its control change', aid)

    def kick(self, aid):
        """Converge in the background, one send thread per adventure. A change recorded during a
        send is sent once that send ends."""
        with self.lock:
            if aid in self.converging:
                self.again.add(aid)
                return
            self.converging.add(aid)

        def send():
            while True:
                try:
                    self.converge(aid)
                except Exception:
                    log.exception('Could not send adventure %s its control state', aid)
                with self.lock:
                    if aid not in self.again:
                        self.converging.discard(aid)
                        self.settled.notify_all()
                        return
                    self.again.discard(aid)
        threading.Thread(target=send, name='control-converge', daemon=True).start()

    def answer(self, aid, desired, timeout=ANSWER_SECONDS):
        """Wait for the worker's answer to `desired`, sending it once more when the first send got
        none, since it may have got there. Returns applied, deferred, refused, unanswered, or
        superseded when a newer change replaced it before it was sent."""
        deadline = time.monotonic() + timeout
        outcome = self._answered(aid, desired, 1, deadline)
        if outcome == 'unanswered':
            self.kick(aid)
            outcome = self._answered(aid, desired, 2, deadline)
        return outcome

    def _answered(self, aid, desired, attempts, deadline):
        with self.settled:
            while desired.attempts < attempts and self.desired.get(aid) is desired:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 'unanswered'
                self.settled.wait(remaining)
            return desired.outcome if desired.attempts >= attempts else 'superseded'

    def choose(self, aid, action, current):
        """A Resume or Pause from a page, checked against `current`, the lease read for it. It
        ends that lease and becomes the desired state, and a refusal puts both back. Returns the
        desired state, or None when control changed hands since."""
        with self.turn(aid):
            if self.current(aid) is not current:
                return None
            with self.lock:
                before = self.desired.get(aid)
            if current is not None:
                self.end(aid, action, apply=False)
            return self.want(aid, action, undo=lambda: self._restore(aid, current, before))

    def _restore(self, aid, lease, desired):
        """Put back the lease and desired state from before a change the worker refused. Called
        with the turn and `lock` held."""
        refused = self.leases.get(aid)
        if lease is None:
            self.leases.pop(aid, None)
            for entry in refused.queue if refused else ():
                self.dropped[aid, entry['user_id']] = 'ended'
        elif self.manager.suspended:
            # A backup started meanwhile and keeps every lease off until it is done. The state
            # the page chose stays desired and is sent again.
            return
        else:
            # People who joined the line meanwhile keep their place.
            known = {lease.user_id, *(entry['user_id'] for entry in lease.queue)}
            lease.queue += [entry for entry in (refused.queue if refused else ()) if entry['user_id'] not in known]
            self.leases[aid] = lease
            self.generations[aid] = lease.generation
            # Ending the lease told its line it closed. It is open again.
            for entry in [{'user_id': lease.user_id}, *lease.queue]:
                self.dropped.pop((aid, entry['user_id']), None)
        if desired is None:
            self.desired.pop(aid, None)
            return
        self.desired[aid] = desired
        if lease is None:
            self.generations[aid] = desired.generation
        if not desired.confirmed:
            self.kick(aid)

    def end_all(self, reason):
        """End every lease, including one a change already under way is about to grant, and wait
        a while for every worker to confirm it.

        Call it after setting `manager.suspended`, so later grants are refused, and never while
        holding the registry's lock.
        """
        with self.lock:
            held = list(dict.fromkeys([*self.leases, *self.turns]))
        ended = [aid for aid in held if self.end(aid, reason)]
        # Every send runs at once, so the wait is one deadline for all of them.
        deadline = time.monotonic() + END_ALL_SECONDS
        with self.settled:
            for aid in ended:
                desired = self.desired.get(aid)
                while desired is not None and not desired.confirmed and self.desired.get(aid) is desired:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        log.warning('Adventure %s has not confirmed the end of its control lease', aid)
                        break
                    self.settled.wait(remaining)
        return ended

    def settle(self, aid, deadline, cancelled=None):
        """Wait until the worker confirmed its desired state, until the monotonic `deadline`, or
        until `cancelled()` says the caller gave up. Returns whether it confirmed. Never call it
        in the turn."""
        with self.settled:
            while True:
                desired = self.desired.get(aid)
                if desired is None or desired.confirmed:
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0 or (cancelled is not None and cancelled()):
                    return False
                self.settled.wait(min(remaining, SETTLE_CHECK_SECONDS) if cancelled else remaining)

    def wake(self):
        """Wake every settle, so one whose caller gave up returns now."""
        with self.settled:
            self.settled.notify_all()

    def stop_worker(self, aid, **options):
        """Stop the adventure's worker and drop what its run was told. Every owner stop goes
        through here, so no Pause from this run follows the next Start. Returns None, and leaves
        the run alone, when `only_if_stopped` found the owner started it again."""
        row = self.manager.supervisor.stop(aid, **options)
        if row is not None:
            self.stopped(aid)
        return row

    def stopped(self, aid):
        """The owner stopped the adventure. It starts again on its autopilot, so it keeps no
        lease and no desired state for a later run to hear."""
        with self.turn(aid):
            if not self.end(aid, 'stopped', apply=False):
                with self.lock:
                    self.advance(aid)
                    self.desired.pop(aid, None)

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
        """End leases that went quiet or whose holder can no longer play, drop quiet queued pages,
        and send each worker that has not confirmed its desired state the state again. A worker
        that restarted since it confirmed forgot it, so it gets it again too."""
        self._expire()
        now = self.clock()
        with self.lock:
            for aid, desired in self.desired.items():
                if desired.confirmed and desired.boot and self.boot(aid) not in (None, desired.boot):
                    desired.confirmed = False
            # A state the worker refused waits out its backoff before it is sent again.
            unconfirmed = [(aid, desired.generation) for aid, desired in self.desired.items()
                           if not desired.confirmed and not (desired.refusals and now < desired.retry_at)]
        for aid, generation in unconfirmed:
            try:
                running = self.manager.registry.adventure(aid)['state'] == 'running'
            except KeyError:
                running = False
            if running:
                self.kick(aid)
                continue
            # A stopped adventure starts again on its autopilot.
            with self.lock:
                if getattr(self.desired.get(aid), 'generation', None) == generation:
                    self.desired.pop(aid, None)

    def boot(self, aid):
        """The worker run the supervisor last heard from in its summary, without asking it."""
        child = getattr(self.manager.supervisor, 'children', {}).get(aid)
        watch = getattr(child, 'watch', None)
        return (watch[1] or {}).get('boot') if watch else None

    def _expire(self):
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
                    # Should the worker refuse the next person, control ends as it would with nobody left.
                    self._grant(aid, user, 'lease.next', queue=queue,
                                undo=lambda: self.end(aid, 'refused', audited=True))
                    return
                except LeaseRefused:
                    self.end(aid, reason, audited=True)
                    return
            # They can no longer play, so they leave the line and their page hears why.
            with self.lock:
                lease.queue = [left for left in lease.queue if left['user_id'] != entry['user_id']]
                self.dropped[aid, entry['user_id']] = 'no_longer_allowed'
        self.end(aid, reason)

    def _grant(self, aid, user, event, queue=(), undo=None, applied=None):
        """Give control to `user`. The worker enters manual mode and drops queued presses first.
        Should it refuse, `undo` runs, or the lease and desired state from before come back.
        `applied` runs once the worker ran it."""
        blocked = self.blocked(aid)
        if blocked:
            raise LeaseRefused(blocked)
        # The old holder's presses are refused from here on, and the worker drops any queued
        # before the take_control.
        now = self.clock()
        with self.lock:
            before = self.leases.get(aid), self.desired.get(aid)
            desired = self.want(aid, 'take_control', undo=undo or (lambda: self._restore(aid, *before)),
                                applied=applied)
            self.leases[aid] = Lease(user['id'], label(user), now, now, now, list(queue), desired.generation)
        self.audit(event, user['id'], aid)

    def blocked(self, aid):
        coordinator = self.manager.coordinator
        if self.manager.suspended:
            return 'A backup is running. Try again when it finishes.'
        if coordinator.reserved(aid):
            return 'A trade holds this adventure. Control opens again when it finishes.'
        return None

    def worker(self, aid, action, generation):
        """Send one control change. Returns how it went (applied, deferred, refused or unanswered),
        the worker's words, its HTTP status and its boot."""
        try:
            reply = self.manager.supervisor.child(aid).request(
                'POST', '/api/control', {'action': action}, timeout=5, headers={LEASE_HEADER: str(generation)})
        except WorkerError as error:
            if 400 <= error.status < 500:
                # converge logs the first refusal, so a refusal sent again is not logged each time.
                return 'refused', str(error), error.status, None
            log.warning('Adventure %s answered %s for the control lease with %s: %s', aid, action, error.status, error)
            return 'unanswered', str(error), error.status, None
        except Exception as error:
            log.warning('Adventure %s did not answer %s for the control lease: %s', aid, action, error)
            return 'unanswered', str(error), None, None
        if not isinstance(reply, dict):
            return 'unanswered', 'The adventure gave no answer', None, None
        if reply.get('applied') is False:
            return 'deferred', str(reply.get('reason') or ''), None, reply.get('boot')
        return 'applied', '', None, reply.get('boot')

    def audit(self, action, uid, aid, target=None):
        try:
            self.manager.auth.audit(action, user_id=uid, adventure_id=aid, target=target)
        except Exception:
            log.exception('Could not record %s in the audit log', action)
