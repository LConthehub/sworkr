"""Make site/downloads/sworkr-start.zip: the setup file plus double-click start, update and stop files.

Run from the repository: python site/build_downloads.py
"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "downloads")
FILES = [("docker-compose.yml", os.path.join(ROOT, "docker-compose.yml"))] + [
    (name, os.path.join(ROOT, "installer", name)) for name in sorted(os.listdir(os.path.join(ROOT, "installer")))]

os.makedirs(OUT, exist_ok=True)
target = os.path.join(OUT, "sworkr-start.zip")
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
    for name, path in FILES:
        with open(path, "rb") as f:
            data = f.read()
        if name.endswith(".bat"):
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")      # Windows wants CRLF
        else:
            data = data.replace(b"\r\n", b"\n")
        info = zipfile.ZipInfo(f"sworkr/{name}", date_time=(2026, 1, 1, 0, 0, 0))
        executable = name.endswith((".command", ".sh"))
        info.external_attr = (0o100755 if executable else 0o100644) << 16    # double-clickable on a Mac
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, data)
    with open(os.path.join(OUT, "docker-compose.yml"), "wb") as f:
        f.write(open(os.path.join(ROOT, "docker-compose.yml"), "rb").read())
print("Wrote", target, len(FILES), "files")
