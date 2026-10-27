#!/usr/bin/env python3
"""
Duo Scanner - local pickup availability alerts.

This is a notify-only tool. It polls Apple's public retail pickup message
feed, watches for selected part numbers near a location, and sends an alert
when a store/part flips to available. It does not reserve, check out, or buy
anything.

Requires Python 3.10+. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
)

_SSL_CONTEXT: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """Return a TLS context that also works on python.org macOS installs.

    Some macOS Python installs cannot find a CA bundle until the user runs
    Python's "Install Certificates" helper. To keep Duo Scanner simple, check
    certifi (when present) and the common operating-system CA bundle paths
    before falling back to Python's default context.
    """
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT

    candidates: list[str] = []
    try:
        import certifi  # type: ignore

        candidates.append(certifi.where())
    except Exception:
        pass
    candidates.extend(
        [
            "/etc/ssl/cert.pem",  # macOS
            "/opt/homebrew/etc/openssl@3/cert.pem",  # Homebrew on Apple Silicon
            "/usr/local/etc/openssl@3/cert.pem",  # Homebrew on Intel Macs
            "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
            "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL/Fedora
        ]
    )
    for path in candidates:
        if path and os.path.exists(path):
            _SSL_CONTEXT = ssl.create_default_context(cafile=path)
            return _SSL_CONTEXT

    _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(path)


@dataclass
class Config:
    location: str
    apple_domain: str
    parts: dict[str, str]
    only_stores: list[str]
    target_cycle_seconds: float
    min_pause_seconds: float
    request_timeout_seconds: float
    cooldown_seconds: float
    alert_on_start_if_available: bool
    desktop_notifications: bool
    beep: bool
    ntfy_topic: str
    ntfy_server: str
    webhook_url: str
    state_file: Path
    log_file: Path

    @classmethod
    def from_file(cls, config_path: Path) -> "Config":
        raw = load_json(config_path)
        base = config_path.parent

        location = str(raw.get("location", "")).strip()
        if not location or location.upper().startswith("YOUR_"):
            raise ValueError("Set 'location' in config.json to your ZIP/postal code first.")

        parts_raw = raw.get("parts") or {}
        if not isinstance(parts_raw, dict) or not parts_raw:
            raise ValueError("Config must include a non-empty 'parts' object: part number -> label.")
        parts = {str(k).strip(): str(v).strip() for k, v in parts_raw.items() if str(k).strip()}

        def rel_path(name: str, default: str) -> Path:
            p = Path(str(raw.get(name, default)))
            return p if p.is_absolute() else base / p

        only_stores = [str(x).strip() for x in raw.get("only_stores", []) if str(x).strip()]

        return cls(
            location=location,
            apple_domain=str(raw.get("apple_domain", "www.apple.com")).strip() or "www.apple.com",
            parts=parts,
            only_stores=only_stores,
            target_cycle_seconds=max(0.3, float(raw.get("target_cycle_seconds", 1.2))),
            min_pause_seconds=max(0.0, float(raw.get("min_pause_seconds", 0.2))),
            request_timeout_seconds=max(2.0, float(raw.get("request_timeout_seconds", 8))),
            cooldown_seconds=max(0.0, float(raw.get("cooldown_seconds", 900))),
            alert_on_start_if_available=bool(raw.get("alert_on_start_if_available", True)),
            desktop_notifications=bool(raw.get("desktop_notifications", True)),
            beep=bool(raw.get("beep", True)),
            ntfy_topic=str(raw.get("ntfy_topic", "")).strip(),
            ntfy_server=str(raw.get("ntfy_server", "https://ntfy.sh")).rstrip("/"),
            webhook_url=str(raw.get("webhook_url", "")).strip(),
            state_file=rel_path("state_file", "duo-scanner-state.json"),
            log_file=rel_path("log_file", "duo-scanner.log"),
        )


PART_PRESETS: dict[str, tuple[str, dict[str, str]]] = {
    "1": (
        "All Night Sky sizes",
        {
            "MK1F4LL/A": "256GB Night Sky",
            "MK1H4LL/A": "512GB Night Sky",
            "MK1L4LL/A": "1TB Night Sky",
            "MK1R4LL/A": "2TB Night Sky",
        },
    ),
    "2": ("Only 256GB Night Sky", {"MK1F4LL/A": "256GB Night Sky"}),
    "3": ("Only 512GB Night Sky", {"MK1H4LL/A": "512GB Night Sky"}),
    "4": ("Only 1TB Night Sky", {"MK1L4LL/A": "1TB Night Sky"}),
    "5": ("Only 2TB Night Sky", {"MK1R4LL/A": "2TB Night Sky"}),
}


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return value or default


def _default_config(location: str, parts: dict[str, str], ntfy_topic: str) -> dict[str, Any]:
    return {
        "location": location,
        "apple_domain": "www.apple.com",
        "parts": parts,
        "only_stores": [],
        "target_cycle_seconds": 1.2,
        "min_pause_seconds": 0.2,
        "request_timeout_seconds": 8,
        "cooldown_seconds": 900,
        "alert_on_start_if_available": True,
        "desktop_notifications": True,
        "beep": True,
        "ntfy_topic": ntfy_topic,
        "ntfy_server": "https://ntfy.sh",
        "webhook_url": "",
        "state_file": "duo-scanner-state.json",
        "log_file": "duo-scanner.log",
    }


def interactive_setup(config_path: Path) -> None:
    print("\nDuo Scanner setup")
    print("-----------------")
    print("Answer three quick questions. No JSON editing needed.\n")

    location = ""
    while not location:
        location = _ask("1) Your ZIP/postal code").strip()
        if location.upper().startswith("YOUR_"):
            location = ""

    print("\n2) Which Duo do you want to watch?")
    for key, (label, _) in PART_PRESETS.items():
        default = " (default)" if key == "1" else ""
        print(f"   {key}. {label}{default}")
    choice = _ask("Choose 1-5", "1")
    if choice not in PART_PRESETS:
        choice = "1"
    _, parts = PART_PRESETS[choice]

    print("\n3) Phone alerts are optional but recommended.")
    print("   Press Enter for computer-only alerts.")
    print("   Type NEW and Duo Scanner will create an ntfy topic for you.")
    print("   Or paste an existing ntfy topic.")
    ntfy_answer = _ask("ntfy topic", "")
    ntfy_topic = ""
    if ntfy_answer.lower() == "new":
        ntfy_topic = "duo-alerts-" + secrets.token_hex(5)
        print("\nPhone setup:")
        print("   1. Install the free ntfy app on your phone.")
        print(f"   2. Subscribe to this exact topic: {ntfy_topic}")
        print("   3. Keep this topic private. Anyone with it can see your alerts.\n")
    elif ntfy_answer:
        ntfy_topic = ntfy_answer

    config_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(config_path, _default_config(location, parts, ntfy_topic))
    print(f"Saved setup to {config_path}")


def config_needs_setup(config_path: Path) -> bool:
    if not config_path.exists():
        return True
    try:
        raw = load_json(config_path)
    except Exception:
        return True
    location = str(raw.get("location", "")).strip()
    return not location or location.upper().startswith("YOUR_")


class Logger:
    def __init__(self, log_file: Path):
        self.log_file = log_file

    def write(self, message: str) -> None:
        line = f"[{now_text()}] {message}"
        print(line, flush=True)
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


class AppleFeed:
    """Client for Apple's pickup-message endpoint.

    Uses urllib so it respects the operating system's normal proxy/network
    settings on Windows, macOS, and Linux. The scanner logic is intentionally
    simple: fetch, parse, diff, alert.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def close(self) -> None:
        pass

    def fetch(self) -> dict[str, Any]:
        query: dict[str, str] = {"pl": "true", "location": self.cfg.location}
        for i, part in enumerate(self.cfg.parts.keys()):
            query[f"parts.{i}"] = part
        url = (
            f"https://{self.cfg.apple_domain}/shop/retail/pickup-message?"
            + urllib.parse.urlencode(query)
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Encoding": "identity",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self.cfg.request_timeout_seconds, context=ssl_context()) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Apple feed returned HTTP {resp.status}")
            body = resp.read()
        return json.loads(body.decode("utf-8"))


