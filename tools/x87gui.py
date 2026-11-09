#!/usr/bin/env python3
"""Local web UI for the Attack Shark X87 (wired)."""
import json, os, secrets, subprocess, sys, threading, time, traceback, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import x87ctl as x

GUI = ROOT / "gui"
TOKEN = secrets.token_urlsafe(24)
LOCK = threading.Lock()
LAYOUT = x.load_layout()

MOD_NAMES = {0x01:"Left Ctrl",0x02:"Left Shift",0x04:"Left Alt",0x08:"Left Win",
             0x10:"Right Ctrl",0x20:"Right Shift",0x40:"Right Alt",0x80:"Right Win"}
MEDIA_NAMES = {0xCD:"Play/Pause",0xB5:"Next Track",0xB6:"Previous Track",0xB7:"Stop",
               0xE2:"Mute",0xE9:"Volume Up",0xEA:"Volume Down",0x6F:"Brightness Up",
               0x70:"Brightness Down",0x221:"Search",0x192:"Calculator",0x223:"Browser Home",
               0x18A:"Email",0x183:"Media Select",0x32:"Sleep (Consumer)",0x30:"Power (Consumer)"}
COMBO_NAMES = {(0x08,0x2C):"Spotlight (Cmd+Space)",(0x08,0x2B):"App Switcher (Cmd+Tab)",
               (0x08,0x35):"Window Switcher (Cmd+`)",(0x01,0x52):"Mission Control (Ctrl+Up)",
               (0x05,0x07):"Dictation (Ctrl+Option+D)",(0x0A,0x20):"Screenshot (Cmd+Shift+3)",
               (0x09,0x2C):"Emoji (Ctrl+Cmd+Space)",(0x09,0x14):"Lock Screen (Ctrl+Cmd+Q)",
               (0x04,0x2B):"Alt/Option+Tab",(0x01,0x2C):"Ctrl+Space"}
REV_HID = {}
PRETTY = {"esc":"Esc","escape":"Esc","tab":"Tab","caps":"Caps Lock","capslock":"Caps Lock",
          "enter":"Enter","return":"Enter","space":"Space","backspace":"Backspace","bksp":"Backspace",
          "delete":"Delete","del":"Delete","insert":"Insert","ins":"Insert","home":"Home","end":"End",
          "pageup":"Page Up","pgup":"Page Up","pagedown":"Page Down","pgdn":"Page Down",
          "right":"Right","left":"Left","down":"Down","up":"Up","printscreen":"Print Screen",
          "prtsc":"Print Screen","scrolllock":"Scroll Lock","pause":"Pause"}
for name, usage in sorted(x.HID.items(), key=lambda kv: (len(kv[0]), kv[0])):
    if usage in REV_HID:
        continue
    REV_HID[usage] = name.upper() if len(name) == 1 else PRETTY.get(name, name.title())

def decode_entry(b):
    if b == bytes([0,0,0,0]):
        return "Disabled"
    if b[1] and not b[0] and not b[2] and not b[3]:
        return MOD_NAMES.get(b[1], f"Modifier 0x{b[1]:02x}")
    if b[0] == 0x0d:
        return "Fn"
    if b[0] == 0 and b[1] and b[3]:
        name = COMBO_NAMES.get((b[1], b[3]))
        return name if name else f"Mods 0x{b[1]:02x} + " + REV_HID.get(b[3], f"HID 0x{b[3]:02x}")
    if b[0] == 0 and b[1] == 0 and b[2] == 0:
        sysnames = {0x81:"Power (Keyboard)",0x82:"Sleep (Keyboard)",0x83:"Wake Up (Keyboard)"}
        if b[3] in sysnames:
            return sysnames[b[3]]
        return REV_HID.get(b[3], f"HID 0x{b[3]:02x}")
    if b[0] == 0x02:
        usage = (b[2] << 8) | b[3]
        return MEDIA_NAMES.get(usage, f"Consumer 0x{usage:04x}")
    return "Custom " + b.hex(" ")

def palette():
    raw = (x.BACKUP / "colors.bin").read_bytes()[8:29]
    return [list(raw[i:i+3]) for i in range(0, 21, 3)]

