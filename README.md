# simple-server
Simple HTTP server in Python with a modern, browser-friendly UI.

## Overview
`simple-server` is a lightweight file server that provides a styled directory listing, uploads, and basic file management directly from your browser. It is designed to be easy to run for quick sharing on a local network or for personal workflows.

## Features
- Modern directory listing UI with file sizes and quick actions.
- Drag and drop one or more files with per-file progress, status, and cancellation controls.
- Create folders and delete files from the UI.
- Download a directory as a zip archive.
- Password-protected sessions with a login/logout flow.
- Expiring, read-only share links scoped to one file or directory.
- Session cookies expire after 30 minutes by default.
- List running server instances via `list` (human readable) or `list --porcelain` (script-friendly).
- Threaded request handling for concurrent clients.
- HTTP byte ranges and ETag/Last-Modified cache validation for seeking and resumable downloads.
- JSON health endpoint at `/healthz` with status, uptime, and version details.
- Device connection page at `/__connect__` with available LAN URLs and offline QR codes.
- Optional local-only binding with `--local`; external access remains the default.
- Serve any path by passing a directory argument.

## Usage
```bash
python src/simpleserver.py [address:port] [path] [--local] [--password <value> | -pwd <value>]
```

### Examples
Run on the default interface/port:
```bash
python src/simpleserver.py
```

By default, the server binds to `0.0.0.0` so other devices can connect. Restrict it to the local machine with:
```bash
python src/simpleserver.py --local
```

At startup, the server prints its available connection URLs and a link to the device connection page. Open `/__connect__` from the file browser to copy an address or scan its QR code. QR codes are generated locally and do not send connection details to a third party.

Use a custom local-only port:
```bash
python src/simpleserver.py 9000 --local
```

Bind to a specific interface/port:
```bash
python src/simpleserver.py 127.0.0.1:9000
```

Serve a specific directory:
```bash
python src/simpleserver.py 8000 /path/to/share
```

Enable password protection:
```bash
python src/simpleserver.py 8000 /path/to/share --password "super-secret"
```

List running servers:
```bash
python src/simpleserver.py list
```

List running servers in a script-friendly format:
```bash
python src/simpleserver.py list --porcelain
```

Check server health:
```bash
curl http://127.0.0.1:8000/healthz
```

## Notes
- When password protection is enabled, clients must log in through the `/__login__` page and can log out via `/__logout__`.
- The `/healthz` endpoint remains available without authentication for health probes.
- Share links can expire after 15 minutes, 1 hour, or 24 hours and are invalidated when the server stops.
- The server writes upload files into the current working directory (or the directory you pass on the command line).
- Upload, create, and delete operations accept single names only and reject targets that resolve outside the served directory.