def entry_is_available(entry: dict[str, Any]) -> bool:
    if entry.get("sel") is True:
        return True
    display = str(entry.get("display") or "").strip().lower()
    if display in {"available", "available today", "available for pickup"}:
        return True
    quote = str(entry.get("quote") or "").strip().lower()
    if quote.startswith("available"):
        return True
    return False


def build_snapshot(feed_json: dict[str, Any], cfg: Config) -> dict[str, dict[str, Any]]:
    snap: dict[str, dict[str, Any]] = {}
    stores = feed_json.get("body", {}).get("stores", []) or []
    only = {s.lower() for s in cfg.only_stores}

    for store in stores:
        store_number = str(store.get("storeNumber") or "")
        store_name = str(store.get("storeName") or store_number)
        if only:
            haystacks = {store_number.lower(), store_name.lower()}
            if not (only & haystacks):
                continue
        parts_avail = store.get("partsAvailability", {}) or {}
        for part in cfg.parts.keys():
            info = parts_avail.get(part)
            if not info:
                continue
            regular = (info.get("messageTypes") or {}).get("regular") or {}
            entry = {
                "store_number": store_number,
                "store": store_name,
                "part": part,
                "label": cfg.parts[part],
                "quote": info.get("pickupSearchQuote"),
                "display": info.get("pickupDisplay"),
                "sel": regular.get("storeSelectionEnabled"),
                "available": False,
            }
            entry["available"] = entry_is_available(entry)
            snap[f"{store_number}|{part}"] = entry
    return snap


