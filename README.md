# Jot

Anonymous pastebin over Tor. No accounts.

- Paste text, get a shareable link
- Optional expiry: 1 hour, 1 day, 1 week, never
- Burn after reading: link works exactly once
- Raw text view

## Stack

Python stdlib only. SQLite (WAL). ThreadingHTTPServer.

## Run

```
python3 app.py  # 127.0.0.1:18095
```

Deploy as a Tor hidden service pointing at port 18095.
