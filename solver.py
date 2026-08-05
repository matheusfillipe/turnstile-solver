import asyncio
import json
import os
import platform
import random
import shutil
import subprocess
import threading
import time
from typing import Optional

import nodriver as uc

# Cloudflare scores the browser itself, so this only works with STOCK Chrome driven
# by nodriver. A patched Chromium or a Playwright/CDP-driven browser gets served the
# interactive challenge instead of a silent pass, whatever the IP says.
CHROME_CANDIDATES_POSIX = (
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
CHROME_CANDIDATES_WINDOWS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)

_profile_lock = threading.Lock()
_profile_pool: list[str] = []
_profile_next = 0


def _find_chrome() -> str:
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]

    candidates = CHROME_CANDIDATES_WINDOWS if platform.system() == "Windows" else CHROME_CANDIDATES_POSIX
    for path in candidates:
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "Chrome not found in default locations. Set CHROME_PATH to your Chrome executable."
    )


def _profile_root() -> str:
    return os.environ.get("TS_PROFILE_DIR", "/tmp/ts_profile")


def _acquire_profile() -> str:
    """Hand out a private profile directory per concurrent solve.

    Chrome holds a singleton lock on its user-data-dir, so concurrent workers
    sharing one directory serialise or fail outright. Profiles are pooled rather
    than made fresh each time because Cloudflare reads a warmed profile as a
    returning visitor, which is most of why this passes at all.
    """
    global _profile_next
    with _profile_lock:
        if _profile_pool:
            return _profile_pool.pop()
        path = f"{_profile_root()}_{_profile_next}"
        _profile_next += 1
        return path


def _release_profile(path: str, *, keep: bool) -> None:
    """Return a working profile to the pool; bin one that just failed.

    A warm profile eventually turns into a poisoned one — Cloudflare stops
    issuing tokens to it and every later solve inherits the same dead state,
    so the service fails permanently until someone wipes the directory.
    """
    if not keep:
        shutil.rmtree(path, ignore_errors=True)
        return
    with _profile_lock:
        _profile_pool.append(path)


async def _solve(sitekey: str, siteurl: str, timeout: int) -> str:
    profile = _acquire_profile()
    browser = None
    token: Optional[str] = None
    try:
        browser = await uc.start(
            browser_executable_path=_find_chrome(),
            headless=False,
            user_data_dir=profile,
            # Chrome refuses to run as root without this, and containers run as root.
            sandbox=False,
        )
        page = await browser.get(siteurl)
        await asyncio.sleep(random.uniform(2.0, 3.0))

        await page.evaluate(f"""
            (() => {{
                if (document.getElementById('_ts_box')) return;
                window._tsToken = null;
                const wrap = document.createElement('div');
                wrap.id = '_ts_box';
                wrap.style = 'position:fixed;top:20px;left:20px;z-index:2147483647;';
                document.body.appendChild(wrap);
                window._tsLoad = function () {{
                    turnstile.render('#_ts_box', {{
                        sitekey: '{sitekey}',
                        callback: function(token) {{ window._tsToken = token; }}
                    }});
                }};
                const s = document.createElement('script');
                s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?onload=_tsLoad&render=explicit';
                s.async = true;
                document.head.appendChild(s);
            }})();
        """)

        await asyncio.sleep(5.0)

        async def get_token() -> Optional[str]:
            return await page.evaluate("""
                (() => {
                    if (window._tsToken) return window._tsToken;
                    const inp = document.querySelector('#_ts_box [name="cf-turnstile-response"]');
                    return (inp && inp.value) ? inp.value : null;
                })()
            """)

        async def get_cf_iframe_rect() -> Optional[dict]:
            raw = await page.evaluate("""
                JSON.stringify((() => {
                    for (const f of document.querySelectorAll('iframe')) {
                        const src = f.src || f.getAttribute('src') || '';
                        if (!src.includes('challenges.cloudflare.com')) continue;
                        const r = f.getBoundingClientRect();
                        if (r.width > 50 && r.height > 20) return {x:r.x, y:r.y, w:r.width, h:r.height};
                    }
                    return null;
                })())
            """)
            if raw and raw != "null":
                return json.loads(raw)
            return None

        async def do_click(rect: Optional[dict]) -> None:
            if rect:
                cx = rect["x"] + 28 + random.uniform(-3, 3)
                cy = rect["y"] + rect["h"] / 2 + random.uniform(-3, 3)
            else:
                cx = 20 + 28 + random.uniform(-3, 3)
                cy = 20 + 32 + random.uniform(-3, 3)
            await page.mouse_move(cx - 80, cy - 20)
            await asyncio.sleep(random.uniform(0.15, 0.25))
            await page.mouse_move(cx, cy)
            await asyncio.sleep(random.uniform(0.08, 0.15))
            await page.mouse_click(cx, cy)

        token = await get_token()
        if token:
            return token

        rect = None
        for _ in range(20):
            rect = await get_cf_iframe_rect()
            if rect:
                break
            await asyncio.sleep(0.5)

        deadline = asyncio.get_event_loop().time() + timeout
        click_count = 0
        last_click = 0.0

        while asyncio.get_event_loop().time() < deadline:
            token = await get_token()
            if token:
                break

            now = asyncio.get_event_loop().time()
            if click_count == 0 or now - last_click > 8:
                if click_count >= 3:
                    await asyncio.sleep(0.3)
                    continue
                await do_click(rect)
                last_click = asyncio.get_event_loop().time()
                click_count += 1
                await asyncio.sleep(1.0)
                rect = await get_cf_iframe_rect() or rect
                continue

            await asyncio.sleep(0.3)
    finally:
        if browser is not None:
            browser.stop()
        _release_profile(profile, keep=token is not None)

    if not token:
        raise TimeoutError(f"Turnstile token not obtained within {timeout}s")

    return token


def solve(sitekey: str, siteurl: str, timeout: int = 45) -> str:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return asyncio.run(_solve(sitekey, siteurl, timeout))


def start_display() -> Optional[subprocess.Popen]:
    """Chrome needs a real display even when nobody is looking at it: headless mode
    is itself a detection signal, so servers get a virtual one instead."""
    if platform.system() != "Linux" or os.environ.get("DISPLAY"):
        return None
    if not shutil.which("Xvfb"):
        raise FileNotFoundError("Xvfb is required on Linux. Install it or set DISPLAY.")
    proc = subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x900x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.environ["DISPLAY"] = ":99"
    time.sleep(0.5)
    return proc


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python solver.py <sitekey> <siteurl>")
        sys.exit(1)

    xvfb = start_display()
    try:
        print(solve(sys.argv[1], sys.argv[2]))
    finally:
        if xvfb:
            xvfb.terminate()