def beep() -> None:
    try:
        if platform.system() == "Windows":
            import winsound

            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        else:
            print("\a", end="", flush=True)
    except Exception:
        print("\a", end="", flush=True)


def desktop_notify(title: str, message: str) -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
            subprocess.run(["osascript", "-e", script], check=False, timeout=3)
        elif system == "Linux":
            subprocess.run(["notify-send", title, message], check=False, timeout=3)
        elif system == "Windows":
            # Keep Windows dependency-free: the console alert and beep are the
            # reliable built-ins. Phone push is covered by ntfy/webhook.
            pass
    except Exception:
        pass


def post_url(url: str, data: bytes, headers: dict[str, str], timeout: float = 5.0) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        resp.read(200)


def send_notifications(cfg: Config, logger: Logger, title: str, message: str) -> None:
    logger.write(f"ALERT: {title} - {message}")
    if cfg.beep:
        beep()
    if cfg.desktop_notifications:
        desktop_notify(title, message)

    if cfg.ntfy_topic:
        topic_url = f"{cfg.ntfy_server}/{urllib.parse.quote(cfg.ntfy_topic)}"
        try:
            post_url(
                topic_url,
                message.encode("utf-8"),
                {"Title": title, "Tags": "rotating_light", "Priority": "high"},
            )
        except Exception as exc:
            logger.write(f"ntfy notification failed: {exc}")

    if cfg.webhook_url:
        payload = json.dumps({"title": title, "message": message, "time": now_text()}).encode("utf-8")
        try:
            post_url(cfg.webhook_url, payload, {"Content-Type": "application/json"})
        except Exception as exc:
            logger.write(f"webhook notification failed: {exc}")


def format_alert(entry: dict[str, Any]) -> tuple[str, str]:
    label = entry.get("label") or entry.get("part")
    store = entry.get("store") or entry.get("store_number")
    title = f"DUO {label} - {store} - GO"
    quote = entry.get("quote") or entry.get("display") or "Available"
    message = f"{label} is available for pickup at {store}. Apple says: {quote}. Check the Apple Store app now."
    return title, message


def _is_rate_limit(exc: Exception) -> bool:
    """Apple/Akamai answer HTTP 541 when a connection is being rate-limited."""
    if getattr(exc, "code", None) == 541:
        return True
    text = str(exc)
    return "HTTP Error 541" in text or " 541:" in text


def _rate_limit_delay(streak: int) -> float:
    """Patient exponential backoff for rate limits: 60s, 120s, 240s... max 10 min."""
    return min(600.0, 60.0 * (2 ** max(0, streak - 1)))


