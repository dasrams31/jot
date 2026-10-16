#!/usr/bin/env python3
"""Jot - anonymous pastebin over Tor.

Python stdlib only. SQLite (WAL). No accounts.

Features: optional expiry, burn-after-reading, raw view.
"""

import html
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "jot.db")
PORT = 18095

ID_LEN = 8
BODY_MAX = 200_000  # ~200KB
EXPIRIES = {"1h": 3600, "1d": 86400, "1w": 604800, "never": 0}

_db_lock = threading.Lock()


def now():
    return int(time.time())


def db():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=10000")
    return c


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = db()
    c.execute("""
    CREATE TABLE IF NOT EXISTS pastes (
        id TEXT PRIMARY KEY,
        body TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL DEFAULT 0,
        burn INTEGER NOT NULL DEFAULT 0,
        views INTEGER NOT NULL DEFAULT 0
    )""")
    c.commit()
    c.close()


def cleanup():
    with _db_lock:
        c = db()
        try:
            c.execute("DELETE FROM pastes WHERE expires_at > 0 AND expires_at < ?",
                      (now(),))
            c.commit()
        finally:
            c.close()


def esc(s):
    return html.escape(s or "", quote=True)


def new_id(c):
    for _ in range(20):
        pid = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789")
                      for _ in range(ID_LEN))
        if not c.execute("SELECT 1 FROM pastes WHERE id=?", (pid,)).fetchone():
            return pid
    return secrets.token_hex(4)


