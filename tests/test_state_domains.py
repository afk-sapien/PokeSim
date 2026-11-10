"""Every kv key the package uses is declared once in pokesim/state/domains.py, with its life.

The scan reads each key where it is used: the first argument of a store's ``get`` and ``set``, and
the key placeholders and quoted keys of SQL on the kv table. A name is followed to its string
through local assignments, loops over literal tuples, module constants, imports and subscripts of
literal tables. A parameter is followed to the arguments of the calls in its own module.
"""
import ast
from pathlib import Path
import re

import pytest

from pokesim.state import domains, schema

PACKAGE = Path(__file__).resolve().parents[1] / 'pokesim'
# The store's own get and set take any key. The calls to them are where the keys are named.
GENERIC = {('pokesim.store', 'get'), ('pokesim.store', 'set')}
STORE = re.compile(r'(?:^|[._])store$')
KV = re.compile(r'\bkv\b')
KEY_BEFORE = re.compile(r'(?:INSERT(?:\s+OR\s+\w+)?\s+INTO\s+kv\s*(?:\(\s*k\s*,\s*v\s*\))?\s*VALUES\s*\(\s*'
                        r'|\bk\s*=\s*|\bk\s+IN\s*\((?:\s*\?\s*,)*\s*)$', re.I)
LIKE_BEFORE = re.compile(r'(?:\bk\s+(?:NOT\s+)?LIKE\s*|substr\(\s*k\s*,\s*1\s*,\s*\?\s*\)\s*=\s*)$', re.I)
QUOTED_KEY = re.compile(r"\bk\s*=\s*'([^']*)'")
QUOTED_LIKE = re.compile(r"\bk\s+(?:NOT\s+)?LIKE\s*'([^']*)'", re.I)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class Unresolved(Exception):
    pass


def sql(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return ''.join(part.value if isinstance(part, ast.Constant) else ' ' for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return sql(node.left) + sql(node.right)
    return ''


def own(scope):
    """The nodes of a function body, without the bodies of the functions and classes inside it."""
    pending = list(scope.body) if isinstance(scope.body, list) else [scope.body]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, SCOPES))


def like(found):
    """A LIKE pattern names the keys that start with its text before the first %."""
    return [('prefix', text.split('%')[0]) for _, text in found]


