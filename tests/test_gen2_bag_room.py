"""A full Gen II items pocket gets a spare entry put away, so a held item can come back to the bag."""
from types import SimpleNamespace

from pokesim.gen2 import ledger, training
from pokesim.gen2.menus import PutAway, Toss
from pokesim.planning.ledger import Shortfall


def spare_item(d, view):
    """The entry the ledger puts away first to free one items-pocket entry, or None."""
    books = ledger.ledger(d)
    books.snapshot(view, kinds=('items',))
    plan = books.make_room(Shortfall('collection_tidy', {'items': 1}))
    return plan[0].detail if plan else None

ITEMS = {'EXP_SHARE': 57, 'POTION': 18, 'BERRY': 173, 'LUCKY_PUNCH': 30, 'NUGGET': 15, 'DRAGON_SCALE': 151,
         'PEARL': 110, 'FIRE_STONE': 22}
PRICES = {57: 0, 18: 300, 173: 20, 30: 10, 15: 10000, 151: 2100, 110: 1400, 22: 2100}


def data():
    return SimpleNamespace(
        items=ITEMS, item_names={30: 'Lucky Punch', 173: 'Berry'},
        item_attributes={item: {'price': price, 'pocket': 'ITEM'} for item, price in PRICES.items()},
        species={1: {'evolutions': [{'method': 'trade', 'requirements': ['DRAGON_SCALE'], 'species': 2}]},
                 3: {'evolutions': [{'method': 'item', 'requirements': ['FIRE_STONE'], 'species': 4}]}})


def bag(*rows, filler=True):
    # Idle entries fill the pocket to its 20, so the given rows decide the choice when they are cheaper.
    rows = list(rows) + ([(200 + i, 1) for i in range(20 - len(rows))] if filler else [])
    return {'items': tuple(rows)}


def snapshot(pockets):
    return SimpleNamespace(pockets=pockets, items=pockets['items'], party=(), stored=())


def test_the_cheapest_entry_no_plan_uses_is_put_away():
    d = data()
    for item in range(200, 220):
        d.item_attributes[item] = {'price': 99999, 'pocket': 'ITEM'}
    view = snapshot(bag((18, 5), (151, 1), (22, 1), (173, 16), (30, 1), (15, 1)))
    # Medicine, evolution items and the share stay. Of the rest, Lucky Punch is worth least in total.
    assert spare_item(d, view) == 30
    view = snapshot(bag((18, 5), (151, 1), (22, 1), (15, 1)))
    # A Nugget sells when money runs out, so even a pricier idle item goes first.
    assert spare_item(d, view) == 200
    view = snapshot(bag((18, 5), (15, 1), (110, 1), filler=False))
    # Among valuables the cheapest goes.
    assert spare_item(d, view) == 110


def test_a_bag_of_kept_items_has_nothing_to_put_away():
    view = snapshot(bag((57, 1), (18, 5), (151, 1), (22, 1), filler=False))
    assert spare_item(data(), view) is None


class Policy:
    def __init__(self, goal, *, blocked=()):
        self.collection, self.menu, self.data = {}, None, data()
        self.goal = SimpleNamespace(key=goal)
        self.blocked = list(blocked)

    def allowed(self, task, snapshot):
        return task not in self.blocked

    def storage_goal(self, snapshot):
        return SimpleNamespace(map_name='GOLDENROD_POKECENTER_1F', x=3, y=1, face='up')


def Goal(*args):
    return SimpleNamespace(key=args[0], label=args[1], map_name=args[2])


def test_a_full_bag_walks_to_the_pc_before_the_swap():
    policy = Policy('collection_train')
    view = snapshot(bag((110, 1), (173, 16), (30, 1)))
    for item in range(200, 220):
        policy.data.item_attributes[item] = {'price': 99999, 'pocket': 'ITEM'}
    goal = ledger.tidy_goal(policy, view, Goal, 22)
    assert goal.key == 'collection_tidy' and goal.label == 'Store Lucky Punch in the PC to make room'
    assert policy.collection['tidy_item'] == 30
    # A Pearl already in the bag stacks, so it needs no free entry.
    policy.collection.clear()
    assert ledger.tidy_goal(policy, view, Goal, 110) is None and policy.collection == {}


def test_the_spare_goes_to_the_pc_or_the_bin_when_the_pc_refuses():
    policy = Policy('collection_tidy')
    policy.collection.update(training={'identity': [1, [1, 2, 3, 4, 5]]}, tidy_item=30)
    view = snapshot(bag((30, 1), (173, 16)))
    assert training.arrive(policy, view) == 'a'
    assert policy.menu == PutAway(30, 1)
    policy = Policy('collection_tidy', blocked=[PutAway(30, 1)])
    policy.collection.update(training={'identity': [1, [1, 2, 3, 4, 5]]}, tidy_item=30)
    assert training.arrive(policy, view) == 'a'
    assert policy.menu == Toss(30, 1)


def test_a_spare_already_gone_ends_the_visit():
    policy = Policy('collection_tidy')
    policy.collection.update(training={'identity': [1, [1, 2, 3, 4, 5]]}, tidy_item=30)
    assert training.arrive(policy, snapshot(bag((173, 16)))) == 'b'
    assert 'tidy_item' not in policy.collection and policy.menu is None
