<div align="center">

# Username Checker Collection

### fast • clean • actually working

A collection of username availability checkers for multiple platforms.

Most public checkers are outdated, rate-limited to death, or straight up broken.  
This repo keeps working scripts in one place with simple usage and minimal setup.

Some scripts are basic availability checkers, others include generation, automation, or claiming logic depending on the platform.

<br>

<img src="https://img.shields.io/badge/python-3.10+-blue?style=for-the-badge&logo=python" />
<img src="https://img.shields.io/badge/status-active-success?style=for-the-badge" />
<img src="https://img.shields.io/badge/platforms-multi--platform-black?style=for-the-badge" />
<img src="https://img.shields.io/badge/vibe-working_endpoints-important?style=for-the-badge" />

</div>

---

# Supported Checkers

```txt
Roblox
Reddit
Steam
Minecraft
Geometry Dash
Chess / Lichess
```

> Some scripts are CLI-based, others GUI-based depending on what works best for the platform.

---

# Features

- Fast username availability checking
- Random username generation
- Multi-platform support
- Some auto-claim / automation support
- GUI for selected platforms
- Rate-limit handling where possible
- Auto-save hits
- Simple Python setup

---

# Requirements

## Python

### Recommended

**Python 3.10+**

### Minimum

**Python 3.9+**

Download here:  
https://www.python.org/downloads/

---

# Dependencies

Install everything with:

```bash
pip install -r requirements.txt
```

### Common modules used

- `requests`
- `aiohttp`
- `asyncio`
- `threading`
- `tkinter`
- `colorama`
- `selenium`
- `beautifulsoup4`
- `httpx`

> Some scripts may require platform-specific cookies, tokens, or active sessions.

---

# Platform Notes

## Minecraft

- Uses Mojang API
- Best for short usernames (mainly 3–4 chars)
- Fast checks with clean responses

## Roblox

- Username checking support
- Optional account creation logic depending on script

---

# Usage

Run whichever script you want:

```bash
python minecraft.py
```

### Examples

```bash
python reddit.py
python roblox.py
python steam.py
```
---

# Why This Repo Exists

Most username checkers on GitHub:

- use dead endpoints
- are patched
- get rate-limited instantly
- fake results
- were abandoned years ago

This repo focuses on scripts that still actually function.

No fake “100% working” garbage.

---

# Disclaimer

```txt
This project is for educational and research purposes only.
```

You are responsible for how you use these scripts.

Do not abuse APIs, violate platform Terms of Service,  
or automate actions on accounts you do not own.

---

# Contributing

If an endpoint gets patched or a checker breaks:

### fix it :)

Pull requests are welcome.

---

<div align="center">

# Author

## made by **rs4t**

mostly vibe coding,  
fixing broken APIs,  
and checking if usernames still hit.

</div>
