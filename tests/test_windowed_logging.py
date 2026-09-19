import logging
import sys

from fastapi import FastAPI
import uvicorn

from pokesim.app.manager import configure_logging


def test_windowed_launch_restores_streams_before_uvicorn_formatters(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    saved_loggers = {name: (logging.getLogger(name).handlers[:], logging.getLogger(name).level,
                            logging.getLogger(name).propagate)
                     for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access')}
    handler = configure_logging(tmp_path)
    output, errors = sys.stdout, sys.stderr
    try:
        assert not output.isatty()
        assert not errors.isatty()
        config = uvicorn.Config(FastAPI(), log_level='warning')
        assert config is not None
        logging.getLogger('pokesim.windowed-test').warning('Windowed diagnostic')
        handler.flush()
        assert 'Windowed diagnostic' in (tmp_path / 'manager.log').read_text()
    finally:
        for name, (handlers, level, propagate) in saved_loggers.items():
            logger = logging.getLogger(name)
            logger.handlers, logger.level, logger.propagate = handlers, level, propagate
        logging.getLogger().removeHandler(handler)
        handler.close()
        output.close()
        errors.close()
