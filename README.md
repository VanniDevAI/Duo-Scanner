# Duo Scanner

**Local pickup alerts for the iPhone Duo.**

Duo Scanner watches Apple's retail pickup feed for stores near your ZIP code and alerts you the moment a Duo model you care about flips to available for pickup. It checks on a ~1.2 second cycle, so you hear about stock while it's still there.

It is **notify-only**. It does not reserve phones, check out, enter carrier info, or buy anything. When it alerts, you move fast in the Apple Store app yourself.

## Download

Download **duo-scanner-local-v3.zip** from this repo, unzip it, and follow the quick start below.

## Quick start

1. Install **Python 3.10 or newer**.
   - Windows: install from python.org and check **Add python.exe to PATH**.
   - macOS: run `python3 --version` in Terminal. If Python is missing, install it from python.org.
   - Linux: install Python 3 with your package manager if needed.
2. Open the START file for your computer:
   - Windows: `START_WINDOWS.bat`
   - Mac: `START_MAC.command` (if macOS blocks it, right-click → Open)
   - Linux: `START_LINUX.sh`
3. The first run asks **three questions**:
   - Your ZIP/postal code
   - Which Duo storage size to watch
   - Optional phone alerts
4. Leave the window open while you want alerts. Stop with `Ctrl+C`.

No config editing. Your answers are saved, so later runs start scanning immediately.

## Phone alerts

During setup, type `NEW` when asked about ntfy. Duo Scanner creates a private topic name and shows it on screen. Install the free **ntfy** app, subscribe to that exact topic, and alerts hit your phone as push notifications.

## Speed, honestly

The scanner targets a **1.2 second check cycle**. If Apple's server answers in about a second, the next check starts almost immediately. Your connection and Apple's response time set the real floor, and Apple's store data can lag actual shelf stock — the scanner catches changes the moment Apple's feed changes.

## Requirements

- Python 3.10+
- A computer that stays **awake and online** while scanning (sleep pauses it)

## Read the code first

Every file is in this repo — `duo_scanner.py` is the whole scanner, written with only Python's standard library. Read it before you run it. That's the point of putting it here.

## Limitations

- Apple can change or throttle the feed at any time.
- An alert means Apple's feed showed availability at that moment. It does not hold the phone for you.
- Carrier verification, account blocks, and checkout speed are still on you.
- No guarantees — this is a fast set of eyes, not a reservation.

## Files

- `duo_scanner.py` — the scanner
- `START_HERE.txt` — the short version
- `START_WINDOWS.bat` / `START_MAC.command` / `START_LINUX.sh` — launchers
- `config.example.json` — advanced settings (custom part numbers, store filters, webhooks)
