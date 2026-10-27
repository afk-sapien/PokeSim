"""Keep an adventure running through an error in one pass of its emulator loop, for every generation."""
import time

MAX_CONSECUTIVE_ERRORS = 10


def loop_failed(emulator, log):
    """Log the current exception and return whether the run must stop instead of trying the next pass.

    A committed reward or purchase that cannot be recovered sets fatal_error before it raises, and only a
    restart is safe then. Otherwise the run continues until the same pass has failed ten times in a row.
    """
    log.exception('emulator loop error')
    if getattr(emulator, 'fatal_error', None):
        return True
    emulator.consecutive_errors += 1
    if emulator.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
        emulator.fatal_error = f'Emulator stopped after {MAX_CONSECUTIVE_ERRORS} consecutive errors. See server logs.'
        return True
    time.sleep(1)
    return False
