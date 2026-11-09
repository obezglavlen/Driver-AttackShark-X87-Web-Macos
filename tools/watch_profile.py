#!/usr/bin/env python3
"""Read-only watcher: logs config/keymap changes while the physical Win/Mac switch is moved."""
import hashlib, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import x87ctl as x

OUT = x.PROFILES / "profile-watch"
OUT.mkdir(parents=True, exist_ok=True)
LOG = OUT / "watch.log"
FROW = [12,18,24,30,36,42,48,54,60,66,72,78]
last = None
end = time.time() + (int(sys.argv[1]) if len(sys.argv)>1 else 180)
with LOG.open("a") as log:
    log.write(f"\n--- watch start {time.strftime('%H:%M:%S')} ---\n"); log.flush()
    while time.time() < end:
        try:
            cfg = x.read_block(0x84, 0, 128)
            base = x.read_block(0x83, 0, 512)
            fn = x.read_block(0x83, 1, 512)
            h = hashlib.sha256(cfg + base + fn).hexdigest()
            if h != last:
                last = h
                ts = time.strftime("%H%M%S")
                (OUT / f"{ts}-config.bin").write_bytes(cfg)
                (OUT / f"{ts}-keys-base.bin").write_bytes(base)
                (OUT / f"{ts}-keys-fn.bin").write_bytes(fn)
                fb = [base[l*4:l*4+4].hex() for l in FROW]
                ff = [fn[l*4:l*4+4].hex() for l in FROW]
                log.write(f"{time.strftime('%H:%M:%S')} hash={h[:12]} effect={cfg[10]:02x} baseF={fb} fnF={ff}\n"); log.flush()
        except Exception as e:
            log.write(f"{time.strftime('%H:%M:%S')} error {e}\n"); log.flush()
        time.sleep(0.5)
    log.write(f"--- watch end {time.strftime('%H:%M:%S')} ---\n")
print(LOG)