class Module:
    def __init__(self, package, name, path, tree):
        self.package, self.name, self.path, self.tree = package, name, path, tree
        self.parent = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        self.constants = {target.id: node.value for node in tree.body if isinstance(node, ast.Assign)
                          for target in node.targets if isinstance(target, ast.Name)}
        base = name if path.name == '__init__.py' else name.rpartition('.')[0]
        self.imports = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                source = base
                for _ in range(max(node.level - 1, 0)):
                    source = source.rpartition('.')[0]
                source = (source + '.' + node.module if node.module else source) if node.level else node.module
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = (source, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self.imports[alias.asname] = (alias.name, None)

    def where(self, node):
        return f'{self.path.relative_to(self.package.root.parent)}:{node.lineno}'

    def scope(self, node):
        node = self.parent.get(node)
        while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            node = self.parent.get(node)
        return node

    def imported(self, name):
        """The module and constant name a local name was imported as, if it came from the package."""
        if name not in self.imports:
            return None, None
        source, attr = self.imports[name]
        if attr and source + '.' + attr in self.package.modules:
            return self.package.modules[source + '.' + attr], None
        return self.package.modules.get(source), attr

    def constant(self, node):
        """The module that defines a module level Name or module.NAME, and the value it assigns."""
        if isinstance(node, ast.Name):
            if node.id in self.constants:
                return self, self.constants[node.id]
            module, attr = self.imported(node.id)
            if module and attr in module.constants:
                return module, module.constants[attr]
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module, attr = self.imported(node.value.id)
            if module and attr is None and node.attr in module.constants:
                return module, module.constants[node.attr]
        raise Unresolved(self.where(node))

    def elements(self, node):
        """What a subscript of a literal table can stand for: every entry, or the one a literal index names."""
        if not isinstance(node, ast.Subscript):
            module, value = self.constant(node)
            return [(module, value)]
        found = []
        for module, table in self.elements(node.value):
            if isinstance(table, (ast.Name, ast.Attribute)):
                module, table = module.constant(table)
            index = node.slice.value if isinstance(node.slice, ast.Constant) else None
            if isinstance(table, ast.Dict):
                keys = [key.value if isinstance(key, ast.Constant) else object() for key in table.keys]
                found += [(module, value) for key, value in zip(keys, table.values) if index is None or key == index]
            elif isinstance(table, (ast.Tuple, ast.List)):
                found += [(module, value) for value in (table.elts if index is None else [table.elts[index]])]
            else:
                raise Unresolved(self.where(node))
        return found

    def values(self, node):
        """The (module, node) pairs a node can stand for, through module constants and literal tables."""
        if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
            return [found for module, value in self.elements(node) for found in module.values(value)]
        return [(self, node)]

    def members(self, node):
        """The members of each literal sequence a node can stand for."""
        found = []
        for module, value in self.values(node):
            if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                raise Unresolved(module.where(value))
            found += [(module, element) for element in value.elts]
        return found

    def unpack(self, node, index):
        """The member at one position of each literal tuple a node can stand for."""
        found = []
        for module, value in self.values(node):
            if (not isinstance(value, (ast.Tuple, ast.List)) or index >= len(value.elts)
                    or any(isinstance(element, ast.Starred) for element in value.elts)):
                raise Unresolved(module.where(value))
            found.append((module, value.elts[index]))
        return found

    def selected(self, node):
        """Whether a loop runs over rows a kv query selects. Their keys are the ones its own filter names."""
        while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'fetchall':
            node = node.func.value
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'execute'
                and bool(node.args) and bool(re.match(r'\s*SELECT\s+k\b.*\bFROM\s+kv\b', sql(node.args[0]), re.I | re.S)))

    def bindings(self, scope, name):
        """What a function binds a name to, as (module, node) pairs, or None when it does not bind it.

        An assignment binds the value, and a tuple target the member at the name's position. A loop
        binds the members of the literal sequence it runs over.
        """
        values = None

        def position(target):
            if isinstance(target, ast.Name):
                return None if target.id == name else False
            if isinstance(target, (ast.Tuple, ast.List)):
                names = [element.id if isinstance(element, ast.Name) else None for element in target.elts]
                if name in names:
                    if any(isinstance(element, ast.Starred) for element in target.elts):
                        raise Unresolved(self.where(target))
                    return names.index(name)
            return False
        for node in own(scope):
            if isinstance(node, ast.Assign):
                targets, value, loop = node.targets, node.value, False
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                targets, value, loop = [node.target], node.value, False
            elif isinstance(node, (ast.For, ast.comprehension)):
                targets, value, loop = [node.target], node.iter, True
            else:
                continue
            for target in targets:
                index = position(target)
                if index is False:
                    continue
                values = values or []
                if loop and self.selected(value):
                    continue
                items = self.members(value) if loop else [(self, value)]
                values += items if index is None else [found for module, item in items for found in module.unpack(item, index)]
        return values

    def declarations(self, node):
        """Whether a node is the domain declarations or a call that picks from them."""
        if isinstance(node, ast.Call):
            node = node.func
        if isinstance(node, ast.Attribute):
            node = node.value
        if not isinstance(node, ast.Name):
            return False
        module, attr = self.imported(node.id)
        if module is not None and module.name == 'pokesim.state.domains':
            return True
        scope = self.scope(node)
        values = self.bindings(scope, node.id) if scope is not None and attr is None and module is None else None
        return bool(values) and all(module.declarations(value) for module, value in values)

    def declared(self, node):
        """Whether ``name.key`` reads a declaration a loop runs over. Such a key is declared by construction."""
        if not (isinstance(node, ast.Attribute) and node.attr == 'key' and isinstance(node.value, ast.Name)):
            return False
        scope = self.scope(node)
        while scope is not None:
            for loop in own(scope):
                if (isinstance(loop, (ast.For, ast.comprehension)) and isinstance(loop.target, ast.Name)
                        and loop.target.id == node.value.id):
                    return self.declarations(loop.iter)
            scope = self.scope(scope)
        return False

    def resolve(self, node, seen=frozenset()):
        """Each kv key a node can be, as ('key', text), or ('prefix', text) for a key built on a string."""
        if self.declared(node):
            return []
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [('key', node.value)]
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
            return [('prefix', node.values[0].value)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return [('prefix', text) for _, text in self.resolve(node.left, seen)]
        if isinstance(node, ast.Subscript):
            return [found for module, value in self.elements(node) for found in module.resolve(value, seen)]
        if isinstance(node, ast.Attribute):
            module, value = self.constant(node)
            return module.resolve(value, seen)
        if not isinstance(node, ast.Name):
            raise Unresolved(self.where(node))
        scope = self.scope(node)
        while scope is not None:
            if (values := self.bindings(scope, node.id)) is not None:
                return [found for module, value in values for found in module.resolve(value, seen)]
            arguments = scope.args
            if node.id in [a.arg for a in arguments.posonlyargs + arguments.args + arguments.kwonlyargs]:
                return self.calls(scope, node.id, seen)
            scope = self.scope(scope)
        module, value = self.constant(node)
        return module.resolve(value, seen)

    def calls(self, function, name, seen):
        """Follow a key parameter to what each call in this module passes for it, or its default."""
        if isinstance(function, ast.Lambda):
            raise Unresolved(self.where(function))
        if (self.name, function.name) in GENERIC or function in seen:
            return []
        arguments = function.args
        positional = [a.arg for a in arguments.posonlyargs + arguments.args]
        defaults = dict(zip(positional[len(positional) - len(arguments.defaults):], arguments.defaults))
        defaults.update((a.arg, d) for a, d in zip(arguments.kwonlyargs, arguments.kw_defaults) if d is not None)
        method = isinstance(self.parent.get(function), ast.ClassDef)
        found, sites = [], 0
        for call in ast.walk(self.tree):
            if not isinstance(call, ast.Call):
                continue
            if method and isinstance(call.func, ast.Attribute) and call.func.attr == function.name:
                position = positional.index(name) - 1 if name in positional else None
            elif not method and isinstance(call.func, ast.Name) and call.func.id == function.name:
                position = positional.index(name) if name in positional else None
            else:
                continue
            argument = next((k.value for k in call.keywords if k.arg == name), None)
            if argument is None and position is not None and position < len(call.args):
                if any(isinstance(a, ast.Starred) for a in call.args[:position + 1]):
                    raise Unresolved(self.where(call))
                argument = call.args[position]
            argument = argument if argument is not None else defaults.get(name)
            if argument is None:
                raise Unresolved(self.where(call))
            sites += 1
            found += self.resolve(argument, seen | {function})
        if not sites:
            raise Unresolved(self.where(function))
        return found

    def scan(self):
        """Each kv key this module names, as (where, kind, text), and the uses it cannot follow."""
        found, unresolved = [], []

        def add(node, attempt):
            try:
                found.extend((self.where(node), kind, text) for kind, text in attempt())
            except Unresolved as error:
                unresolved.append(f'{self.where(node)} {ast.unparse(node)} (at {error})')
        for call in ast.walk(self.tree):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or not call.args:
                continue
            receiver = ast.unparse(call.func.value)
            if call.func.attr in ('get', 'set') and (STORE.search(receiver) or (
                    self.name == 'pokesim.store' and receiver == 'self')):
                add(call.args[0], lambda node=call.args[0]: self.resolve(node))
            elif call.func.attr in ('execute', 'executemany') and KV.search(text := sql(call.args[0])):
                found.extend((self.where(call), 'key', key) for key in QUOTED_KEY.findall(text))
                found.extend((self.where(call), *row) for row in like([('key', p) for p in QUOTED_LIKE.findall(text)]))
                rows = call.args[1] if len(call.args) > 1 else None
                if call.func.attr == 'executemany':
                    rows = rows.elts if isinstance(rows, (ast.Tuple, ast.List)) else [rows]
                else:
                    rows = [rows]
                for index, mark in enumerate(re.finditer(r'\?', text)):
                    before = text[:mark.start()]
                    if not (KEY_BEFORE.search(before) or LIKE_BEFORE.search(before)):
                        continue
                    for row in rows:
                        if not isinstance(row, (ast.Tuple, ast.List)) or index >= len(row.elts):
                            unresolved.append(f'{self.where(call)} {ast.unparse(call.args[1]) if row else "no parameters"}')
                            continue
                        value = row.elts[index]
                        if LIKE_BEFORE.search(before):
                            add(value, lambda value=value: like(self.resolve(value)))
                        else:
                            add(value, lambda value=value: self.resolve(value))
        return found, unresolved


class Package:
    def __init__(self, root):
        self.root = root
        self.modules = {}
        for path in sorted(root.rglob('*.py')):
            parts = path.relative_to(root.parent).with_suffix('').parts
            name = '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)
            self.modules[name] = Module(self, name, path, ast.parse(path.read_text(encoding='utf-8'), str(path)))

    def scan(self):
        found, unresolved = [], []
        for module in self.modules.values():
            more, missed = module.scan()
            found += more
            unresolved += missed
        return found, unresolved


@pytest.fixture(scope='module')
def scanned():
    return Package(PACKAGE).scan()


def declared(kind, text):
    if kind == 'key':
        return domains.find(text) is not None
    return any(text.startswith(prefix) for prefix in domains.PREFIXES)


def test_every_kv_key_the_package_uses_is_declared(scanned):
    found, unresolved = scanned
    assert unresolved == [], 'The scan cannot tell which kv key these name. Name it with a string or a constant.'
    missing = sorted({f'{kind} {text!r} at {where}' for where, kind, text in found if not declared(kind, text)})
    assert missing == [], 'Declare each new kv key in pokesim/state/domains.py, one line with its life.'


def test_every_declared_key_is_still_used(scanned):
    found, _ = scanned
    keys = {text for _, kind, text in found if kind == 'key'}
    prefixes = {text for _, kind, text in found if kind == 'prefix'}
    assert sorted(set(domains.KEYS) - keys) == []
    assert sorted(prefix for prefix in domains.PREFIXES
                  if not any(text.startswith(prefix) for text in prefixes | keys)) == []


def test_the_declared_tables_are_the_schema_tables():
    tables = {re.search(r'EXISTS (\w+)', statement).group(1) for statement in schema.TABLES}
    assert set(domains.TABLES) | {'kv'} == tables


def test_each_domain_is_declared_once_with_a_life():
    names = [domain.key for domain in domains.DOMAINS]
    assert len(names) == len(set(names))
    for domain in domains.DOMAINS:
        assert domain.life in domains.LIVES, domain
        assert domain.generations and set(domain.generations) <= {1, 2}, domain
        assert domain.kind in (domains.KEY, domains.PREFIX, domains.TABLE), domain
        assert not domain.cached or domain.kind == domains.KEY, domain
        assert domain.owner.startswith('pokesim.'), domain
    assert not [key for key in domains.KEYS if any(key.startswith(prefix) for prefix in domains.PREFIXES)]
    assert domains.find('trade_offer:abc') is domains.PREFIXES['trade_offer:']
    assert domains.find('never-declared') is None


def test_the_store_caches_the_same_keys_as_before():
    assert domains.CACHED == {
        'cartridge-steps-v1', 'mew-returns-v1', 'pokesim-mew-v1', 'legendary-returns-v1',
        'step-events-v1', 'pokedex-milestones-v1', 'shiny-statistics-v1'}


def test_the_lives_are_what_each_restart_does():
    def keys(life, generation):
        return {domain.key for domain in domains.DOMAINS if domain.life == life and generation in domain.generations
                and domain.kind != domains.TABLE}
    # Section 4 of docs/design/adventure-state-store.md, as ruled in section 8.
    both = {'custom-reward-pending-v1', 'league-rewards-v1', 'play_clock', 'capture-statistics-v1',
            'pokedex-milestones-v1', 'adventure-records-v1', 'trade_offer:', 'loop-guard-reloads-v1',
            'goal-time-v1'}
    assert keys(domains.RESETS_ON_RESTART, 1) == both | {
        'shiny-statistics-v1', 'league-partners-v2', 'league-partners-v1', 'mew-returns-v1', 'pokesim-mew-v1'}
    assert keys(domains.RESETS_ON_RESTART, 2) == both | {
        'gen2-shiny-statistics-v1', 'gen2-mythical-gift-v1', 'gen2-gs-ball-distribution-v1',
        'gen2-league-partners-v1', 'gen2-mew-returns-v1', 'gen2-clock-v1'}
    assert keys(domains.REWINDS, 1) == {'policy_state', 'run_memory'}
    assert keys(domains.REWINDS, 2) == {'policy_state', 'gen2-history'}
    assert domains.KEYS['league-rewards-v1'].policy_reads and 'trade_hold' in domains.POLICY_READS


def test_the_scan_follows_each_way_a_key_is_named(tmp_path):
    root = tmp_path / 'pokesim'
    (root / 'sub').mkdir(parents=True)
    (root / '__init__.py').write_text('')
    (root / 'sub' / '__init__.py').write_text('')
    (root / 'keys.py').write_text("KEY = 'imported'\nTABLE = {1: (KEY, 'x'), 2: ('second', 'y')}\n")
    (root / 'state').mkdir()
    (root / 'state' / '__init__.py').write_text('')
    (root / 'state' / 'domains.py').write_text('def restarted(generation):\n    return ()\n')
    (root / 'sub' / 'user.py').write_text('''
from .. import keys
from ..state import domains
from ..keys import KEY as renamed
LOCAL = 'module'

def uses(store, db, generation):
    store.get('literal')
    store.set(LOCAL, 1)
    self.store.get(renamed)
    store.get(keys.TABLE[generation][0])
    marker = 'assigned'
    db.execute('SELECT 1 FROM kv WHERE k=?', (marker,))
    db.execute('UPDATE kv SET v=? WHERE k=?', ('not a key', 'updated'))
    db.execute("SELECT v FROM kv WHERE k='quoted'")
    db.execute('SELECT k FROM kv WHERE k LIKE ?', ('family:' + '%',))
    db.execute("DELETE FROM kv WHERE k LIKE 'pattern:%'")
    for key in ('looped', 'twice'):
        store.set(key, None)
    store.get(f'built:{generation}')
    read(db, 'through-a-call')
    read(db)

def read(db, key='by-default'):
    db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (key, '{}'))

def pairs(store, db, generation):
    for key, value in (('pair-a', 1), ('pair-b', 2)):
        db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (key, value))
    name, table = keys.TABLE[generation]
    store.get(name)
    for row, raw in db.execute('SELECT k,v FROM kv WHERE k LIKE ?', ('rows:%',)).fetchall():
        db.execute('UPDATE kv SET v=? WHERE k=?', (raw, row))

def declared(db):
    chosen = domains.restarted(1)
    for domain in chosen:
        db.execute('DELETE FROM kv WHERE k=?', (domain.key,))

def unknown(store, value):
    store.get(value.name)
''')
    found, unresolved = Package(root).scan()
    assert sorted((kind, text) for _, kind, text in found) == sorted([
        ('key', 'literal'), ('key', 'module'), ('key', 'imported'), ('key', 'imported'), ('key', 'second'),
        ('key', 'assigned'), ('key', 'updated'), ('key', 'quoted'), ('prefix', 'family:'), ('prefix', 'pattern:'),
        ('key', 'looped'), ('key', 'twice'), ('prefix', 'built:'), ('key', 'through-a-call'), ('key', 'by-default'),
        ('key', 'pair-a'), ('key', 'pair-b'), ('key', 'imported'), ('key', 'second'), ('prefix', 'rows:')])
    assert [row.split(' ')[1] for row in unresolved] == ['value.name']
