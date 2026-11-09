#!/usr/bin/env python3
"""Small X87 wired configurator. Uses the compiled IOKit helper x87io."""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IO = ROOT / "tools" / "x87io"
BACKUP = ROOT / "backup"
PROFILES = ROOT / "profiles"
KB_INI = ROOT / "layout" / "KB.ini"
TEXT_XML = ROOT / "layout" / "text.xml"
CONFIG_BASE = 0x3A          # 20 x 2-byte effect slots
EFFECT_BYTE = 10

HID = {
    "esc":0x29,"escape":0x29,"tab":0x2B,"caps":0x39,"capslock":0x39,
    "enter":0x28,"return":0x28,"space":0x2C,"backspace":0x2A,"bksp":0x2A,
    "delete":0x4C,"del":0x4C,"insert":0x49,"ins":0x49,"home":0x4A,"end":0x4D,
    "pageup":0x4B,"pgup":0x4B,"pagedown":0x4E,"pgdn":0x4E,
    "right":0x4F,"left":0x50,"down":0x51,"up":0x52,
    "printscreen":0x46,"prtsc":0x46,"scrolllock":0x47,"pause":0x48,
    "-":0x2D,"=":0x2E,"[":0x2F,"]":0x30,"\\":0x31,";":0x33,"'":0x34,
    "`":0x35,",":0x36,".":0x37,"/":0x38,
}
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    HID[ch] = 0x04 + i
for i, ch in enumerate("1234567890"):
    HID[ch] = 0x1E + i
for i in range(1, 13):
    HID[f"f{i}"] = 0x3A + i - 1

MEDIA = {
    "media:play_pause":0xCD, "media:next":0xB5, "media:prev":0xB6, "media:stop":0xB7,
    "media:mute":0xE2, "media:vol_up":0xE9, "media:vol_down":0xEA,
    "media:bright_up":0x6F, "media:bright_down":0x70,
    "media:search":0x221, "media:calc":0x192, "media:home":0x223,
    "media:email":0x18A, "media:select":0x183,
    "media:sleep":0x32, "media:power":0x30,
}

SYSTEM = {
    "key:sleep":0x82, "key:power":0x81, "key:wake":0x83,
}

COMBOS = {
    "combo:spotlight":      (0x08, "space"),
    "combo:app_switcher":   (0x08, "tab"),
    "combo:window_switcher":(0x08, "`"),
    "combo:mission_control":(0x01, "up"),
    "combo:dictation":      (0x05, "d"),
    "combo:screenshot":     (0x0A, "3"),
    "combo:emoji":          (0x09, "space"),
    "combo:lock":           (0x09, "q"),
    "combo:alt_tab":        (0x04, "tab"),
    "combo:ctrl_space":     (0x01, "space"),
}

def _clean_name(s):
    s = s.strip().lower().replace(" ", "")
    return s

def load_layout():
    """Parse the OEM KB.ini and text.xml into a small dict."""
    txt = KB_INI.read_text(encoding="utf-8-sig", errors="replace")
    opt, keys, fn = {}, [], {}
    section = None
    pending = None
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("["):
            section = s
            continue
        if s.startswith(";;"):
            pending = ";"
            continue
        if s.startswith(";/"):
            pending = "/"
            continue
        if s.startswith(";") or s.startswith("//"):
            pending = s.lstrip(";/ ").strip()
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip()
        if section == "[OPT]":
            opt[k.lower()] = v
        elif section == "[KEY]" and re.fullmatch(r"K\d+", k):
            p = [x.strip() for x in v.split(",")]
            try:
                x1, y1, x2, y2 = int(p[0]), int(p[1]), int(p[2]), int(p[3])
                keys.append({"name": pending or k, "x": x1, "y": y1,
                             "w": x2 - x1, "h": y2 - y1, "vk": p[5],
                             "led": int(p[7])})
            except (ValueError, IndexError):
                pass
            pending = None
        elif section == "[FN1]" and re.fullmatch(r"K\d+", k):
            fn[int(k[1:])] = v
            pending = None
    # effect names from text.xml
    names = []
    try:
        xml = TEXT_XML.read_bytes().decode("utf-16", errors="replace")
        for i in range(1, 21):
            m = re.search(rf"<tc_kb_led{i}>([^<]*)</tc_kb_led{i}>", xml)
            names.append(m.group(1) if m else f"effect{i}")
    except Exception:
        names = [f"effect{i}" for i in range(1, 21)]
    effects = []
    for i in range(20):
        raw = opt.get(f"ledopt{i+1}")
        p = [x.strip() for x in raw.split(",")] if raw else ["0","0","0","0","0","0","0"]
        try:
            vals = [int(x, 0) for x in p]
        except ValueError:
            vals = [0]*7
        effects.append({"index": i, "ui": vals[0], "hw": vals[1], "light": bool(vals[2]),
                        "speed": bool(vals[3]), "direct": bool(vals[4]),
                        "random": bool(vals[5]), "color": bool(vals[6]),
                        "name": names[i]})
    return {"opt": opt, "keys": keys, "fn": fn, "effects": effects}

