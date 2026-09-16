"""File durability and process locks on desktop and server platforms."""
import errno
import os


def sync_directory(path):
    # Windows does not expose directory fsync through Python. File contents are
    # still flushed before replacement, but directory crash durability differs.
    if os.name == 'nt':
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def lock_file(stream):
    """Take a nonblocking exclusive lock, held until the stream is closed."""
    if os.name == 'nt':
        import msvcrt
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError('This adventure is already open') from error
            raise
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
