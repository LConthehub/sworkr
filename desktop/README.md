# Sworkr desktop app

Sworkr as an ordinary program: download, unzip, double-click. No Docker. It runs only on this computer
(127.0.0.1:8765), puts an icon in the system tray (menu bar on a Mac) with *Open*, *Open the backups folder*
and *Quit*, and opens sworkr in the browser.

- **Data:** Windows `%LOCALAPPDATA%\Sworkr`, Mac `~/Library/Application Support/Sworkr`, Linux `~/.local/share/sworkr`.
- **Backups:** `Documents/Sworkr backups`.
- **Keys:** the database key and the key that seals saved passwords live in the computer's own keychain
  (Windows Credential Manager, the macOS Keychain, the Linux Secret Service) under "sworkr". They open only for
  the person signed in to the computer. Encrypted backups open with the backup passphrase alone, on any computer.

## Building

The app is built on the system it's for: build the Windows app on Windows and the Mac app on a Mac.

```
python -m venv .venv
.venv/Scripts/pip install -r desktop/requirements.txt      # Mac: .venv/bin/pip
cd frontend && npm ci && npm run build && cd ..
.venv/Scripts/python desktop/build.py                       # makes dist/Sworkr and dist/Sworkr-<system>.zip
```

## Before handing it out

- **Windows** shows "Windows protected your PC" for programs that aren't code-signed (*More info → Run anyway*).
  A code-signing certificate removes that.
- **Mac** won't open an app that isn't signed and notarized by Apple without extra steps (right-click → *Open*).
  That needs an Apple Developer account.