def run_io(args):
    p = subprocess.run([str(IO)] + args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stdout + p.stderr).strip())
    return p

def read_block(cmd, sub, size, total=1, idx=0):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
    try:
        run_io(["read", path, f"{cmd:02x}", f"{sub:02x}", str(size), str(total), str(idx)])
        data = Path(path).read_bytes()
    finally:
        os.unlink(path)
    if len(data) < 8 + size:
        raise RuntimeError(f"short read: {len(data)} bytes")
    return data[8:8+size]

def write_block(cmd, sub, size, payload, total=1, idx=0):
    if len(payload) != size:
        raise ValueError(f"payload is {len(payload)} bytes, expected {size}")
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(payload)
        path = f.name
    try:
        run_io(["write", path, f"{cmd:02x}", f"{sub:02x}", str(size), str(total), str(idx)])
    finally:
        os.unlink(path)

def save_config(payload, label):
    PROFILES.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = PROFILES / f"{ts}-{label}.bin"
    path.write_bytes(payload)
    return path

def apply_config(new, label):
    old = read_block(0x84, 0, 128)
    save_config(old, f"before-{label}")
    write_block(0x04, 0, 128, new)
    got = read_block(0x84, 0, 128)
    if got != new:
        write_block(0x04, 0, 128, old)
        raise RuntimeError("readback mismatch; restored previous config")
    return old, got

def save_keymap(payload, layer, label):
    PROFILES.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = PROFILES / f"{ts}-{label}-{'fn' if layer else 'base'}.keymap"
    path.write_bytes(payload)
    return path

def apply_keymap(new, layer, label):
    old = read_block(0x83, layer, 512)
    save_keymap(old, layer, f"before-{label}")
    write_block(0x03, layer, 512, new)
    got = read_block(0x83, layer, 512)
    if got != new:
        write_block(0x03, layer, 512, old)
        raise RuntimeError("keymap readback mismatch; restored previous keymap")
    return old, got

def find_key(layout, name):
    want = _clean_name(name)
    aliases = {
        "caps":"capslock", "esc":"escape", "del":"delete", "pgup":"pageup",
        "pgdn":"pagedown", "bksp":"backspace", "prtsc":"printscreen",
        "srclock":"scrolllock", "ctrl":"lctrl", "shift":"lshift", "alt":"lalt",
        "win":"lwin", "menu":"app", "return":"enter",
    }
    want = aliases.get(want, want)
    for k in layout["keys"]:
        if _clean_name(k["name"]) == want:
            return k
    # allow explicit LED index
    if want.startswith("led") and want[3:].isdigit():
        led = int(want[3:])
        return {"name": f"led{led}", "led": led}
    raise SystemExit(f"unknown key {name!r}; try `key list`")

