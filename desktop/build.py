"""
Build the desktop app for the computer this runs on (Windows here makes the Windows app; a Mac makes the Mac app).

    python desktop/build.py --pages path/to/frontend/dist

Needs: Python 3.11+, the packages in desktop/requirements.txt, and the frontend already built (npm run build).
Makes dist/Sworkr (a folder with Sworkr.exe / Sworkr.app) and a zip of it in dist/.
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", default=os.path.join(ROOT, "frontend", "dist"), help="the built frontend folder")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = parser.parse_args()
    if not os.path.isfile(os.path.join(args.pages, "index.html")):
        sys.exit(f"No built pages in {args.pages}. Build the frontend first (npm run build).")

    work = os.path.join(args.out, "build")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    # The backend without its tests, caches and any local data.
    backend = os.path.join(work, "backend")
    shutil.copytree(os.path.join(ROOT, "backend"), backend,
                    ignore=shutil.ignore_patterns("tests", "__pycache__", "data", "*.db", "Dockerfile", "requirements-dev.txt"))
    shutil.copytree(args.pages, os.path.join(work, "web"))

    sep = ";" if sys.platform == "win32" else ":"
    icon = os.path.join(args.pages, "icon-512.png")
    command = [
        sys.executable, "-m", "PyInstaller", os.path.join(HERE, "sworkr_desktop.py"),
        "--name", "Sworkr", "--noconfirm", "--clean", "--windowed",
        "--distpath", args.out, "--workpath", os.path.join(work, "pyinstaller"), "--specpath", work,
        "--add-data", f"{backend}{sep}backend", "--add-data", f"{os.path.join(work, 'web')}{sep}web",
        "--paths", backend,
        # sworkr's modules are loaded from the backend folder at run time; these are what they need.
        "--collect-all", "sqlcipher3", "--collect-submodules", "keyring", "--collect-submodules", "uvicorn",
        "--collect-submodules", "webauthn", "--collect-all", "segno", "--collect-data", "tzdata",
        "--hidden-import", "pystray", "--hidden-import", "multipart",
    ]
    for module in sorted(f[:-3] for f in os.listdir(backend) if f.endswith(".py")):
        command += ["--hidden-import", module]
    if sys.platform == "win32" and os.path.exists(icon):
        try:
            from PIL import Image
            ico = os.path.join(work, "sworkr.ico")
            Image.open(icon).save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
            command += ["--icon", ico]
        except Exception as e:
            print(f"(no icon: {e})")
    elif sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "com.sworkr.app"]
    subprocess.run(command, check=True)

    target = os.path.join(args.out, "Sworkr.app" if sys.platform == "darwin" else "Sworkr")
    platform = {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux")
    archive = shutil.make_archive(os.path.join(args.out, f"Sworkr-{platform}"), "zip", os.path.dirname(target), os.path.basename(target))
    print(f"\nBuilt {target}\nZip:  {archive}")


if __name__ == "__main__":
    main()
