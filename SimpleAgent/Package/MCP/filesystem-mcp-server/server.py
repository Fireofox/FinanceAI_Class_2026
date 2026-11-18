"""A stdio MCP server for UTF-8 files under a configured directory.

FILE_MCP_ROOT defaults to the server's current working directory.
FILE_MCP_MAX_BYTES defaults to 1048576 bytes per read or write.
"""

import contextlib
import errno
import os
from pathlib import Path, PureWindowsPath
import secrets
import stat

from mcp.server.fastmcp import FastMCP

server = FastMCP("filesystem-example")
DEFAULT_MAX_BYTES = 1024 * 1024


class FileToolError(ValueError):
    """A safe, user-facing file operation error."""


def _settings():
    root = Path(os.path.abspath(os.environ.get("FILE_MCP_ROOT") or os.getcwd()))
    try:
        limit = int(os.environ.get("FILE_MCP_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
        if limit <= 0:
            raise ValueError
    except ValueError:
        raise FileToolError("FILE_MCP_MAX_BYTES must be a positive integer") from None
    return root, limit


def _parts(path: str) -> tuple[str, ...]:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise FileToolError("Path must be a non-empty relative file path")
    windows = PureWindowsPath(path)
    candidate = Path(path)
    if candidate.is_absolute() or windows.is_absolute() or windows.drive:
        raise FileToolError("Path must be relative to the configured root")
    # Reject both native and Windows traversal syntax, even on POSIX.
    if ".." in candidate.parts or ".." in windows.parts or not candidate.parts:
        raise FileToolError("Path must stay within the configured root")
    if os.name != "nt" and "\\" in path:
        raise FileToolError("Path must use the platform's directory separators")
    if os.name == "nt":
        for part in candidate.parts:
            # is_reserved covers device names even when an extension is added.
            reserved = os.path.isreserved(part) if hasattr(os.path, "isreserved") else PureWindowsPath(part).is_reserved()
            if ":" in part or part.endswith((".", " ")) or reserved:
                raise FileToolError("Invalid Windows file path")
    return candidate.parts


if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

    def _win_handle(path: Path, read: bool, directory: bool):
        # OPEN_REPARSE_POINT examines the entry itself; excluding SHARE_DELETE
        # pins it against rename/replacement until its handle is closed.
        handle = _kernel32.CreateFileW(str(path), 0x80000000 if read else 0, 0x1 | 0x2, None, 3,
                                       0x00200000 | (0x02000000 if directory else 0), None)
        if handle == _INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = _FileAttributeTagInfo()
            if not _kernel32.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x400:
                raise FileToolError("Symbolic links and reparse points are not allowed")
            if bool(info.attributes & 0x10) != directory:
                raise FileToolError("Expected a directory" if directory else "Expected a regular file")
            return handle
        except BaseException:
            _kernel32.CloseHandle(handle)
            raise


@contextlib.contextmanager
def _parent(root: Path, parts: tuple[str, ...]):
    """Pin the complete directory chain while accessing the target file."""
    with contextlib.ExitStack() as stack:
        if os.name == "nt":
            current = Path(root.anchor)
            for part in (None, *root.parts[1:], *parts[:-1]):
                if part is not None:
                    current /= part
                handle = _win_handle(current, read=False, directory=True)
                stack.callback(_kernel32.CloseHandle, handle)
            yield current, None
        else:
            if not hasattr(os, "O_NOFOLLOW"):
                raise FileToolError("This platform cannot safely reject symbolic links")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            fd = os.open(root.anchor, flags)
            stack.callback(os.close, fd)
            for part in (*root.parts[1:], *parts[:-1]):
                fd = os.open(part, flags, dir_fd=fd)
                stack.callback(os.close, fd)
            yield None, fd


def _check_target(parent: Path | None, directory_fd: int | None, name: str) -> bool:
    try:
        entry = os.lstat(parent / name if parent is not None else name, dir_fd=directory_fd)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(entry.st_mode) or getattr(entry, "st_file_attributes", 0) & 0x400:
        raise FileToolError("Symbolic links and reparse points are not allowed")
    if not stat.S_ISREG(entry.st_mode):
        raise FileToolError("Expected a regular file")
    return True


def _read(parent: Path | None, directory_fd: int | None, name: str, limit: int) -> bytes:
    if os.name == "nt":
        handle = _win_handle(parent / name, read=True, directory=False)
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            _kernel32.CloseHandle(handle)
            raise
    else:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise FileToolError("Expected a regular file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise FileToolError("File exceeds the configured byte limit")
    return data


def _write(parent: Path | None, directory_fd: int | None, name: str, data: bytes, overwrite: bool) -> str:
    exists = _check_target(parent, directory_fd, name)
    if exists and not overwrite:
        raise FileToolError("File already exists; set overwrite=true to replace it")
    temp_name = ".mcp-" + secrets.token_hex(16) + ".tmp"
    temp_path = parent / temp_name if parent is not None else temp_name
    target_path = parent / name if parent is not None else name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp_path, flags, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        # Re-check before replacing and never follow an existing link.
        exists = _check_target(parent, directory_fd, name)
        if not overwrite:
            if os.name == "nt":
                os.rename(temp_path, target_path)  # Windows rename refuses existing targets.
            else:
                os.link(temp_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        else:
            os.replace(temp_path, target_path, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        return "overwritten" if exists else "created"
    finally:
        try:
            os.unlink(temp_path, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _error(exc: Exception) -> dict:
    if isinstance(exc, FileToolError):
        message = str(exc)
    elif isinstance(exc, UnicodeError):
        message = "File content must be valid UTF-8"
    elif isinstance(exc, FileNotFoundError):
        message = "File or parent directory does not exist"
    elif isinstance(exc, FileExistsError):
        message = "File already exists; set overwrite=true to replace it"
    elif isinstance(exc, OSError) and exc.errno in (errno.ELOOP,):
        message = "Symbolic links and reparse points are not allowed"
    elif isinstance(exc, OSError):
        message = f"File operation failed: {exc.strerror or type(exc).__name__}"
    else:
        message = "File operation failed"
    return {"status": "error", "error": message}


@server.tool()
def read_file(path: str) -> dict:
    """Read a UTF-8 text file using a path relative to the configured root."""
    try:
        root, limit = _settings()
        parts = _parts(path)
        with _parent(root, parts) as (parent, directory_fd):
            data = _read(parent, directory_fd, parts[-1], limit)
        return {"status": "ok", "path": path, "content": data.decode("utf-8"), "bytes": len(data)}
    except (OSError, UnicodeError, FileToolError) as exc:
        return _error(exc)


@server.tool()
def write_file(path: str, content: str, overwrite: bool = False) -> dict:
    """Write UTF-8 text below the configured root; explicitly opt in to replacement."""
    try:
        root, limit = _settings()
        parts = _parts(path)
        data = content.encode("utf-8")
        if len(data) > limit:
            raise FileToolError("Content exceeds the configured byte limit")
        with _parent(root, parts) as (parent, directory_fd):
            action = _write(parent, directory_fd, parts[-1], data, overwrite)
        return {"status": "ok", "path": path, "bytes": len(data), "action": action}
    except (OSError, UnicodeError, FileToolError) as exc:
        return _error(exc)


if __name__ == "__main__":
    server.run(transport="stdio")