def output_entry(text):
    t = _clean_name(text)
    mods = {"lctrl":0x01,"lshift":0x02,"lalt":0x04,"lwin":0x08,
            "rctrl":0x10,"rshift":0x20,"ralt":0x40,"rwin":0x80,
            "ctrl":0x01,"shift":0x02,"alt":0x04,"win":0x08}
    if t in ("none","off","disable","disabled"):
        return bytes([0,0,0,0])
    if re.fullmatch(r"(0x)?[0-9a-f]{8}", t, re.I):
        return bytes.fromhex(t[2:] if t.startswith("0x") else t)
    if t.startswith("key:"):
        usage = SYSTEM.get(t)
        if usage is None:
            raise SystemExit(f"unknown system key {text!r}")
        return bytes([0,0,0,usage])
    if t.startswith("media:"):
        key = t[6:]
        usage = int(key, 0) if key.startswith("0x") else MEDIA.get(t)
        if usage is None:
            raise SystemExit(f"unknown media output {text!r}")
        return bytes([0x02, 0x00, (usage >> 8) & 0xFF, usage & 0xFF])
    if t.startswith("combo:"):
        if t not in COMBOS:
            raise SystemExit(f"unknown combo {text!r}")
        mods_val, key = COMBOS[t]
        usage = HID.get(_clean_name(key))
        if usage is None:
            raise SystemExit(f"unknown combo key {key!r}")
        return bytes([0x00, mods_val & 0xFF, 0x00, usage & 0xFF])
    if t in mods:
        return bytes([0, mods[t], 0, 0])
    if t in HID:
        return bytes([0,0,0,HID[t]])
    raise SystemExit(f"unknown output {text!r}; use a key name, modifier, media:, combo:, 'disable', or 8 hex digits")

def cmd_key(layout, args):
    layer = 1 if args.fn else 0
    if args.action == "list":
        kb = read_block(0x83, layer, 512)
        for k in layout["keys"]:
            e = kb[k["led"]*4:k["led"]*4+4]
            print(f"{k['name']!r:12} led={k['led']:3}  {e.hex(' ')}")
        return
    if args.action == "dump":
        kb = read_block(0x83, layer, 512)
        for i in range(128):
            e = kb[i*4:i*4+4]
            if any(e):
                print(f"slot {i:3d}  {e.hex(' ')}")
        return
    if args.action == "set":
        src = find_key(layout, args.source)
        if _clean_name(src["name"]) == "fn":
            raise SystemExit("refusing to remap the Fn key")
        entry = output_entry(args.output)
        kb = read_block(0x83, layer, 512)
        new = bytearray(kb)
        new[src["led"]*4:src["led"]*4+4] = entry
        if args.dry_run:
            print(f"would set {src['name']} (led {src['led']}) -> {entry.hex(' ')}")
            return
        old, got = apply_keymap(bytes(new), layer, f"key-{src['name']}-{args.output}")
        print(f"{src['name']} -> {args.output}  {got[src['led']*4:src['led']*4+4].hex(' ')}")
        print(f"backup: {save_keymap(old, layer, 'previous')}")
        return
    if args.action == "reset":
        src = find_key(layout, args.source)
        default_path = BACKUP / ("keys-fn.bin" if layer else "keys-base.bin")
        if not default_path.exists():
            raise SystemExit(f"missing default keymap {default_path}; run `dump` first")
        default = default_path.read_bytes()[8:]
        kb = read_block(0x83, layer, 512)
        new = bytearray(kb)
        new[src["led"]*4:src["led"]*4+4] = default[src["led"]*4:src["led"]*4+4]
        if args.dry_run:
            print(f"would reset {src['name']} to {default[src['led']*4:src['led']*4+4].hex(' ')}")
            return
        old, got = apply_keymap(bytes(new), layer, f"key-reset-{src['name']}")
        print(f"{src['name']} reset to {got[src['led']*4:src['led']*4+4].hex(' ')}")
        print(f"backup: {save_keymap(old, layer, 'previous')}")
        return

def effect_for_hw(layout, hw):
    matches = [e for e in layout["effects"] if e["hw"] == hw]
    if not matches:
        return None
    return matches[0]

def current_values(layout, cfg):
    hw = cfg[EFFECT_BYTE]
    e = effect_for_hw(layout, hw)
    if e is None:
        return hw, None, None, None, None
    slot = e["index"]
    a, b = cfg[CONFIG_BASE+2*slot], cfg[CONFIG_BASE+2*slot+1]
    return hw, e, a, (b >> 4) & 0x0F, b & 0x0F

def cmd_status(layout):
    cfg = read_block(0x84, 0, 128)
    hw, e, bright, speed, color = current_values(layout, cfg)
    print(f"device   {layout['opt'].get('name','X87')}  {layout['opt'].get('vid','')}:{layout['opt'].get('pid','')}")
    if e:
        print(f"effect   {e['name']}  (ui {e['ui']}, hw {hw}, slot {e['index']})")
        print(f"bright   {bright}/9   speed {speed}/4   color {color}/7")
    else:
        print(f"effect   unknown hw {hw}")
    print(f"debounce {cfg[3]}   sleep {cfg[0x18]}   config {cfg.hex()[:32]}...")

