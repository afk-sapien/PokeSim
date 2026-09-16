"""Avoid a duplicate top-level SDL2 link when ctypes already collects the library."""
from PyInstaller.compat import is_darwin

if is_darwin:
    bindepend_symlink_suppression = ['**/sdl2dll/dll/SDL2.framework/**']