def status_dict():
    try:
        cfg = x.read_block(0x84, 0, 128)
    except Exception as e:
        msg = str(e)
        if "0xe00002e2" in msg:
            return {"connected": False, "error": "permission",
                    "message": "macOS blocked HID access. Grant Input Monitoring to X87 Configurator."}
        return {"connected": False, "error": msg}
    hw, eff, bright, speed, color = x.current_values(LAYOUT, cfg)
    return {
        "connected": True,
        "name": LAYOUT["opt"].get("name", "X87 Keyboard"),
        "vid": LAYOUT["opt"].get("vid", "0x258a"),
        "pid": LAYOUT["opt"].get("pid", "0x010c"),
        "effect": {"name": eff["name"] if eff else f"Unknown {hw}", "hw": hw,
                   "ui": eff["ui"] if eff else 0, "slot": eff["index"] if eff else -1},
        "brightness": bright, "speed": speed, "color": color,
        "profile": "mac" if cfg[0x1B] == 0x02 else "win",
        "effects": [{"name": e["name"], "hw": e["hw"], "ui": e["ui"], "slot": e["index"]}
                    for e in LAYOUT["effects"] if e["name"] != "Self-define"],
        "palette": palette(),
    }

def keys_dict(layer):
    kb = x.read_block(0x83, layer, 512)
    out = []
    for k in LAYOUT["keys"]:
        e = kb[k["led"]*4:k["led"]*4+4]
        out.append({"name": k["name"], "led": k["led"], "x": k["x"], "y": k["y"],
                    "w": k["w"], "h": k["h"], "entry": e.hex(" "),
                    "output": decode_entry(e)})
    return {"layer": layer, "keys": out}

def outputs_list():
    groups = [
        ("Special", [("Disable", "disable")]),
        ("Media", [("Play/Pause","media:play_pause"),("Next Track","media:next"),
                   ("Previous Track","media:prev"),("Stop","media:stop"),("Mute","media:mute"),
                   ("Volume Up","media:vol_up"),("Volume Down","media:vol_down"),
                   ("Brightness Up","media:bright_up"),("Brightness Down","media:bright_down"),
                   ("Search","media:search"),("Calculator","media:calc"),
                   ("Browser Home","media:home"),("Email","media:email"),
                   ("Media Select","media:select")]),
        ("Mac shortcuts", [("Spotlight (Cmd+Space)","combo:spotlight"),
                           ("App Switcher (Cmd+Tab)","combo:app_switcher"),
                           ("Window Switcher (Cmd+`)","combo:window_switcher"),
                           ("Mission Control (Ctrl+Up)","combo:mission_control"),
                           ("Screenshot (Cmd+Shift+3)","combo:screenshot"),
                           ("Emoji (Ctrl+Cmd+Space)","combo:emoji"),
                           ("Lock Screen (Ctrl+Cmd+Q)","combo:lock"),
                           ("Alt/Option+Tab","combo:alt_tab"),("Ctrl+Space","combo:ctrl_space")]),
        ("Letters", [(c.upper(), c) for c in "abcdefghijklmnopqrstuvwxyz"]),
        ("Digits", [(c, c) for c in "1234567890"]),
        ("Function", [(f"F{i}", f"f{i}") for i in range(1, 13)]),
        ("Navigation", [("Esc","esc"),("Tab","tab"),("Caps Lock","caps"),("Enter","enter"),
                        ("Space","space"),("Backspace","backspace"),("Delete","delete"),
                        ("Insert","insert"),("Home","home"),("End","end"),("Page Up","pageup"),
                        ("Page Down","pagedown"),("Up","up"),("Down","down"),("Left","left"),
                        ("Right","right"),("Print Screen","prtsc"),("Scroll Lock","srclock"),
                        ("Pause","pause")]),
        ("Modifiers", [("Left Ctrl","lctrl"),("Left Shift","lshift"),("Left Alt","lalt"),
                       ("Left Win","lwin"),("Right Ctrl","rctrl"),("Right Shift","rshift"),
                       ("Right Alt","ralt"),("Right Win","rwin")]),
        ("Symbols", [("-","-"),("=","="),("[","["),("]","]"),("\\","\\"),(";",";"),("'","'"),
                     ("`","`"),(",",","),(".","."),("/","/")]),
    ]
    return [{"group": g, "items": [{"name": n, "value": v} for n, v in items]} for g, items in groups]

def apply_lighting(data):
    name = data.get("effect")
    cfg = x.read_block(0x84, 0, 128)
    eff = None
    for e in LAYOUT["effects"]:
        if e["name"] == name:
            eff = e; break
    if not eff:
        raise ValueError(f"unknown effect {name!r}")
    new = bytearray(cfg)
    new[10] = eff["hw"]
    off = 0x3A + 2*eff["index"]
    new[off] = int(data.get("brightness", 4)) & 0x0F
    new[off+1] = ((int(data.get("speed", 2)) & 0x0F) << 4) | (int(data.get("color", 7)) & 0x0F)
    x.apply_config(bytes(new), "gui-lighting")
    return status_dict()