def cmd_effect(layout, name, dry):
    cfg = read_block(0x84, 0, 128)
    hw = None
    if re.fullmatch(r"0x[0-9a-f]+|\d+", name, re.I):
        hw = int(name, 0)
    else:
        for e in layout["effects"]:
            if _clean_name(e["name"]) == _clean_name(name) or _clean_name(name) in _clean_name(e["name"]):
                hw = e["hw"]; break
    if hw is None:
        raise SystemExit(f"unknown effect {name!r}; use --list")
    new = bytearray(cfg); new[EFFECT_BYTE] = hw
    if dry:
        print(f"would set effect byte {EFFECT_BYTE}=0x{hw:02x}"); return
    old, got = apply_config(bytes(new), f"effect-{name}")
    print(f"effect set to {name} (hw {hw}), readback 0x{got[EFFECT_BYTE]:02x}")
    print(f"backup of previous config: {save_config(old, 'previous')}")

def cmd_knob(layout, field, value, dry):
    cfg = read_block(0x84, 0, 128)
    hw, e, bright, speed, color = current_values(layout, cfg)
    if not e:
        raise SystemExit(f"current effect hw {hw} not found in layout")
    slot = e["index"]; off = CONFIG_BASE + 2*slot
    new = bytearray(cfg)
    if field == "brightness":
        v = int(value, 0); new[off] = v
    elif field == "speed":
        v = int(value, 0); new[off+1] = (v << 4) | (new[off+1] & 0x0F)
    elif field == "color":
        v = int(value, 0); new[off+1] = (new[off+1] & 0xF0) | v
    else:
        raise ValueError(field)
    if dry:
        print(f"would set {field} for {e['name']} at 0x{off:02x}/{off+1:02x}"); return
    old, got = apply_config(bytes(new), f"{field}-{value}")
    print(f"{field} set for {e['name']}: {got[off]:02x} {got[off+1]:02x}")
    print(f"backup: {save_config(old, 'previous')}")

def cmd_dump():
    BACKUP.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = BACKUP / ts
    out.parent.mkdir(exist_ok=True)
    p = subprocess.run([str(ROOT/"tools"/"x87backup"), str(out)], capture_output=True, text=True)
    print(p.stdout, end="")
    if p.returncode != 0:
        print(p.stderr, file=sys.stderr); raise SystemExit(p.returncode)
    print(f"dumped to {out}")

def cmd_restore(path):
    payload = Path(path).read_bytes()
    if len(payload) == 136:
        payload = payload[8:]
    if len(payload) != 128:
        raise SystemExit(f"expected 128-byte config payload or 136-byte response, got {len(payload)}")
    old, got = apply_config(payload, "restore")
    print(f"restored {path}; readback matches" if got == payload else "restore mismatch")
    print(f"backup of previous config: {save_config(old, 'previous')}")

def cmd_effect_list(layout):
    for e in layout["effects"]:
        print(f"{e['index']:2d}  ui={e['ui']:2d} hw={e['hw']:2d}  {e['name']}")

def main():
    ap = argparse.ArgumentParser(prog="x87ctl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("dump")
    r = sub.add_parser("restore"); r.add_argument("file")
    e = sub.add_parser("effect"); e.add_argument("name", nargs="?"); e.add_argument("--list", action="store_true"); e.add_argument("--dry-run", action="store_true")
    for field in ("brightness","speed","color"):
        p = sub.add_parser(field); p.add_argument("value"); p.add_argument("--dry-run", action="store_true")
    k = sub.add_parser("key")
    k.add_argument("action", choices=["list","dump","set","reset"])
    k.add_argument("source", nargs="?")
    k.add_argument("output", nargs="?")
    k.add_argument("--fn", action="store_true")
    k.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    layout = load_layout()
    if args.cmd == "status": cmd_status(layout)
    elif args.cmd == "dump": cmd_dump()
    elif args.cmd == "restore": cmd_restore(args.file)
    elif args.cmd == "effect":
        if args.list or not args.name: cmd_effect_list(layout)
        else: cmd_effect(layout, args.name, args.dry_run)
    elif args.cmd in ("brightness","speed","color"):
        cmd_knob(layout, args.cmd, args.value, args.dry_run)
    elif args.cmd == "key":
        cmd_key(layout, args)

if __name__ == "__main__":
    main()
