# Duo Scanner - local pickup alerts

Duo Scanner watches Apple's pickup feed and alerts you when selected iPhone Duo models become available near you.

It is **notify-only**. It does not reserve a phone, check out, enter carrier information, or buy anything. When it alerts, move fast in the Apple Store app yourself.

## Simplest setup

1. Install Python 3.10 or newer.
   - Windows: install from python.org and check **Add python.exe to PATH**.
   - macOS: run `python3 --version` in Terminal. If Python is missing, install it from python.org.
   - Linux: install Python 3 with your package manager if needed.

2. Open the START file for your computer:
   - Windows: `START_WINDOWS.bat`
   - Mac: `START_MAC.command` — if macOS blocks it, right-click it and choose Open.
   - Linux: `START_LINUX.sh`

3. The first run asks four questions:
   - Your ZIP/postal code
   - Which color to watch: Night Sky, Star White, or both
   - Which Duo storage size to watch
   - Optional phone alerts

4. Leave the window open while you want alerts. Stop with `Ctrl+C`.

No JSON editing is needed for normal use. The setup saves your answers to `config.json`.

## Phone alerts

During setup, type `NEW` when asked about ntfy. Duo Scanner will create a private topic name and show it on screen. Install the free **ntfy** app, subscribe to that exact topic, and your phone can receive push alerts.

You can also press Enter to skip phone alerts and use computer alerts only.

## Speed

Duo Scanner targets a **1.2 second cycle**. If Apple's server answers in about one second, the next check starts almost immediately.

That is a target, not a guarantee. Your connection and Apple's response time set the floor, and Apple's store data can lag real shelf stock. The scanner catches changes when Apple's feed changes.

## If you need to change something later

Run setup again:

```bash
python3 duo_scanner.py --config config.json --setup
```

Windows may need:

```bat
py -3 duo_scanner.py --config config.json --setup
```

Test alerts:

```bash
python3 duo_scanner.py --config config.json --test-alert
```

Advanced users can edit `config.json` directly. `config.example.json` shows the available fields, including custom part numbers, store filters, webhook alerts, and cooldown timing.

## Honest limitations

- Apple can change or throttle the feed at any time.
- If Apple rate-limits your connection (HTTP 541), the scanner backs off automatically and keeps trying on its own. Leave the window open — restarting doesn't help, waiting does.
- An alert means Apple's feed showed availability at that moment. It does not hold the phone.
- Carrier verification, account blocks, and checkout speed are still on the buyer.
- Keep the computer awake and online while scanning. Sleep pauses the scanner.
- Use it for your own purchase alerts. Check the retailer's terms and do not use it to automate checkout.

## Files

- `START_HERE.txt` - the short version.
- `START_WINDOWS.bat`, `START_MAC.command`, `START_LINUX.sh` - start here.
- `duo_scanner.py` - the scanner. Python standard library only.
- `config.example.json` - advanced/manual settings reference.
- `config.json` - created by setup.
- `duo-scanner-state.json` and `duo-scanner.log` - created while running.
