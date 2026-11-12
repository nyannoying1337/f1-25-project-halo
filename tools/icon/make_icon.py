"""Draw the addon icon (icons/halo.png, 256 x 256 RGB) from tools/halo.js: the 2026 dial with its collar, centred and
whole, over a flat grey. Saira (SIL OFL 1.1) only; no game or broadcast artwork.

usage, from the addon root:
    python -I tools/icon/make_icon.py icons/halo.png --chrome "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"

Options: --size (px, default 256), --scale (px per HUD unit, default 2.95: the collar's edge, r 39.37 units, about
12 px inside the icon's edge), --profile (browser profile folder, a new one per run). One headless browser run
(tools/icon/icon.html).
"""
import argparse
import base64
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

_USER_SITE = os.path.join(os.environ.get('APPDATA', ''), 'Python', 'Python%d%d' % sys.version_info[:2], 'site-packages')
if os.path.isdir(_USER_SITE) and _USER_SITE not in sys.path:
    sys.path.append(_USER_SITE)      # Pillow may live in the user site, which python -I leaves out
from PIL import Image  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--chrome', default=os.environ.get('CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe'))
    ap.add_argument('--size', type=int, default=256)
    ap.add_argument('--scale', type=float, default=2.95)
    ap.add_argument('--profile', default=os.path.join(tempfile.gettempdir(), 'halo-icon-browser'))
    a = ap.parse_args()
    run = os.path.join(a.profile, 'run_%d_%d' % (os.getpid(), time.time_ns()))
    url = 'file:///' + os.path.join(HERE, 'icon.html').replace('\\', '/') + f'?size={a.size}&scale={a.scale}'
    cmd = [a.chrome, '--headless=new', '--disable-gpu', '--allow-file-access-from-files', '--virtual-time-budget=60000',
           '--user-data-dir=' + run, '--dump-dom', url]
    res = subprocess.run(cmd, capture_output=True, timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', res.stdout.decode('utf-8', 'replace'), re.S)
    if not m or not html.unescape(m.group(1)).startswith('{'):
        raise SystemExit(f'icon.html failed (exit {res.returncode}): {(m and html.unescape(m.group(1))[:600])!r} '
                         f'{res.stderr[-300:]!r}')
    got = json.loads(html.unescape(m.group(1)))
    if not got['fontLoaded']:
        raise SystemExit('Saira did not load (tools/tower/saira.ttf)')
    im = Image.open(io.BytesIO(base64.b64decode(got['png'].split(',', 1)[1]))).convert('RGB')
    assert im.size == (a.size, a.size), im.size
    im.save(a.out, optimize=True)
    print(f'{a.out}: {im.size[0]} x {im.size[1]} RGB, scale {a.scale} px per HUD unit')


if __name__ == '__main__':
    main()
