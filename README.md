# simple-server
Simple HTTP server in Python with a modern, browser-friendly UI.

## Overview
`simple-server` is a lightweight file server that provides a styled directory listing, uploads, and basic file management directly from your browser. It is designed to be easy to run for quick sharing on a local network or for personal workflows.

## Features
- Modern directory listing UI with file sizes and quick actions.
- Upload one or more files directly from the browser.
- Create folders and delete files from the UI.
- Download a directory as a zip archive.
- Password-protected sessions with a login/logout flow.
- Session cookies expire after 30 minutes by default.
- List running server instances via `list` (human readable) or `list --porcelain` (script-friendly).
- Threaded request handling for concurrent clients.
- Serve any path by passing a directory argument.

## Usage
```bash
python src/simpleserver.py [address:port] [path] [--password <value> | -pwd <value>] [--single-file <path> | -sf <path>]
```

### Examples
Run on the default interface/port:
```bash
python src/simpleserver.py
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

Serve a single file (no directory listing or access to other files):
```bash
python src/simpleserver.py 8000 --single-file /path/to/file.pdf
```

List running servers:
```bash
python src/simpleserver.py list
```

List running servers in a script-friendly format:
```bash
python src/simpleserver.py list --porcelain
```

## Notes
- When password protection is enabled, clients must log in through the `/__login__` page and can log out via `/__logout__`.
- The server writes upload files into the current working directory (or the directory you pass on the command line).
