# Remote dd Clone Guide

Site: https://swipswaps.github.io/remote-dd-clone-guide/

Interactive guide to cloning a **running SATA disk** to a **USB‑attached SATA disk** over SSH, with live progress.

## What it covers

- `dd` piped through SSH with `status=progress`
- `pv` for a real progress bar, throughput, and ETA
- `dd`'s own `status=progress` when `pv` is not available
- `kill -USR1` to request an on‑demand progress report
- Compression (`pigz` / `lz4`) to reduce SSH bandwidth
- Safety checks before writing to the target device

## Quick start

```bash
# On the machine that has the USB target attached:
lsblk -o NAME,SIZE,TYPE,MODEL,TRAN
# Identify the USB disk, then run:
ssh user@source-host "sudo dd if=/dev/sda bs=4M status=progress" | sudo dd of=/dev/sdb bs=4M status=progress conv=fsync
```

Open the site for the full step‑by‑step walkthrough.