def set_key(data):
    layer = int(data.get("layer", 0))
    src = x.find_key(LAYOUT, data["source"])
    if x._clean_name(src["name"]) == "fn":
        raise ValueError("refusing to remap the Fn key")
    entry = x.output_entry(data["output"])
    kb = x.read_block(0x83, layer, 512)
    new = bytearray(kb)
    new[src["led"]*4:src["led"]*4+4] = entry
    x.apply_keymap(bytes(new), layer, f"gui-key-{src['name']}")
    return keys_dict(layer)

def reset_key(data):
    layer = int(data.get("layer", 0))
    src = x.find_key(LAYOUT, data["source"])
    default = (x.BACKUP / ("keys-fn.bin" if layer else "keys-base.bin")).read_bytes()[8:]
    kb = x.read_block(0x83, layer, 512)
    new = bytearray(kb)
    new[src["led"]*4:src["led"]*4+4] = default[src["led"]*4:src["led"]*4+4]
    x.apply_keymap(bytes(new), layer, f"gui-reset-{src['name']}")
    return keys_dict(layer)

def restore_original():
    x.apply_config((x.BACKUP / "config.bin").read_bytes()[8:], "gui-restore-original")
    for layer, name in ((0, "keys-base.bin"), (1, "keys-fn.bin")):
        x.apply_keymap((x.BACKUP / name).read_bytes()[8:], layer, "gui-restore-original")
    return status_dict()

def undo_last():
    files = sorted((x.PROFILES).glob("*.bin"), key=lambda p: p.stat().st_mtime, reverse=True)
    files = [p for p in files if p.stat().st_size == 128]
    if not files:
        raise ValueError("no previous config backup found")
    payload = files[0].read_bytes()
    x.apply_config(payload, "gui-undo")
    return status_dict()

def make_backup():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = x.BACKUP / f"gui-{ts}"
    p = subprocess.run([str(ROOT/"tools"/"x87backup"), str(dest)], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stdout + p.stderr).strip())
    return str(dest)

FROW_LEDS = [12,18,24,30,36,42,48,54,60,66,72,78]
FKEY = {led: bytes([0,0,0,0x3A+i]) for i, led in enumerate(FROW_LEDS)}

PROFILE_PREFS = x.PROFILES / "frow.json"

def load_frow_prefs():
    try:
        d = json.loads(PROFILE_PREFS.read_text())
        return {"win": d.get("win", "fkeys"), "mac": d.get("mac", "media")}
    except Exception:
        return {"win": "fkeys", "mac": "media"}

def save_frow_prefs(prefs):
    x.PROFILES.mkdir(exist_ok=True)
    PROFILE_PREFS.write_text(json.dumps(prefs, indent=2))

def os_mode():
    cfg = x.read_block(0x84, 0, 128)
    return "mac" if cfg[0x1B] == 0x02 else "win"

def read_frow():
    return x.read_block(0x83, 0, 512), x.read_block(0x83, 1, 512)

def fkeys_on_base(base):
    return sum(1 for led in FROW_LEDS if base[led*4:led*4+4] == FKEY[led])

def current_layout():
    base, _ = read_frow()
    n = fkeys_on_base(base)
    return "A" if n == 12 else ("B" if n == 0 else "custom")

def target_layout(profile, prefs):
    want = prefs.get(profile, "fkeys")
    if want == "fkeys":
        return "A" if profile == "win" else "B"
    return "B" if profile == "win" else "A"

def frow_state():
    base, fn = read_frow()
    n = fkeys_on_base(base)
    primary = "fkeys" if n == 12 else ("media" if n == 0 else "custom")
    prefs = load_frow_prefs()
    mode = "mac" if x.read_block(0x84, 0, 128)[0x1B] == 0x02 else "win"
    return {"primary": primary, "fkeys_on_base": n, "media_on_base": 12-n,
            "os_mode": mode, "prefs": prefs, "target": target_layout(mode, prefs),
            "current_layout": "A" if n == 12 else ("B" if n == 0 else "custom"),
            "base": [base[led*4:led*4+4].hex(" ") for led in FROW_LEDS],
            "fn": [fn[led*4:led*4+4].hex(" ") for led in FROW_LEDS]}

def write_keymaps(base, fn):
    old_base = x.read_block(0x83, 0, 512)
    old_fn = x.read_block(0x83, 1, 512)
    x.save_keymap(old_base, 0, "before-frow-sync")
    x.save_keymap(old_fn, 1, "before-frow-sync")
    try:
        x.write_block(0x03, 0, 512, bytes(base))
        if x.read_block(0x83, 0, 512) != bytes(base):
            raise RuntimeError("base keymap readback mismatch")
        x.write_block(0x03, 1, 512, bytes(fn))
        if x.read_block(0x83, 1, 512) != bytes(fn):
            raise RuntimeError("Fn keymap readback mismatch")
    except Exception:
        x.write_block(0x03, 0, 512, old_base)
        x.write_block(0x03, 1, 512, old_fn)
        raise

