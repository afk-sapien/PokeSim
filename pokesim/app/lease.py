"""The control lease: one account at a time plays an adventure by hand.

The first request wins and later requests queue in order. The holder hands over, refuses or
lets go, and an owner or manager can always take control back. A lease ends when its page
stops sending heartbeats, when its holder stops pressing buttons, when a trade or backup
starts, or when the holder loses Can play. Leases live in memory, and every change goes to
the audit log, so a manager restart drops them and startup puts the autopilot back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import threading
import time

from .policy import can

log = logging.getLogger(__name__)
# A page sends a heartbeat every 15 s. A hidden tab may skip a few before its lease ends.
HEARTBEAT_GRACE_SECONDS = 45
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


def label(user):
    return user.get('display_name') or user['username']


class Leases:
    def __init__(self, manager, clock=time.monotonic):
        self.manager = manager
        self.clock = clock
        self.lock = threading.RLock()
        self.leases = {}
        self.stop = threading.Event()

    @property
    def enforced(self):
        """Leases apply under accounts. Under AUTH=none Take Control works as it always has."""
        return self.manager.auth_mode == 'accounts'

    # Reading ----------------------------------------------------------------------------
    def holder(self, aid):
        with self.lock:
            lease = self.leases.get(aid)
            return lease.user_id if lease else None

    def holds(self, aid, actor):
        return actor.id is not None and self.holder(aid) == actor.id

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
        with self.lock:
            lease = self.leases.get(aid)
            if lease is not None:
                if lease.user_id != actor.id and all(entry['user_id'] != actor.id for entry in lease.queue):
                    lease.queue.append({'user_id': actor.id, 'name': label(actor.user), 'at': time.time()})
                    self.audit('lease.request', actor.id, aid)
                return
            self._grant(aid, actor.user, 'lease.grant')

    def release(self, aid, actor, adventure):
        """The holder lets go, which passes control to the next in line. A queued person leaves the queue."""
        with self.lock:
            lease = self.leases.get(aid)
            if lease is None:
                return
            if lease.user_id != actor.id:
                lease.queue = [entry for entry in lease.queue if entry['user_id'] != actor.id]
                return
            self._pass_on(aid, lease, 'release')

    def heartbeat(self, aid, actor, adventure):
        with self.lock:
            lease = self.leases.get(aid)
            if lease is None or lease.user_id != actor.id:
                raise LeaseRefused('You do not hold control of this adventure')
            lease.last_beat = self.clock()

    def handover(self, aid, actor, adventure, target):
        with self.lock:
            lease = self.leases.get(aid)
            if lease is None or lease.user_id != actor.id:
                raise LeaseRefused('You do not hold control of this adventure')
            entry = next((entry for entry in lease.queue if entry['user_id'] == target), None)
            if entry is None:
                raise LeaseRefused('That person is not waiting for control')
            user = self.playable(target, adventure)
            if user is None:
                lease.queue.remove(entry)
                raise LeaseRefused('That person can no longer play this adventure')
            queue = [row for row in lease.queue if row is not entry]
            self._grant(aid, user, 'lease.handover', queue=queue)

    def refuse(self, aid, actor, adventure, target):
        with self.lock:
            lease = self.leases.get(aid)
            if lease is None or not (lease.user_id == actor.id or can(actor, 'adventure.manage', adventure)):
                raise LeaseRefused('You do not hold control of this adventure')
            before = len(lease.queue)
            lease.queue = [entry for entry in lease.queue if entry['user_id'] != target]
            if len(lease.queue) != before:
                self.audit('lease.refuse', actor.id, aid, target)

    def take(self, aid, actor, adventure):
        """An owner or manager takes control at once, whoever holds it."""
        if not can(actor, 'adventure.manage', adventure):
            raise PermissionError('Only an owner or manager can take control back')
        with self.lock:
            lease = self.leases.get(aid)
            if lease is not None and lease.user_id == actor.id:
                return
            queue = [entry for entry in lease.queue if entry['user_id'] != actor.id] if lease else []
            self._grant(aid, actor.user, 'lease.take', queue=queue)

    def touch(self, aid, actor):
        """A button press from the holder. Returns False when this person does not hold control."""
        with self.lock:
            lease = self.leases.get(aid)
            if lease is None or lease.user_id != actor.id:
                return False
            lease.last_input = lease.last_beat = self.clock()
            return True

    def end(self, aid, reason, *, apply=True):
        """End the lease on this adventure, if any, and put the autopilot back or keep it paused."""
        with self.lock:
            lease = self.leases.pop(aid, None)
            if lease is None:
                return False
            self.audit('lease.end', lease.user_id, aid, reason)
            if apply:
                self.worker(aid, 'pause' if self.end_choice(aid) == 'pause' else 'resume')
            return True

    def end_all(self, reason):
        with self.lock:
            return [aid for aid in list(self.leases) if self.end(aid, reason)]

    def forget(self, aid, uid):
        """A grant, user or session went away: end their lease and drop their requests."""
        with self.lock:
            lease = self.leases.get(aid)
            if lease is None:
                return
            if lease.user_id == uid:
                self._pass_on(aid, lease, 'revoked')
            else:
                lease.queue = [entry for entry in lease.queue if entry['user_id'] != uid]

    def sweep(self):
        """End leases that went quiet or whose holder can no longer play."""
        now = self.clock()
        with self.lock:
            for aid, lease in list(self.leases.items()):
                try:
                    adventure = self.manager.registry.adventure(aid)
                except KeyError:
                    self.leases.pop(aid, None)
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

    # Inside the lock ---------------------------------------------------------------------
    def playable(self, uid, adventure):
        """This user, when they may still hold control of this adventure."""
        user = self.manager.auth.user(uid)
        if user is None or user['disabled'] or user['placeholder']:
            return None
        return user if can(self.manager.actor_for(user), 'adventure.play', adventure) else None

    def _pass_on(self, aid, lease, reason):
        """Give control to the next person in line who can still play, or end the lease."""
        adventure = self.manager.registry.adventure(aid)
        queue = list(lease.queue)
        while queue:
            entry = queue.pop(0)
            user = self.playable(entry['user_id'], adventure)
            if user is not None:
                self.audit('lease.end', lease.user_id, aid, reason)
                try:
                    self._grant(aid, user, 'lease.next', queue=queue)
                    return
                except LeaseRefused:
                    break
        self.leases[aid] = lease
        self.end(aid, reason)

    def _grant(self, aid, user, event, queue=()):
        """Give control to `user`. The worker enters manual mode and drops queued presses first."""
        blocked = self.blocked(aid)
        if blocked:
            raise LeaseRefused(blocked)
        if not self.worker(aid, 'take_control'):
            raise LeaseRefused('The adventure is busy with a trade or did not answer. Try again in a moment.')
        now = self.clock()
        self.leases[aid] = Lease(user['id'], label(user), now, now, now, list(queue))
        self.audit(event, user['id'], aid)

    def blocked(self, aid):
        coordinator = self.manager.coordinator
        if self.manager.suspended:
            return 'A backup is running. Try again when it finishes.'
        if coordinator.reserved(aid):
            return 'A trade holds this adventure. Control opens again when it finishes.'
        return None

    def worker(self, aid, action):
        try:
            self.manager.supervisor.child(aid).request('POST', '/api/control', {'action': action}, timeout=5)
            return True
        except Exception as error:
            log.warning('Adventure %s refused %s for the control lease: %s', aid, action, error)
            return False

    def audit(self, action, uid, aid, target=None):
        try:
            self.manager.auth.audit(action, user_id=uid, adventure_id=aid, target=target)
        except Exception:
            log.exception('Could not record %s in the audit log', action)