# ---------------------------------------------------------------- html ---

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d0d0e;--panel:#151517;--panel2:#1c1c1f;--border:#232326;--border2:#323237;
--text:#f4f4f5;--muted:#9c9ca6;--faint:#63636c;--acc:#8ab4ff;--warn:#f59e0b}
html{-webkit-text-size-adjust:100%;overflow-x:hidden}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,
"Segoe UI",Roboto,Helvetica,Arial,sans-serif;line-height:1.5;font-size:15px;
-webkit-font-smoothing:antialiased;overflow-x:hidden;width:100%;max-width:100vw}
a{color:inherit;text-decoration:none}
.wrap{max-width:720px;margin:0 auto;min-height:100vh;width:100%;display:flex;
flex-direction:column;border-left:1px solid var(--border);border-right:1px solid var(--border)}
.topbar{position:sticky;top:0;z-index:20;background:rgba(13,13,14,.92);
backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
border-bottom:1px solid var(--border)}
.topbar-in{max-width:720px;margin:0 auto;display:flex;align-items:center;
justify-content:space-between;padding:10px 16px;gap:8px;min-height:60px}
.wordmark{font-size:20px;font-weight:800;letter-spacing:-.03em}
.wordmark .dot{color:var(--faint)}
.newbtn{color:var(--muted);font-size:13.5px;font-weight:600;padding:10px 16px;
border:1px solid var(--border2);border-radius:999px;min-height:44px;
display:flex;align-items:center}
.newbtn:hover{color:var(--text);border-color:var(--muted)}
.main{flex:1;padding:24px 18px}
.main h1{font-size:22px;font-weight:800;letter-spacing:-.02em;margin-bottom:6px}
.sub{color:var(--muted);font-size:14px;margin-bottom:20px}
textarea{width:100%;background:var(--panel);border:1px solid var(--border2);
border-radius:14px;padding:16px;color:var(--text);
font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
font-size:14px;line-height:1.6;min-height:280px;resize:vertical}
textarea:focus{outline:none;border-color:var(--muted)}
.opts{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0;align-items:center}
.opt{display:flex;align-items:center;gap:8px;font-size:14px;color:var(--muted)}
.opt select{background:var(--panel);border:1px solid var(--border2);color:var(--text);
border-radius:10px;padding:10px 12px;font-size:14px;font-family:inherit;min-height:44px}
.opt input[type=checkbox]{width:20px;height:20px;accent-color:var(--acc)}
button.btn{background:var(--text);color:#0d0d0e;border:none;border-radius:12px;
padding:14px 28px;font-weight:700;font-size:15px;cursor:pointer;min-height:52px;
font-family:inherit;width:100%}
button.btn:active{transform:scale(.98)}
button.btn:disabled{opacity:.4}
.meta{display:flex;gap:14px;flex-wrap:wrap;color:var(--faint);font-size:13px;
margin-bottom:14px;align-items:center}
.meta .burn{color:var(--warn);font-weight:700}
pre.paste{background:var(--panel);border:1px solid var(--border);border-radius:14px;
padding:18px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
font-size:13.5px;line-height:1.65;white-space:pre-wrap;word-break:break-word;
overflow-wrap:break-word;max-height:70vh;overflow-y:auto}
.actions{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
.actions a,.actions button{flex:1;min-height:48px;display:flex;align-items:center;
justify-content:center;background:var(--panel);border:1px solid var(--border2);
border-radius:12px;color:var(--text);font-size:14px;font-weight:600;cursor:pointer;
font-family:inherit;padding:12px}
.actions a:hover,.actions button:hover{border-color:var(--muted)}
.sharebox{background:var(--panel);border:1px solid var(--border);border-radius:14px;
padding:16px;margin-bottom:16px}
.sharebox label{display:block;font-size:12.5px;font-weight:600;color:var(--muted);
margin-bottom:8px}
.sharebox .linkrow{display:flex;gap:8px}
.sharebox input{flex:1;background:var(--bg);border:1px solid var(--border2);
border-radius:10px;padding:11px 14px;color:var(--text);
font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;min-width:0}
.copybtn{flex:none;background:var(--panel2)!important;border:1px solid var(--border2)!important;
padding:11px 18px!important;min-height:44px}
.empty{padding:60px 20px;text-align:center;color:var(--faint)}
.empty h2{font-size:18px;color:var(--muted);margin-bottom:8px}
.footer{padding:20px 16px 28px;text-align:center;color:var(--faint);font-size:12px}
.err{background:rgba(244,63,94,.08);border:1px solid rgba(244,63,94,.35);color:#fda4b4;
padding:12px 16px;border-radius:12px;margin-bottom:16px;font-size:14px}
@media(max-width:660px){
.wrap{border-left:none;border-right:none}
.main{padding:18px 14px}
textarea{min-height:220px;font-size:13.5px}
.topbar-in{padding:8px 12px;min-height:56px}
}
"""


def page(title, body, home=True):
    top = ("<div class='topbar'><div class='topbar-in'>"
           "<a class='wordmark' href='/'>Jot<span class='dot'>.</span></a>"
           + ("" if home else "<a class='newbtn' href='/'>+ New paste</a>")
           + "</div></div>")
    return ("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1,"
            "viewport-fit=cover'>"
            "<title>%s - Jot</title><style>%s</style></head>"
            "<body><div class='wrap'>%s<div class='main'>%s</div>"
            "<div class='footer'>Jot &mdash; anonymous pastebin over Tor<br>"
            "No accounts. Pastes expire, or burn after reading.<br><span style='font-size:11px;opacity:.75'>Donate: <code style='font-size:10px'>0x62A098898048c79FF14De07F3BE9310398E5eCF8</code></span></div>"
            "</div>"
            "<script>"
            "function copyLink(id){var i=document.getElementById(id);"
            "i.select();i.setSelectionRange(0,99999);"
            "try{navigator.clipboard.writeText(i.value);}catch(e){"
            "document.execCommand('copy');}"
            "var b=document.getElementById(id+'-btn');"
            "var t=b.textContent;b.textContent='Copied';"
            "setTimeout(function(){b.textContent=t;},2000);}"
            "</script>"
            "</body></html>") % (esc(title), CSS, top, body)


def home_page(err=""):
    ehtml = "<div class='err'>%s</div>" % esc(err) if err else ""
    return page("New paste", (
        "<h1>Paste something.</h1>"
        "<p class='sub'>Anonymous. No account. Set an expiry, or burn it after one read.</p>"
        "%s<form method='post' action='/'>"
        "<textarea name='body' maxlength='200000' placeholder='Paste text, code, notes...' "
        "required></textarea>"
        "<div class='opts'>"
        "<label class='opt'>Expires: <select name='expiry'>"
        "<option value='1d'>1 day</option><option value='1h'>1 hour</option>"
        "<option value='1w'>1 week</option><option value='never'>Never</option>"
        "</select></label>"
        "<label class='opt'><input type='checkbox' name='burn' value='1'> "
        "Burn after reading</label>"
        "</div>"
        "<button class='btn' type='submit'>Create paste</button>"
        "</form>") % ehtml)


def view_page(pid, paste, base_url):
    burn_note = ("<span class='burn'>Burns after reading &mdash; "
                 "this is the only view.</span>" if paste["burn"] else "")
    exp = "Never" if not paste["expires_at"] else time.strftime(
        "%Y-%m-%d %H:%M UTC", time.gmtime(paste["expires_at"]))
    url = base_url + "/" + pid
    return page("Paste " + pid, (
        "<div class='sharebox'><label>Share this link</label>"
        "<div class='linkrow'>"
        "<input id='sharelink' readonly value='%s' onclick='this.select()'>"
        "<button class='copybtn' id='sharelink-btn' "
        "onclick=\"copyLink('sharelink')\">Copy</button>"
        "</div></div>"
        "<div class='meta'><span>%d views</span><span>Expires: %s</span>%s</div>"
        "<pre class='paste'>%s</pre>"
        "<div class='actions'>"
        "<a href='/%s/raw'>Raw</a>"
        "<a href='/' >New paste</a>"
        "</div>") % (esc(url), paste["views"], exp, burn_note,
                     esc(paste["body"]), esc(pid)), home=False)


# ---------------------------------------------------------------- server ---

class Handler(BaseHTTPRequestHandler):
    server_version = "Jot/1.0"
    protocol_version = "HTTP/1.1"

    def send_html(self, code, html_body):
        data = html_body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_text(self, code, text):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def redirect(self, loc):
        self.send_response(303)
        self.send_header("Location", loc)
        self.end_headers()

    def read_form(self):
        try:
            ln = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        if ln <= 0 or ln > BODY_MAX + 1024:
            return None
        raw = self.rfile.read(ln)
        try:
            return dict(urllib.parse.parse_qsl(raw.decode("utf-8", "replace")))
        except Exception:
            return None

    def base_url(self):
        host = self.headers.get("Host", "").split(",")[0].strip()
        # only trust onion hosts to avoid header injection in share links
        if re.fullmatch(r"[a-z2-7]+\.onion(:\d+)?", host):
            return "http://" + host
        return ""

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, is_post):
        path = urllib.parse.urlparse(self.path).path
        try:
            self.c = db()
        except Exception:
            self.send_response(500)
            self.end_headers()
            return
        try:
            if is_post and path == "/":
                self.handle_create()
            elif not is_post and path == "/":
                self.send_html(200, home_page())
            elif not is_post:
                m = re.fullmatch(r"/([A-Za-z0-9]{4,16})(/raw)?", path)
                if m:
                    self.handle_view(m.group(1).lower(), raw=bool(m.group(2)))
                else:
                    self.send_html(404, page("Not found",
                                             "<div class='empty'><h2>Not found</h2>"
                                             "<p><a href='/'>New paste</a></p></div>"))
            else:
                self.send_html(404, page("Not found", "<div class='empty'>"
                                                      "Not found.</div>"))
        except BrokenPipeError:
            pass
        except Exception:
            try:
                self.send_html(500, page("Error", "<div class='empty'>"
                                                  "Something went wrong.</div>"))
            except BrokenPipeError:
                pass
        finally:
            self.c.close()

    def handle_create(self):
        form = self.read_form()
        if form is None:
            self.send_html(400, home_page("Paste too large or bad request."))
            return
        body = (form.get("body") or "").strip()
        if not body:
            self.send_html(400, home_page("Paste is empty."))
            return
        if len(body) > BODY_MAX:
            self.send_html(400, home_page("Paste too large (max ~200KB)."))
            return
        expiry = EXPIRIES.get(form.get("expiry", "1d"), 86400)
        burn = 1 if form.get("burn") == "1" else 0
        with _db_lock:
            c = db()
            try:
                pid = new_id(c)
                exp_at = now() + expiry if expiry else 0
                c.execute(
                    "INSERT INTO pastes(id, body, created_at, expires_at, burn)"
                    " VALUES (?,?,?,?,?)",
                    (pid, body, now(), exp_at, burn))
                c.commit()
            finally:
                c.close()
        self.redirect("/" + pid)

    def handle_view(self, pid, raw=False):
        with _db_lock:
            c = db()
            try:
                p = c.execute("SELECT * FROM pastes WHERE id=?", (pid,)).fetchone()
                if not p:
                    self.send_html(404, page("Not found",
                                             "<div class='empty'><h2>Paste not found</h2>"
                                             "<p>It may have expired or burned.</p>"
                                             "<p><a href='/'>New paste</a></p></div>"))
                    return
                if p["expires_at"] and p["expires_at"] < now():
                    c.execute("DELETE FROM pastes WHERE id=?", (pid,))
                    c.commit()
                    self.send_html(404, page("Expired",
                                             "<div class='empty'><h2>Paste expired</h2>"
                                             "<p><a href='/'>New paste</a></p></div>"))
                    return
                body, burn = p["body"], p["burn"]
                views = p["views"] + 1
                if burn:
                    c.execute("DELETE FROM pastes WHERE id=?", (pid,))
                else:
                    c.execute("UPDATE pastes SET views=? WHERE id=?", (views, pid))
                c.commit()
            finally:
                c.close()
        if raw:
            self.send_text(200, body)
            return
        self.send_html(200, view_page(pid, dict(p, views=views), self.base_url()))


def cleanup_loop():
    while True:
        time.sleep(600)
        try:
            cleanup()
        except Exception:
            pass


def main():
    init_db()
    cleanup()
    threading.Thread(target=cleanup_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Jot on 127.0.0.1:%d" % PORT, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