def swap_frow():
    base = bytearray(x.read_block(0x83, 0, 512))
    fn = bytearray(x.read_block(0x83, 1, 512))
    for led in FROW_LEDS:
        i = led * 4
        base[i:i+4], fn[i:i+4] = fn[i:i+4], base[i:i+4]
    write_keymaps(base, fn)
    return frow_state()

def force_layout(target):
    base = bytearray(x.read_block(0x83, 0, 512))
    fn = bytearray(x.read_block(0x83, 1, 512))
    media = (x.BACKUP / "keys-fn.bin").read_bytes()[8:]
    for i, led in enumerate(FROW_LEDS):
        if target == "A":
            base[led*4:led*4+4] = FKEY[led]
            fn[led*4:led*4+4] = media[led*4:led*4+4]
        else:
            base[led*4:led*4+4] = media[led*4:led*4+4]
            fn[led*4:led*4+4] = FKEY[led]
    write_keymaps(base, fn)

def ensure_layout(target):
    if target not in ("A", "B"):
        return
    cur = current_layout()
    if cur == target:
        return
    if cur in ("A", "B"):
        swap_frow()
    else:
        force_layout(target)

def set_profile_mode(profile, want):
    if profile not in ("win", "mac") or want not in ("fkeys", "media"):
        raise ValueError("profile must be win/mac and mode must be fkeys/media")
    if profile == "mac":
        raise ValueError("Mac mode uses a firmware keymap; the F row is fixed by the keyboard.")
    prefs = load_frow_prefs()
    prefs[profile] = want
    save_frow_prefs(prefs)
    if os_mode() == profile:
        ensure_layout(target_layout(profile, prefs))
    return frow_state()

class Handler(BaseHTTPRequestHandler):
    server_version = "X87GUI/1.0"
    def log_message(self, fmt, *args):
        pass
    def _token_ok(self):
        return self.headers.get("X-X87-Token") == TOKEN
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def _json_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")
    def _serve_file(self, name, ctype):
        p = GUI / name
        if not p.exists():
            self._send(404, {"error": "not found"}); return
        self._send(200, p.read_bytes(), ctype)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            html = (GUI / "index.html").read_text()
            html = html.replace("__TOKEN__", TOKEN)
            self._send(200, html, "text/html; charset=utf-8"); return
        if path == "/style.css": return self._serve_file("style.css", "text/css")
        if path == "/app.js": return self._serve_file("app.js", "application/javascript")
        if path == "/keyimg.png": return self._serve_file("keyimg.png", "image/png")
        if not self._token_ok():
            self._send(401, {"error": "unauthorized"}); return
        try:
            if path == "/api/status": self._send(200, status_dict())
            elif path == "/api/keys":
                q = urlparse(self.path).query
                layer = 1 if "layer=1" in q else 0
                self._send(200, keys_dict(layer))
            elif path == "/api/outputs": self._send(200, outputs_list())
            elif path == "/api/frow": self._send(200, frow_state())
            else: self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})
    def do_POST(self):
        if not self._token_ok():
            self._send(401, {"error": "unauthorized"}); return
        path = urlparse(self.path).path
        try:
            data = self._json_body()
            with LOCK:
                if path == "/api/lighting": self._send(200, apply_lighting(data))
                elif path == "/api/key": self._send(200, set_key(data))
                elif path == "/api/key-reset": self._send(200, reset_key(data))
                elif path == "/api/frow-swap": self._send(200, swap_frow())
                elif path == "/api/frow-profile":
                    self._send(200, set_profile_mode(data.get("profile"), data.get("mode")))
                elif path == "/api/restore": self._send(200, restore_original())
                elif path == "/api/undo": self._send(200, undo_last())
                elif path == "/api/backup":
                    p = make_backup(); self._send(200, {"path": p})
                elif path == "/api/open-backups":
                    subprocess.Popen(["open", str(x.BACKUP)]); self._send(200, {"ok": True})
                elif path == "/api/open-privacy":
                    subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"])
                    self._send(200, {"ok": True})
                elif path == "/api/quit":
                    self._send(200, {"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else: self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(400, {"error": str(e)})

def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"X87 Configurator running at {url}")
    print("Ctrl+C to stop.")
    def sync_loop():
        last = None
        while True:
            try:
                mode = os_mode()
                if mode != last:
                    last = mode
                    if mode == "win":
                        with LOCK:
                            prefs = load_frow_prefs()
                            ensure_layout(target_layout(mode, prefs))
                        print("F-row sync: win profile applied", flush=True)
            except Exception:
                pass
            time.sleep(1.5)
    threading.Thread(target=sync_loop, daemon=True).start()
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

if __name__ == "__main__":
    main()
