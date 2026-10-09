"""Linux openat/O_NOFOLLOW traversal under administrator-selected roots."""
import os
import stat
from pathlib import PurePosixPath
if __package__:
    from .bridge_core import Failure, MAX_CONTENT, require
else:
    from bridge_core import Failure, MAX_CONTENT, require

EXTENSIONS = {".txt", ".md", ".py", ".java", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".sql", ".csv", ".log"}
SECRET_PARTS = {".git", ".ssh", ".aws", ".gemini", ".codex", "node_modules", ".venv", "credentials", "secrets", "auth.json", "config.json"}


def read_sources(roots, names):
    require(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "LINUX_REQUIRED")
    require(isinstance(names, list) and 1 <= len(names) <= 12, "BAD_FILES")
    output, total = [], 0
    for name in names:
        require(isinstance(name, str), "BAD_NAME")
        parts = name.split("/")
        require(len(parts) >= 2 and all(x not in ("", ".", "..") for x in parts), "PATH_DENIED")
        require(parts[0] in roots and "\\" not in name, "PATH_DENIED")
        require(not any(p.lower() in SECRET_PARTS or p.lower().startswith('.env') or
                        p.lower().endswith(('.pem', '.key', '.p12', '.pfx')) for p in parts[1:]), "SECRET_PATH")
        require(PurePosixPath(name).suffix.lower() in EXTENSIONS, "EXTENSION_DENIED")
        root = roots[parts[0]]
        require(isinstance(root, str) and root.startswith('/') and root != '/', "BAD_ROOT")
        # Open every root component without following symlinks, including configured roots.
        chain = root.strip('/').split('/') + parts[1:]
        require(all(p not in ('', '.', '..') for p in chain), "BAD_ROOT")
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in chain[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            file_fd = os.open(chain[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                before = os.fstat(file_fd)
                require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "NOT_PRIVATE_REGULAR_FILE")
                require(before.st_size <= MAX_CONTENT - total, "INPUT_LIMIT")
                with os.fdopen(file_fd, 'rb', closefd=False) as f:
                    raw = f.read(MAX_CONTENT - total + 1)
                after = os.fstat(file_fd)
                require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                        (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "FILE_CHANGED")
                total += len(raw)
                require(total <= MAX_CONTENT, "INPUT_LIMIT")
                require(b'\x00' not in raw, "BINARY_FILE")
                try:
                    content = raw.decode('utf-8')
                except UnicodeError:
                    raise Failure('UTF8_REQUIRED') from None
                output.append({'name': name, 'content': content})
            finally:
                os.close(file_fd)
        except OSError:
            raise Failure('PATH_UNREADABLE_OR_UNSAFE') from None
        finally:
            os.close(fd)
    return output
