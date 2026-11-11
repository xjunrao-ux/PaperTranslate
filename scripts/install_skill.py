"""Copy the reviewed, self-contained skill to the personal skills directory.

Different files require --update and verified backups. No recursive deletes or moves.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
from datetime import datetime,timezone


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path,
                        default=Path.home() / ".codex/skills/pdf-translate")
    parser.add_argument('--update',action='store_true',help='更新已安装文件，并在 skills 目录之外逐文件备份')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "skills/pdf-translate"
    target = args.destination.expanduser().resolve()
    files = [p for p in source.rglob("*") if p.is_file() and
             "__pycache__" not in p.parts and p.suffix != ".pyc"]
    if not files or not (source / "SKILL.md").is_file():
        raise SystemExit("Skill source is missing")
    changed=[]
    for path in files:
        dest = target / path.relative_to(source)
        if not dest.resolve().is_relative_to(target):
            raise SystemExit('Destination escapes skill directory: '+str(dest))
        if dest.exists() and (not dest.is_file() or sha(dest) != sha(path)):
            if not args.update or not dest.is_file():
                raise SystemExit("Existing different file; installation stopped without overwriting: " + str(dest))
            changed.append(dest)
    if changed:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=target.parent.parent/'skill-backups'/target.name/stamp
        for dest in changed:
            copied=backup/dest.relative_to(target)
            copied.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,copied)
            if sha(dest)!=sha(copied):raise SystemExit('Backup verification failed')
        print('Previous files backed up: '+str(backup))
    for path in files:
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest in changed:
            shutil.copy2(path, dest)
        if sha(path) != sha(dest):
            raise SystemExit("Copy verification failed: " + str(dest))
    print(f"Installed {len(files)} verified files: {target}")


if __name__ == "__main__":
    main()
