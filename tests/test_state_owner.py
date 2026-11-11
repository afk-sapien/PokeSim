"""Section 3.1 of docs/design/adventure-state-store.md: pokesim/state and store.py own pokesim.sqlite.

Every other module in the package, and every script in tools/, reaches an adventure's database through
a store's methods, or opens it with ``state.connect``, which checks the schema version first. A module
fails this test when it uses a store's ``db`` or ``lock``, or opens a database with sqlite3 itself. The
app's own databases are the one exception: the modules that own app.sqlite and auth.sqlite, and the
tools that read a copy of app.sqlite, may open those, and nothing else.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'pokesim'
# Each module that opens one of the app's own databases, and the file it opens. A tool is named by its
# path from the repository root, and a package module by its path inside pokesim/.
APP_DATABASES = {'app/registry.py': 'app.sqlite', 'app/backup.py': 'app.sqlite', 'app/auth.py': 'auth.sqlite',
                 'tools/live_soak.py': 'app.sqlite', 'tools/replay_progress.py': 'app.sqlite'}
RAW = {'db', 'lock'}


def path_of(name):
    return ROOT / name if name.startswith('tools/') else PACKAGE / name


def modules():
    """Every module of the package outside its owners, pokesim/state and store.py, then every tool."""
    for path in sorted(PACKAGE.rglob('*.py')):
        name = path.relative_to(PACKAGE).as_posix()
        if not name.startswith('state/') and name != 'store.py':
            yield name, path.read_text(encoding='utf-8')
    for path in sorted((ROOT / 'tools').glob('*.py')):
        yield f'tools/{path.name}', path.read_text(encoding='utf-8')


def a_store(owner):
    """Whether an expression names a store, such as ``store``, ``self.store`` or ``self._store``."""
    name = owner.id if isinstance(owner, ast.Name) else owner.attr if isinstance(owner, ast.Attribute) else ''
    return name == 'store' or name.endswith('_store')


def sqlite_connects(tree):
    """Each call that opens a database with sqlite3, under any name the module imports it as."""
    names, functions = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name for alias in node.names if alias.name == 'sqlite3')
        elif isinstance(node, ast.ImportFrom) and node.module == 'sqlite3':
            functions.update(alias.asname or alias.name for alias in node.names if alias.name == 'connect')
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call = node.func
        if isinstance(call, ast.Name) and call.id in functions:
            yield node
        elif (isinstance(call, ast.Attribute) and call.attr == 'connect' and isinstance(call.value, ast.Name)
              and call.value.id in names):
            yield node


def breaches(name, source):
    """Where a module reaches past the owners: a store's handle, or a database it opens itself."""
    tree = ast.parse(source)
    found = [f"{name}:{node.lineno} a store's .{node.attr}" for node in ast.walk(tree)
             if isinstance(node, ast.Attribute) and node.attr in RAW and a_store(node.value)]
    for node in sqlite_connects(tree):
        if name not in APP_DATABASES or 'pokesim.sqlite' in ast.get_source_segment(source, node):
            found.append(f'{name}:{node.lineno} sqlite3.connect')
    return found


def test_only_pokesim_state_and_the_store_reach_an_adventure_database():
    found = [breach for name, source in modules() for breach in breaches(name, source)]
    assert found == [], 'Add a store method in pokesim/state, or open the adventure with state.connect.'


@pytest.mark.parametrize('source', [
    'store.db.execute("SELECT 1")',
    'with self.store.lock:\n    pass',
    'with emu._store.db:\n    pass',
    'import sqlite3 as lite\nlite.connect(path)',
    'from sqlite3 import connect\nconnect(path)',
])
def test_the_scan_finds_each_way_past_the_owners(source):
    assert breaches('gen2/example.py', source)


def test_the_scan_lets_the_app_databases_and_state_connect_pass():
    assert breaches('gen2/example.py', 'manager.registry.db.execute("SELECT 1")\nwith self.restore.lock:\n    pass\n'
                                       'from pokesim.state import schema\nschema.connect(path, read_only=True)') == []
    assert breaches('app/registry.py', "import sqlite3\nsqlite3.connect(root / 'app.sqlite')") == []
    # An app database owner may not open an adventure's file either.
    assert breaches('app/registry.py', "import sqlite3\nsqlite3.connect(root / 'adventures' / aid / 'pokesim.sqlite')")
    assert breaches('tools/live_soak.py', "import sqlite3\nsqlite3.connect(folder / 'pokesim.sqlite')")


def test_the_scan_reads_every_tool():
    assert 'tools/live_soak.py' in dict(modules())


@pytest.mark.parametrize('name, database', APP_DATABASES.items())
def test_each_app_database_owner_still_opens_its_own_file(name, database):
    """An owner that stops opening its database leaves the exception list, so the list never grows stale."""
    source = path_of(name).read_text(encoding='utf-8')
    assert list(sqlite_connects(ast.parse(source))) and database in source
