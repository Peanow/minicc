from pathlib import Path
from tempfile import TemporaryDirectory

from archive import resolve_member


with TemporaryDirectory() as tmp:
    root = Path(tmp) / "extract"
    assert resolve_member(root, "pkg/data.txt") == (root / "pkg/data.txt").resolve()
    for unsafe in ("../escape.txt", "pkg/../../escape.txt", "/tmp/escape.txt"):
        try:
            resolve_member(root, unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe member accepted: {unsafe}")

    sibling = root.parent / f"{root.name}-other" / "file.txt"
    relative_escape = str(Path("..") / sibling.parent.name / sibling.name)
    try:
        resolve_member(root, relative_escape)
    except ValueError:
        pass
    else:
        raise AssertionError("prefix-confusion escape was accepted")
