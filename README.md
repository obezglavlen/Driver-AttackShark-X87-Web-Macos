# Attack Shark X87 — macOS wired configurator

The vendor installer is Windows-only. This is a small native macOS tool that talks to the
keyboard's HID config interface directly (wired USB-C only).

## Device

- Wired: `258a:010c`
- HID interface: usage page `0xFF00`, usage `0x0001`
- Feature report `6`, 520 bytes
- Model/PSD: `03 00 00 00 01 a7`
- Firmware family: SinoWealth `CDevG5KB` (Fw 24)

No firmware flashing is implemented on purpose.

## Function row / Win-Mac profiles

The keyboard has a physical Win/Mac switch. The switch changes config byte
`0x1B` (`0x00` = Windows, `0x02` = macOS).

**Windows mode** uses the keymap block exposed by command `0x83`. Key remaps and
F-row settings work there. The **Function row** card controls it:

- **F keys primary** — F1–F12 without Fn, media/shortcuts with Fn.
- **Media primary** — media/shortcuts without Fn, F1–F12 with Fn.

**Mac mode is different.** It uses an internal firmware keymap, not the `0x83`
block. Writing the keymap in Mac mode has no effect (verified with a CapsLock
remap). The Mac F row is fixed by firmware: media normal, F keys with Fn. The
GUI shows a warning and disables the Mac profile controls.

Practical workaround: use the physical switch in **Win** position on macOS if you
want F keys primary (media with Fn). The keyboard then sends F keys normally; the
Alt/Win modifier positions differ from Mac mode, which macOS can swap under
System Settings → Keyboard → Modifier Keys if needed.

## Media and Mac-shortcut outputs

The key remap output list now includes:

- **Media** — Play/Pause, Next/Previous, Stop, Mute, Volume +/-, Brightness +/-,
  Search, Calculator, Browser Home, Email, Media Select.
- **Mac shortcuts** — Spotlight (Cmd+Space), App Switcher (Cmd+Tab),
  Window Switcher (Cmd+`), Mission Control (Ctrl+Up), Screenshot (Cmd+Shift+3),
  Emoji (Ctrl+Cmd+Space), Lock Screen (Ctrl+Cmd+Q).

These are written into the Fn layer and work in **Windows mode**. In Mac mode the
firmware keymap is fixed, so the GUI disables those changes.

Dictation and Sleep do not have standard HID usages that macOS honors from a
third-party keyboard. They require a custom macOS Dictation shortcut or a
third-party remapper; they are therefore not offered in the GUI.

## Troubleshooting: Input Monitoring

The reliable launcher is **`start-gui.command`**. Double-click it in Finder; it
opens Terminal and starts the server. Allow **Terminal** in
System Settings → Privacy & Security → Input Monitoring. That path works because
Terminal already has the HID permission.

The included `X87 Configurator.app` is optional. On macOS its HID access is
attributed to **Python.app**, not to the app bundle, so granting
`X87 Configurator` and `x87io` alone may still produce
`kIOReturnNotPermitted`. If that happens, use `start-gui.command` instead.

If you really want to use the `.app`, add this to Input Monitoring as well:

```text
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app
```

The terminal fallback is always:

```sh
cd ~/x87
python3 tools/x87gui.py
```

## Backup

Original read-only dump:

```
backup/config.bin      128-byte LED/config block
backup/colors.bin      512-byte effect colour table
backup/perkey.bin      512-byte per-key area (currently mostly empty)
backup/keys-base.bin   512-byte base keymap
backup/keys-fn.bin     512-byte Fn keymap
backup/macros.bin      4096-byte macro area (empty)
backup/identity.bin    identity response
backup/manifest.json   sizes + SHA-256
```

Every write made by `x87ctl.py` also saves the previous block to `profiles/`.

## Running the GUI (recommended)

Double-click **`start-gui.command`** in Finder. It opens Terminal, starts the
local-only web UI, and opens your browser. The URL is also written to
`/tmp/x87gui.log`. The **Quit** button in the UI stops it, or close the Terminal
window.

`X87 Configurator.app` is included as an optional launcher, but the `.command`
path is more reliable on macOS because the app's Python process has the extra
Input Monitoring permission ambiguity described below.

## CLI usage

```sh
cd ~/x87

./tools/x87ctl.py status
./tools/x87ctl.py effect --list
./tools/x87ctl.py effect fixed_on
./tools/x87ctl.py brightness 9
./tools/x87ctl.py speed 4
./tools/x87ctl.py color 7
./tools/x87ctl.py key list
./tools/x87ctl.py key set caps a
./tools/x87ctl.py key reset caps
./tools/x87ctl.py dump
./tools/x87ctl.py restore backup/config.bin
```

`effect`, `brightness`, `speed`, `color`, and `key` write a full block, read it back,
and restore the previous block automatically if the readback does not match.

## Safety

- Factory reset on the keyboard: hold `Fn + Esc` for about 3 seconds.
- All reads/writes are wired-only.
- `profiles/` keeps the previous state before every change.
- If anything looks wrong: `./tools/x87ctl.py restore backup/config.bin` (config) and
  `./tools/x87ctl.py key reset <key>` (keymap).

## Repository layout

```
tools/x87io          compiled IOKit feature-report helper (macOS arm64)
tools/x87io.c        its source
tools/x87backup      compiled read-only backup dumper
tools/x87backup.c    its source
tools/x87ctl.py      command-line configurator
tools/x87gui.py      local web UI server
tools/watch_profile.py  read-only Win/Mac switch watcher (diagnostic)
gui/                 web UI, including keyimg.png keyboard render
layout/KB.ini        OEM key layout metadata used by the configurator
layout/text.xml      OEM effect names
backup/              original read-only keyboard backup
X87 Configurator.app optional launcher (may be blocked by Python TCC)
start-gui.command    recommended launcher (Terminal)
```

The compiled helpers are for macOS arm64. Rebuild them with:

```sh
clang -O2 -o tools/x87io tools/x87io.c -framework IOKit -framework CoreFoundation
clang -O2 -o tools/x87backup tools/x87backup.c -framework IOKit -framework CoreFoundation
```

## Assets and licensing

The OEM Windows installer and its binary are **not** included. `gui/keyimg.png`,
`X87 Configurator.app/Contents/Resources/appicon.icns`, and the layout metadata in
`layout/` are extracted from the OEM installer and are included only so the tool
can talk to the same hardware. They are not covered by any project license;
replace them before redistributing if that matters for your use.
