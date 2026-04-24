# Username Checker Collection

A collection of username availability checkers for different platforms.

Most public checkers are outdated, rate-limited to death, or straight up broken.  
This repo is meant to keep working scripts in one place with simple usage and minimal setup.

Some scripts are basic availability checkers, others include generation, automation, or claiming logic depending on the platform.

---

## Supported Checkers
- Roblox
- Reddit
- Steam
- Minecraft
- Geometry Dash
- Chess / Lichess
(Some scripts may be CLI-based, others GUI-based depending on what works best for the platform.)

---

## Features
- Fast username availability checking
- Random username generation
- Multi-platform support
- Some auto-claim / automation support
- GUI for selected platforms
- Rate-limit handling where possible
- Save hits automatically
- Simple Python setup

---

## Requirements

### Python
Recommended:
- **Python 3.10+**
Minimum for some scripts:
- Python 3.9+
Download here: https://www.python.org/downloads/

---

## Dependencies
Install everything with:
```bash
pip install -r requirements.txt
```

Common modules used across scripts include:
- `requests`
- `aiohttp`
- `asyncio`
- `threading`
- `tkinter` (usually included with Python)
- `colorama`
- `selenium` (for browser/session-based claimers)
- `beautifulsoup4`
- `httpx`
(Some scripts may require platform-specific cookies, tokens, or active sessions.)

---

## Platform Notes

### Minecraft
- Uses Mojang API
- Good for short username checking (3–4 chars mainly)

### Roblox
- Supports checking + optional account creation logic

---

## Usage
Run whichever script you want:
```bash
python tiktok_checker.py
```

Examples:
```bash
python github_checker.py
python reddit_checker.py
python roblox_checker_gui.py
```

For GUI scripts:
```bash
python roblox_checker_gui.py
```

---

## Why This Repo Exists
Most username checkers on GitHub:

- are patched
- use dead endpoints
- get rate-limited instantly
- fake results
- were abandoned years ago

This repo focuses on scripts that actually still function.

---

## Disclaimer
This project is for educational and research purposes only.
You are responsible for how you use these scripts.  
Do not abuse APIs, violate platform Terms of Service, or automate actions on accounts you do not own.

---

## Contributing
If an endpoint gets patched or a checker breaks, feel free to update it.
Pull requests are welcome.

---

## Author
Made by **rs4t**
