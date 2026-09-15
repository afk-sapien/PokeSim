"""Validated immutable configuration installed before game modules are imported."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SimulationSettings:
    rom_path: str
    data_dir: str
    game_data_dir: str
    public_url: str = 'http://127.0.0.1:8000'
    starter: str = 'random'
    speed: float = 1
    policy: str = 'strategic'
    viewer_only: bool = False
    league_rewards: bool = False
    mew_event: bool = False
    seed: int | None = None
    fast_text: bool = True
    battle_animations: bool = True
    autosave_seconds: int = 60
    keep_autosaves: int = 20
    stuck_reload_seconds: int = 600
    battle_timeout_seconds: int = 900
    stream_fps: int = 15
    event_retention_days: int = 0
    feed_title: str = 'pokesim'
    ntfy_url: str = ''
    ntfy_token: str = ''
    ntfy_min_priority: int = 2
    ntfy_mute: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ('rom_path', 'data_dir', 'game_data_dir'):
            value = getattr(self, name)
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError(f'{name} must be an absolute path')
            object.__setattr__(self, name, str(Path(value).resolve()))
        if not Path(self.rom_path).is_file() or Path(self.rom_path).stat().st_size == 0:
            raise ValueError('rom_path must point to a nonempty ROM file')
        if self.policy not in {'strategic', 'smart_random', 'guided_random'}:
            raise ValueError('Unknown simulation policy')
        if self.starter not in {'random', 'bulbasaur', 'charmander', 'squirtle'}:
            raise ValueError('Unknown starter')
        for name in ('viewer_only', 'fast_text', 'battle_animations', 'league_rewards', 'mew_event'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be a boolean')
        if self.seed is not None and type(self.seed) is not int:
            raise ValueError('seed must be an integer or null')
        ranges = {
            'speed': (0, 16), 'autosave_seconds': (1, 86400),
            'keep_autosaves': (1, 10000), 'stuck_reload_seconds': (1, 604800),
            'battle_timeout_seconds': (1, 604800), 'stream_fps': (1, 60),
            'event_retention_days': (0, 36500), 'ntfy_min_priority': (1, 5),
        }
        for name, (low, high) in ranges.items():
            value = getattr(self, name)
            kinds = (float, int) if name == 'speed' else (int,)
            if type(value) not in kinds or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{name} must be between {low} and {high}')
        if 0 < self.speed < 0.1:
            raise ValueError('speed must be zero or at least 0.1')
        for name in ('public_url', 'ntfy_url'):
            value = getattr(self, name)
            if name == 'ntfy_url' and value == '':
                continue
            if not isinstance(value, str):
                raise ValueError(f'{name} must be a URL')
            parsed = urlsplit(value)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f'{name} must be an HTTP URL without credentials')
            if parsed.query or parsed.fragment:
                raise ValueError(f'{name} must not contain a query or fragment')
        if not isinstance(self.feed_title, str) or not isinstance(self.ntfy_token, str):
            raise ValueError('Notification token and feed title must be text')
        if not isinstance(self.ntfy_mute, (list, tuple)) or any(not isinstance(x, str) for x in self.ntfy_mute):
            raise ValueError('ntfy_mute must be a list of event names')
        object.__setattr__(self, 'ntfy_mute', tuple(self.ntfy_mute))

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict):
            raise ValueError('settings must be an object')
        unknown = set(values) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f'Unknown settings: {", ".join(sorted(unknown))}')
        try:
            return cls(**values)
        except TypeError as error:
            raise ValueError('Missing required simulation settings') from error

    @classmethod
    def from_environment(cls):
        from .. import config
        values = {field.name: getattr(config, field.name.upper()) for field in fields(cls)
                  if hasattr(config, field.name.upper())}
        for name in ('rom_path', 'data_dir'):
            values[name] = str(Path(values[name]).expanduser().resolve())
        values['game_data_dir'] = str(Path(os.environ.get('GAME_DATA_DIR',
            str(Path(values['data_dir']) / 'game-data'))).expanduser().resolve())
        values['ntfy_mute'] = tuple(sorted(values['ntfy_mute']))
        return cls(**values)

    def to_dict(self):
        return asdict(self)

    def install(self, *, managed=True):
        """Bridge legacy module constants once inside the owning process."""
        os.environ['DATA_DIR'] = self.data_dir
        os.environ['GAME_DATA_DIR'] = self.game_data_dir
        for name, value in self.to_dict().items():
            if isinstance(value, bool):
                encoded = '1' if value else '0'
            elif name == 'ntfy_mute':
                encoded = ','.join(value)
            else:
                encoded = str(value if value is not None else 0)
            os.environ[name.upper()] = encoded
        if managed:
            os.environ.update(HOST='127.0.0.1', PORT='8000', TRADING_URL='', TRADING_INSTANCE='', TRADE_TOKEN='')
        from .. import config
        for name, value in self.to_dict().items():
            if name == 'game_data_dir':
                continue
            if name in {'rom_path', 'data_dir'}:
                value = Path(value)
            if name == 'ntfy_mute':
                value = set(value)
            setattr(config, name.upper(), value)
        if managed:
            config.TRADING_URL = ''
            config.TRADING_INSTANCE = ''
            config.TRADE_TOKEN = ''
