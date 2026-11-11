"""Package only distributable skill files; never include jobs or bytecode."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
skill = root / "skills/pdf-translate"
out = root / "dist/pdf-translate.zip"
out.parent.mkdir(exist_ok=True)
with ZipFile(out, "w", ZIP_DEFLATED) as archive:
    for path in sorted(skill.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            archive.write(path, path.relative_to(skill.parent).as_posix())
print(out)
