"""Copy the reviewed, self-contained skill to the personal skills directory.

Existing different files are never overwritten. No recursive deletes or moves.
"""
import argparse
import hashlib
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path,
                        default=Path.home() / ".codex/skills/pdf-translate")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "skills/pdf-translate"
    target = args.destination.expanduser().resolve()
    files = [p for p in source.rglob("*") if p.is_file() and
             "__pycache__" not in p.parts and p.suffix != ".pyc"]
    if not files or not (source / "SKILL.md").is_file():
        raise SystemExit("Skill source is missing")
    for path in files:
        dest = target / path.relative_to(source)
        if dest.exists() and (not dest.is_file() or sha(dest) != sha(path)):
            raise SystemExit("Existing different file; installation stopped without overwriting: " + str(dest))
    for path in files:
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(path, dest)
        if sha(path) != sha(dest):
            raise SystemExit("Copy verification failed: " + str(dest))
    print(f"Installed {len(files)} verified files: {target}")


if __name__ == "__main__":
    main()
