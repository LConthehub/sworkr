"""
Sworkr as an ordinary desktop app: no Docker, nothing to set up.

Double-clicking it starts sworkr on this computer only (127.0.0.1), puts an icon in the system tray (the menu
bar on a Mac) and opens sworkr in the browser. Opening it again while it runs just opens the browser.

Where things are kept:
- the database:        Windows %LOCALAPPDATA%\\Sworkr   Mac ~/Library/Application Support/Sworkr   Linux ~/.local/share/sworkr
- backups:             Documents/Sworkr backups (easy to find, and to copy elsewhere)
- the keys:            the computer's own keychain (Windows Credential Manager, the macOS Keychain, the Linux
                       Secret Service), not files. They open only for the person signed in to this computer.
"""

import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

APP = "Sworkr"
PORT = int(os.environ.get("SWORKR_PORT", "8765"))        # not 8080, so it can run beside the Docker copy
ADDRESS = f"http://localhost:{PORT}"


def bundle_dir() -> str:
    """Where the app's own files are: next to this script, or inside the packaged app."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local"), APP)
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP}")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), APP.lower())


def backups_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents", f"{APP} backups")


def log_file() -> str:
    return os.path.join(os.environ.get("DATA_DIR") or data_dir(), "sworkr.log")


def already_running() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def port_taken() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def configure():
    """Tell sworkr where to keep things, before it's imported. Each can be changed with the same setting the
    Docker copy uses (DATA_DIR, BACKUP_DIR…)."""
    data = os.environ.setdefault("DATA_DIR", data_dir())
    os.makedirs(data, exist_ok=True)
    os.makedirs(os.environ.setdefault("BACKUP_DIR", backups_dir()), exist_ok=True)
    os.environ.setdefault("KEY_DIR", os.path.join(data, "keys"))      # only used if the keychain is turned off
    os.environ.setdefault("SWORKR_KEY_STORE", "keychain")
    os.environ.setdefault("STATIC_DIR", os.path.join(bundle_dir(), "web"))
    sys.path.insert(0, os.path.join(bundle_dir(), "backend"))
    logging.basicConfig(filename=log_file(), level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")


def serve():
    import uvicorn
    import main   # noqa: F401  (sworkr itself; upgrades and encrypts the database on start)
    config = uvicorn.Config(main.app, host="127.0.0.1", port=PORT, log_config=None, proxy_headers=True,
                            forwarded_allow_ips="127.0.0.1")
    server = uvicorn.Server(config)
    return server, threading.Thread(target=server.run, name="sworkr", daemon=True)


def wait_until_up(seconds: float = 60) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if already_running():
            return True
        time.sleep(0.3)
    return False


def tray(server):
    """The icon with Open and Quit. Without a tray (some Linux desktops), sworkr just keeps running."""
    try:
        import pystray
        from PIL import Image
    except Exception:
        while not server.should_exit:
            time.sleep(1)
        return
    icon_path = os.path.join(bundle_dir(), "web", "icon-192.png")
    image = Image.open(icon_path) if os.path.exists(icon_path) else Image.new("RGB", (64, 64), (167, 49, 120))

    def quit_app(icon, _item):
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Sworkr", lambda icon, item: webbrowser.open(ADDRESS), default=True),
        pystray.MenuItem("Open the backups folder", lambda icon, item: open_folder(os.environ["BACKUP_DIR"])),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Sworkr", quit_app),
    )
    pystray.Icon(APP, image, f"{APP} is running", menu).run()


def open_folder(path: str):
    if sys.platform == "win32":
        os.startfile(path)   # noqa: S606
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')


def show_error(message: str):
    """A plain message box, so someone who double-clicked isn't left wondering."""
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(APP, message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def run():
    if already_running():
        webbrowser.open(ADDRESS)
        return
    if port_taken():
        show_error(f"Something else on this computer is using port {PORT}, so Sworkr can't start.\n\n"
                   f"Close it and try again, or start Sworkr with the SWORKR_PORT setting set to another number.")
        return
    configure()
    try:
        server, thread = serve()
    except Exception as e:   # the database can't be opened, the key is missing…
        logging.exception("Sworkr couldn't start")
        show_error(f"Sworkr couldn't start: {e}\n\nDetails are in {log_file()}")
        return
    thread.start()
    if not wait_until_up():
        show_error(f"Sworkr didn't start. Details are in {log_file()}")
        return
    webbrowser.open(ADDRESS)
    tray(server)
    server.should_exit = True
    thread.join(timeout=10)


if __name__ == "__main__":
    run()