def run_once(feed: AppleFeed, cfg: Config, logger: Logger, state: dict[str, Any]) -> dict[str, Any]:
    feed_json = feed.fetch()
    snap = build_snapshot(feed_json, cfg)
    old_entries: dict[str, Any] = state.get("entries") or {}
    last_alert: dict[str, Any] = state.get("last_alert") or {}
    first_run = not old_entries and not state.get("baseline_done")
    now = time.time()
    alerts: list[dict[str, Any]] = []

    for key, entry in snap.items():
        prev = old_entries.get(key)
        prev_available = bool(prev and prev.get("available"))
        is_available = bool(entry.get("available"))

        if is_available:
            transitioned = not prev_available
            start_alert = first_run and cfg.alert_on_start_if_available
            cooled_down = now - float(last_alert.get(key, 0)) >= cfg.cooldown_seconds
            if transitioned or start_alert or cooled_down:
                # Avoid re-alerting continuously for an item that simply stays
                # available unless the cooldown has fully elapsed.
                if transitioned or start_alert or cooled_down:
                    alerts.append(entry)
                    last_alert[key] = now
        else:
            last_alert.pop(key, None)

    # If an item disappears from the feed entirely, clear its alert timer so a
    # later reappearance can alert immediately.
    for key in list(last_alert.keys()):
        if key not in snap:
            last_alert.pop(key, None)

    for entry in alerts:
        title, message = format_alert(entry)
        send_notifications(cfg, logger, title, message)

    state["entries"] = snap
    state["last_alert"] = last_alert
    state["baseline_done"] = True
    state["updated_at"] = now_text()
    save_json(cfg.state_file, state)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local iPhone Duo pickup availability scanner")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    parser.add_argument("--test-alert", action="store_true", help="Send a test alert and exit")
    parser.add_argument("--setup", action="store_true", help="Run the simple setup wizard and exit")
    parser.add_argument("--reset-state", action="store_true", help="Delete saved scanner state and exit")
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser()
    if args.setup:
        interactive_setup(config_path)
        return 0

    if config_needs_setup(config_path):
        if sys.stdin.isatty():
            interactive_setup(config_path)
        else:
            print(f"Setup needed for: {config_path}", file=sys.stderr)
            print("Run with --setup, or use one of the START files and answer the setup questions.", file=sys.stderr)
            return 2

    try:
        cfg = Config.from_file(config_path)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    logger = Logger(cfg.log_file)

    if args.reset_state:
        try:
            cfg.state_file.unlink(missing_ok=True)
            print(f"Deleted state file: {cfg.state_file}")
        except OSError as exc:
            print(f"Could not delete state file: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.test_alert:
        send_notifications(cfg, logger, "DUO Scanner test", "Test alert from Duo Scanner. Notifications are working.")
        return 0

    state: dict[str, Any] = {}
    if cfg.state_file.exists():
        try:
            state = load_json(cfg.state_file)
        except Exception:
            state = {}

    feed = AppleFeed(cfg)
    logger.write(
        "Duo Scanner started. Location="
        f"{cfg.location}; parts={len(cfg.parts)}; target_cycle={cfg.target_cycle_seconds:.1f}s; "
        "notify-only; press Ctrl+C to stop."
    )

    failures = 0
    rate_limit_streak = 0
    try:
        while True:
            cycle_start = time.monotonic()
            try:
                state = run_once(feed, cfg, logger, state)
                failures = 0
                rate_limit_streak = 0
            except Exception as exc:
                feed.close()
                if args.once:
                    logger.write(f"Scan failed: {exc}")
                    return 1
                if _is_rate_limit(exc):
                    rate_limit_streak += 1
                    delay = _rate_limit_delay(rate_limit_streak)
                    if rate_limit_streak == 1:
                        logger.write(
                            "Apple is rate-limiting this connection (HTTP 541). "
                            "The scanner will slow down and keep trying on its own. "
                            "Restarting will not help — waiting does."
                        )
                    logger.write(f"Rate-limited by Apple (HTTP 541). Next check in {int(delay)}s.")
                    time.sleep(delay)
                    continue
                failures += 1
                logger.write(f"Scan failed ({failures} in a row): {exc}")
                backoff = min(30.0, max(cfg.min_pause_seconds, failures * 2.0))
                time.sleep(backoff)
                continue

            if args.once:
                return 0

            elapsed = time.monotonic() - cycle_start
            sleep_for = max(cfg.min_pause_seconds, cfg.target_cycle_seconds - elapsed)
            # If Apple's response was slower than the target, start again almost
            # immediately. The scanner can target a 1.2s cadence; it cannot make
            # Apple's servers answer faster than they do.
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        logger.write("Duo Scanner stopped.")
        return 0
    finally:
        feed.close()


if __name__ == "__main__":
    raise SystemExit(main())
