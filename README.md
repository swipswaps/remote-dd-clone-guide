# Remote dd Clone Guide

Site: https://swipswaps.github.io/remote-dd-clone-guide/

Clone a remote SATA disk to a USB drive (or a remote network destination) over SSH, with live progress.

- **Manual** — download the helper script or git clone, run copy-paste commands. No Docker.
- **Interactive** — `docker compose up -d` starts a loopback backend; the page probes it and unlocks a panel with dry-run, compression, bandwidth limit, tolerate-read-errors, resume, verify, and optional remote destination.

## Manual

    git clone https://github.com/swipswaps/remote-dd-clone-guide.git
    cd remote-dd-clone-guide
    bash scripts/clone-remote-dd.sh <remote-host> <source-dev> <local-target-dev> [user]

Or download just the script:

    curl -O https://swipswaps.github.io/remote-dd-clone-guide/scripts/clone-remote-dd.sh

## Interactive

    git clone https://github.com/swipswaps/remote-dd-clone-guide.git
    cd remote-dd-clone-guide
    cp .env.example .env
    $EDITOR .env       # set BACKEND_TOKEN and ALLOWED_LOCAL_DEVICES
    docker compose up -d

Open the site. The status badge turns green. Paste the token, fill in the form, click Dry run, then Start clone.

## Safety

dd writes raw bytes. The backend adds defence in depth:

1. Device allowlist (ALLOWED_LOCAL_DEVICES); empty means refuse all local writes.
2. Explicit confirm — the client must send the destination path verbatim.
3. Dry run — POST /dryrun returns the exact command without executing.
4. Loopback bind — 127.0.0.1:8080; not reachable from the network.
5. Input validation — host, user, and /dev/* paths are regex-gated.
6. Unmount guard — the manual script refuses if the target is mounted.
7. Abort kills the process group — SIGTERM, then SIGKILL after 1 s.

The Docker container is privileged — it must write to host block devices. Everything above is defence in depth, not a substitute for pointing of= at the right device.
