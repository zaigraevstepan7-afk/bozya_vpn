#!/usr/bin/env python3
import base64
import json
import os
import re
import shutil
import socket
import statistics
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote, urlparse

import requests
import yaml

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES = [
    "https://sub.aska.lol/Ux7lmK0xkIl2",
    "https://connliberty.com/connection/subs/dcf2b960-d490-40dd-a18b-1718550f939e",
    "https://akonit.tech/sub/f9afd2d3-3858-403e-bbc9-9a720420c188",
    "https://sub.vlessfo.ru/vlessforu/working_configs.txt",
]

# Always prepended to the subscription. Not probed and not counted toward TOP_N.
PINNED_AWG_CONFIGS = [
    ("LTEdWARPv2_99.conf", "DE"),
    ("LTEfWARPv2_40.conf", "FI"),
    ("LTEpWARPv2_60.conf", "PL"),
]

OUT_DIR = os.path.join(BASE_DIR, "output")
TOP_N = 30
MAX_TEST_PER_SOURCE = 40
MAX_PER_SOURCE_FINAL = 15
MIN_SUCCESS = 0.8
ATTEMPTS = 5
CONFIRM_ATTEMPTS = 5
TIMEOUT = 2.5
MAX_MEDIAN_MS = 180.0
MAX_JITTER_MS = 35.0
MAX_WORST_MS = 300.0
PROBE_WORKERS = 16
REPROBE_TOP = 60

SCHEMES = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://")
GAME_GEO = ["NL", "DE", "PL", "CZ", "RO", "FI", "SE", "SG", "JP", "US"]

FULL_NAMES = {
    "RU": "Россия", "NL": "Нидерланды", "DE": "Германия", "FR": "Франция",
    "PL": "Польша", "CZ": "Чехия", "RO": "Румыния", "FI": "Финляндия",
    "SE": "Швеция", "SG": "Сингапур", "JP": "Япония", "US": "США",
    "GB": "Великобритания", "TR": "Турция", "KR": "Южная Корея",
    "HK": "Гонконг", "TW": "Тайвань", "CA": "Канада", "CH": "Швейцария",
    "IT": "Италия", "ES": "Испания", "EE": "Эстония", "LT": "Литва",
    "LV": "Латвия", "UA": "Украина", "MD": "Молдова", "BG": "Болгария",
    "EU": "Европа", "AT": "Австрия", "BE": "Бельгия", "DK": "Дания",
    "NO": "Норвегия", "IE": "Ирландия", "PT": "Португалия", "GR": "Греция",
    "HU": "Венгрия", "SK": "Словакия", "HR": "Хорватия", "RS": "Сербия",
    "GE": "Грузия", "AM": "Армения", "AZ": "Азербайджан", "KZ": "Казахстан",
    "UZ": "Узбекистан", "IN": "Индия", "ID": "Индонезия", "MY": "Малайзия",
    "TH": "Таиланд", "VN": "Вьетнам", "PH": "Филиппины", "AE": "ОАЭ",
    "IL": "Израиль", "BR": "Бразилия", "MX": "Мексика", "AR": "Аргентина",
    "CL": "Чили", "ZA": "ЮАР", "AU": "Австралия", "NZ": "Новая Зеландия",
    "SA": "Саудовская Аравия", "EG": "Египет", "CY": "Кипр", "IS": "Исландия",
    "LU": "Люксембург", "MT": "Мальта", "MO": "Макао", "IR": "Иран",
}

_COUNTRY_CACHE = {}
_COUNTRY_LOCK = threading.Lock()


def country_to_flag(code):
    if not code or len(code) != 2:
        return ""
    return chr(127397 + ord(code[0])) + chr(127397 + ord(code[1]))


def country_display(country):
    if not country:
        return ""
    flag = country_to_flag(country)
    full = FULL_NAMES.get(country)
    if full:
        return flag + " " + full
    return flag + " " + country

RU_HINTS = [
    r"\bru\b",
    r"\brus\b",
    r"\brussia\b",
    r"\bроссия\b",
    r"\bрф\b",
    r"\bмосква\b",
    r"\bmoscow\b",
    r"\bmow\b",
    r"\bspb\b",
]

COUNTRY_HINTS = [
    ("RU", ["russia", "россия", "рф", "москва", "moscow", "mow", "spb"]),
    ("NL", ["netherlands", "нидерланды", "amsterdam", "ams"]),
    ("DE", ["germany", "германия", "frankfurt", "berlin", "fra"]),
    ("FR", ["france", "франция", "paris", "cdg"]),
    ("PL", ["poland", "польша", "warsaw", "waw"]),
    ("CZ", ["czech", "чехия", "prague", "prg"]),
    ("RO", ["romania", "румыния", "bucharest", "buh"]),
    ("FI", ["finland", "финляндия", "helsinki", "hel"]),
    ("SE", ["sweden", "швеция", "stockholm", "sto"]),
    ("SG", ["singapore", "сингапур", "sgp"]),
    ("JP", ["japan", "япония", "tokyo", "tyo", "osaka"]),
    ("US", ["united states", "usa", "сша", "los angeles", "new york", "seattle", "dallas", "miami", "lax", "jfk", "nyc"]),
    ("GB", ["united kingdom", "great britain", "великобритания", "london", "lon"]),
    ("TR", ["turkey", "турция", "istanbul", "ist"]),
    ("KR", ["south korea", "korea", "корея", "seoul", "icn"]),
    ("HK", ["hong kong", "гонконг", "hongkong", "hkg"]),
    ("TW", ["taiwan", "тайвань", "taipei", "tpe"]),
    ("CA", ["canada", "канада", "toronto", "montreal"]),
    ("CH", ["switzerland", "швейцария", "zurich", "zrh"]),
    ("IT", ["italy", "италия", "milan", "rome"]),
    ("ES", ["spain", "испания", "madrid", "barcelona"]),
    ("EE", ["estonia", "эстония", "tallinn"]),
    ("LT", ["lithuania", "литва", "vilnius"]),
    ("LV", ["latvia", "латвия", "riga"]),
    ("UA", ["ukraine", "украина", "kyiv", "kiev"]),
    ("MD", ["moldova", "молдова", "chisinau"]),
    ("BG", ["bulgaria", "болгария", "sofia"]),
]


def flag_to_country(text):
    letters = []
    for ch in text:
        cp = ord(ch)
        if 0x1F1E6 <= cp <= 0x1F1FF:
            letters.append(chr(65 + cp - 0x1F1E6))
            if len(letters) == 2:
                return "".join(letters)
    return None


def is_ru(text):
    low = text.lower()
    for hint in RU_HINTS:
        if re.search(hint, low):
            return True
    return flag_to_country(text) == "RU"


def detect_country_from_name(text):
    flag = flag_to_country(text)
    if flag:
        return flag
    low = text.lower()
    for code, hints in COUNTRY_HINTS:
        for hint in hints:
            if re.search(r"\b" + re.escape(hint) + r"\b", low):
                return code
    return None


def try_b64_line(line):
    compact = re.sub(r"\s+", "", line)
    if len(compact) < 20:
        return None
    variants = [compact, compact + "=" * (-len(compact) % 4)]
    for variant in variants:
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                raw = decoder(variant, validate=True)
                text = raw.decode("utf-8")
                if text.startswith(SCHEMES) or "\n" in text:
                    return text
            except Exception:
                continue
    return None


def extract_nodes(text):
    head = text[:500].lower().lstrip()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        print("WARN: source returned HTML page, no nodes found")
        return []
    found = []
    seen = set()

    def add(piece):
        piece = piece.strip()
        if piece.startswith(SCHEMES) and piece not in seen:
            seen.add(piece)
            found.append(piece)

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(SCHEMES):
            add(line)
            continue
        decoded = try_b64_line(line)
        if decoded:
            for piece in decoded.splitlines():
                add(piece)
    decoded = try_b64_line(text)
    if decoded:
        for piece in decoded.splitlines():
            add(piece)
    return found


def parse_generic(uri, scheme):
    try:
        body = uri.split("://", 1)[-1].split("#")[0].split("?")[0]
        if "@" not in body:
            return None
        parsed = urlparse(uri)
        host = parsed.hostname or ""
        port = parsed.port or 443
        name = unquote(parsed.fragment or "")
        if not host:
            return None
        return {"scheme": scheme, "host": host, "port": port, "name": name, "raw": uri}
    except Exception:
        return None


def parse_vmess(uri):
    try:
        payload = uri[len("vmess://"):]
        if "#" in payload:
            payload = payload.split("#")[0]
        try:
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        except Exception:
            payload = unquote(payload)
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw.decode("utf-8"))
        host = data.get("add") or data.get("host") or ""
        port = int(data.get("port") or 0)
        name = data.get("ps") or ""
        if not host or not port:
            return None
        return {"scheme": "vmess", "host": host, "port": port, "name": name, "data": data, "raw": uri}
    except Exception:
        return None


def parse_ss(uri):
    try:
        parsed = urlparse(uri)
        host = parsed.hostname
        port = parsed.port
        name = unquote(parsed.fragment or "")
        if host and port:
            return {"scheme": "ss", "host": host, "port": port, "name": name, "raw": uri}
        payload = uri[len("ss://"):]
        if "#" in payload:
            payload, frag = payload.split("#", 1)
            name = unquote(frag)
        payload = unquote(payload)
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8")
        if "@" not in raw or ":" not in raw.rsplit("@", 1)[-1]:
            return None
        hostport = raw.rsplit("@", 1)[-1]
        host, port_s = hostport.rsplit(":", 1)
        return {"scheme": "ss", "host": host, "port": int(port_s), "name": name, "raw": uri}
    except Exception:
        return None


def parse_node(line):
    if line.startswith("vmess://"):
        return parse_vmess(line)
    if line.startswith("vless://"):
        return parse_generic(line, "vless")
    if line.startswith("trojan://"):
        return parse_generic(line, "trojan")
    if line.startswith("ss://"):
        return parse_ss(line)
    if line.startswith("hysteria2://") or line.startswith("hy2://"):
        return parse_generic(line, "hysteria2")
    return None


def rename_node(node, new_name):
    encoded = quote(new_name, safe="")
    if node["scheme"] == "vmess":
        data = dict(node["data"])
        data["ps"] = new_name
        payload = base64.urlsafe_b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")
        return "vmess://" + payload
    head = node["raw"].split("#")[0]
    return head + "#" + encoded


def parse_wg_conf(text):
    interface = {}
    peer = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if section == "interface":
            interface[key] = value
        elif section == "peer":
            peer[key] = value
    return interface, peer


def split_endpoint(endpoint):
    endpoint = (endpoint or "").strip()
    if not endpoint:
        return None, None
    if endpoint.startswith("["):
        close = endpoint.find("]")
        if close <= 1:
            return None, None
        host = endpoint[1:close]
        rest = endpoint[close + 1:]
        if rest.startswith(":"):
            return host, rest[1:]
        return host, None
    if endpoint.count(":") == 1:
        host, port = endpoint.rsplit(":", 1)
        return host, port
    host, port = endpoint.rsplit(":", 1)
    if port.isdigit():
        return host, port
    return endpoint, None


def awg_conf_to_uri(interface, peer, display_name):
    private_key = interface.get("PrivateKey") or ""
    public_key = peer.get("PublicKey") or ""
    address = interface.get("Address") or ""
    endpoint = peer.get("Endpoint") or ""
    host, port = split_endpoint(endpoint)
    if not private_key or not public_key or not address or not host or not port:
        return None
    query = {
        "publickey": public_key,
        "address": address,
    }
    optional = [
        ("presharedkey", peer.get("PresharedKey")),
        ("mtu", interface.get("MTU")),
        ("dns", interface.get("DNS")),
        ("allowedips", peer.get("AllowedIPs")),
        ("keepalive", peer.get("PersistentKeepalive")),
        ("reserved", peer.get("Reserved") or interface.get("Reserved")),
        ("jc", interface.get("Jc")),
        ("jmin", interface.get("Jmin")),
        ("jmax", interface.get("Jmax")),
        ("s1", interface.get("S1")),
        ("s2", interface.get("S2")),
        ("s3", interface.get("S3")),
        ("s4", interface.get("S4")),
        ("h1", interface.get("H1")),
        ("h2", interface.get("H2")),
        ("h3", interface.get("H3")),
        ("h4", interface.get("H4")),
        ("i1", interface.get("I1")),
        ("i2", interface.get("I2")),
        ("i3", interface.get("I3")),
        ("i4", interface.get("I4")),
        ("i5", interface.get("I5")),
    ]
    for key, value in optional:
        if value:
            query[key] = value
    query_str = "&".join(k + "=" + quote(str(v), safe="") for k, v in query.items())
    userinfo = quote(private_key, safe="")
    return "awg://" + userinfo + "@" + host + ":" + str(port) + "?" + query_str + "#" + quote(display_name, safe="")


def load_pinned_awg():
    pinned = []
    for filename, country in PINNED_AWG_CONFIGS:
        path = os.path.join(BASE_DIR, filename)
        if not os.path.isfile(path):
            print("WARN: pinned config missing:", path)
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            interface, peer = parse_wg_conf(text)
            display_name = "Белый список | " + (country_display(country) or country)
            uri = awg_conf_to_uri(interface, peer, display_name)
            if not uri:
                print("WARN: pinned config incomplete:", filename)
                continue
            dest = os.path.join(OUT_DIR, filename)
            shutil.copy2(path, dest)
            host, port = split_endpoint(peer.get("Endpoint") or "")
            pinned.append({
                "file": filename,
                "display_name": display_name,
                "country": country,
                "host": host,
                "port": int(port) if port and str(port).isdigit() else port,
                "uri": uri,
            })
            print("INFO: pinned", filename, "->", display_name)
        except Exception as exc:
            print("WARN: pinned config failed:", filename, str(exc))
    return pinned


def fetch_source(url):
    headers = {
        "User-Agent": "v2rayN/7.12.4",
        "Accept": "text/plain,application/json,*/*",
    }
    try:
        resp = requests.get(url, timeout=20, headers=headers)
        resp.raise_for_status()
    except requests.exceptions.SSLError:
        resp = requests.get(url, timeout=20, headers=headers, verify=False)
        resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def probe_once(host, port, timeout=TIMEOUT):
    start = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, (time.monotonic() - start) * 1000.0
    except Exception:
        return False, None


def probe(host, port, attempts=ATTEMPTS, warmup=True):
    """TCP connect probe. First successful connect is warm-up and ignored for latency."""
    samples = []
    ok = 0
    warmed = False
    total = attempts + (1 if warmup else 0)
    for i in range(total):
        success, ms = probe_once(host, port)
        if not success:
            # Small pause after failure so retries are less correlated.
            time.sleep(0.05)
            continue
        ok += 1
        if warmup and not warmed:
            warmed = True
            time.sleep(0.03)
            continue
        samples.append(ms)
        if i + 1 < total:
            time.sleep(0.03)
    # If warm-up ate the only success, keep it so we don't zero out a live host.
    if ok > 0 and not samples:
        success, ms = probe_once(host, port)
        if success and ms is not None:
            samples.append(ms)
            ok = max(ok, 1)
    scored_ok = len(samples)
    return scored_ok, samples


def latency_stats(samples):
    if not samples:
        return None, None, None
    raw_worst = max(samples)
    cleaned = list(samples)
    if len(cleaned) >= 4:
        ordered = sorted(cleaned)
        cleaned = ordered[1:-1] or ordered
    median_ms = statistics.median(cleaned)
    jitter_ms = statistics.pstdev(cleaned) if len(cleaned) > 1 else 0.0
    # Keep raw worst so single spikes still fail MAX_WORST_MS.
    return median_ms, jitter_ms, raw_worst


def resolve_host(host):
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = info[4][0]
            if ":" not in ip:
                return ip
        return infos[0][4][0]
    except Exception:
        return None


def lookup_country(ip, token):
    if not ip:
        return None
    with _COUNTRY_LOCK:
        if ip in _COUNTRY_CACHE:
            return _COUNTRY_CACHE[ip]
    country = None
    if token:
        try:
            headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
            resp = requests.get("https://ipinfo.io/" + ip + "/json", headers=headers, timeout=10)
            if resp.status_code == 200:
                cc = resp.json().get("country")
                if cc:
                    country = cc
        except Exception:
            pass
    if not country:
        try:
            resp = requests.get(
                "http://ip-api.com/json/" + ip + "?fields=status,countryCode",
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") != "fail":
                    country = data.get("countryCode") or country
        except Exception:
            pass
    if not country:
        try:
            resp = requests.get("https://ipwho.is/" + ip, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") is not False:
                    country = data.get("country_code") or country
        except Exception:
            pass
    with _COUNTRY_LOCK:
        _COUNTRY_CACHE[ip] = country
    return country


def write_file(name, content):
    if not content:
        content = ""
    if not content.endswith("\n"):
        content += "\n"
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    token = os.environ.get("IPINFO_TOKEN", "")
    os.makedirs(OUT_DIR, exist_ok=True)
    pinned = load_pinned_awg()

    per_source = {}
    for url in SOURCES:
        try:
            text = fetch_source(url)
            lines = extract_nodes(text)
        except Exception as exc:
            print("WARN: source failed:", url, str(exc))
            lines = []
        per_source[url] = lines
        print("INFO: source nodes:", url, len(lines))

    seen = set()
    candidates = []
    for url in SOURCES:
        count = 0
        for line in per_source[url]:
            if count >= MAX_TEST_PER_SOURCE:
                break
            node = parse_node(line)
            if not node:
                continue
            key = (node["scheme"], node["host"], node["port"])
            if key in seen:
                continue
            if is_ru(node["name"]):
                continue
            seen.add(key)
            node["source"] = url
            node["country"] = detect_country_from_name(node["name"])
            node["resolved_ip"] = None
            node["success_rate"] = 0.0
            node["median_ms"] = None
            node["jitter_ms"] = None
            node["total_score"] = 0.0
            node["game_score"] = 0.0
            node["speed_score"] = 0.0
            candidates.append(node)
            count += 1

    print("INFO: candidates:", len(candidates))
    print("INFO: pass1 probing", len(candidates), "nodes...")

    def probe_node(node, attempts=ATTEMPTS):
        ok, samples = probe(node["host"], node["port"], attempts=attempts, warmup=True)
        node["_ok"] = ok
        node["_samples"] = samples

    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
        list(pool.map(probe_node, candidates))

    def apply_probe_stats(node, attempts):
        samples = node.get("_samples") or []
        ok = len(samples)
        rate = ok / float(attempts) if attempts else 0.0
        if rate < MIN_SUCCESS:
            return False
        median_ms, jitter_ms, worst_ms = latency_stats(samples)
        if median_ms is None:
            return False
        if median_ms > MAX_MEDIAN_MS:
            return False
        if jitter_ms > MAX_JITTER_MS:
            return False
        if worst_ms > MAX_WORST_MS:
            return False
        node["success_rate"] = round(rate, 2)
        node["median_ms"] = round(median_ms, 1)
        node["jitter_ms"] = round(jitter_ms, 1)
        node["worst_ms"] = round(worst_ms, 1)
        return True

    rough = []
    for node in candidates:
        if not apply_probe_stats(node, ATTEMPTS):
            continue
        # rough score for selecting who gets confirmation probe
        med = node["median_ms"]
        jit = node["jitter_ms"]
        node["_rough"] = node["success_rate"] * 100.0 - med * 0.2 - jit * 0.4
        rough.append(node)

    rough.sort(key=lambda n: n["_rough"], reverse=True)
    confirm_list = rough[:REPROBE_TOP]
    print("INFO: pass1 survivors:", len(rough), "| confirming top:", len(confirm_list))

    def confirm_node(node):
        ok2, samples2 = probe(
            node["host"], node["port"], attempts=CONFIRM_ATTEMPTS, warmup=True
        )
        node["_confirm_samples"] = list(samples2)
        merged = list(node.get("_samples") or []) + list(samples2)
        node["_samples"] = merged
        node["_ok"] = len(merged)
        node["_confirm_ok"] = ok2

    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
        list(pool.map(confirm_node, confirm_list))

    def enrich_node(node):
        total_attempts = ATTEMPTS + CONFIRM_ATTEMPTS
        if not apply_probe_stats(node, total_attempts):
            return None
        confirm_samples = node.get("_confirm_samples") or []
        confirm_need = max(1, int(round(CONFIRM_ATTEMPTS * MIN_SUCCESS)))
        if len(confirm_samples) < confirm_need and node["success_rate"] < 0.9:
            return None
        # Confirm round itself should not be a high-jitter spike train.
        c_med, c_jit, c_worst = latency_stats(confirm_samples)
        if c_med is not None:
            if c_med > MAX_MEDIAN_MS or c_jit > MAX_JITTER_MS or c_worst > MAX_WORST_MS:
                return None
        ip = resolve_host(node["host"])
        if not node["country"] and ip:
            node["country"] = lookup_country(ip, token)
        if node["country"] == "RU":
            return None
        node["resolved_ip"] = ip
        print(
            "INFO: ok",
            node["scheme"],
            node["host"],
            node["port"],
            "rate:",
            node["success_rate"],
            "ms:",
            node["median_ms"],
            "jitter:",
            node["jitter_ms"],
        )
        return node

    with ThreadPoolExecutor(max_workers=8) as pool:
        tested = [n for n in pool.map(enrich_node, confirm_list) if n]

    print("INFO: passed strict filter:", len(tested))

    for node in tested:
        med = node["median_ms"] if node["median_ms"] is not None else 300.0
        jit = node["jitter_ms"] if node["jitter_ms"] is not None else 50.0
        worst = node.get("worst_ms") if node.get("worst_ms") is not None else med
        src_index = SOURCES.index(node["source"]) if node["source"] in SOURCES else 9
        source_bonus = max(0, 10 - src_index * 3)
        node["total_score"] = round(
            node["success_rate"] * 120.0 - med * 0.25 - jit * 0.55 - (worst - med) * 0.15 + source_bonus,
            1,
        )
        node["game_score"] = round(
            node["success_rate"] * 120.0 - med * 0.35 - jit * 0.7 - (worst - med) * 0.2,
            1,
        )
        node["speed_score"] = round(
            node["success_rate"] * 110.0 - med * 0.2 - jit * 0.25 + source_bonus,
            1,
        )
        node["geo_rank"] = GAME_GEO.index(node["country"]) if node["country"] in GAME_GEO else 999

    # Highest score first; on ties prefer lower latency then lower jitter.
    tested.sort(
        key=lambda n: (
            -(n["total_score"] or 0),
            n["median_ms"] if n["median_ms"] is not None else 999.0,
            n["jitter_ms"] if n["jitter_ms"] is not None else 999.0,
        )
    )

    final = []
    per_src_count = {}
    for node in tested:
        src = node["source"]
        if per_src_count.get(src, 0) >= MAX_PER_SOURCE_FINAL:
            continue
        per_src_count[src] = per_src_count.get(src, 0) + 1
        final.append(node)
        if len(final) >= TOP_N:
            break

    game_pick = None
    if final:
        game_pick = sorted(
            final,
            key=lambda n: (-n["game_score"], n["geo_rank"], n["median_ms"] or 999.0, n["jitter_ms"]),
        )[0]

    speed_pick = None
    if final:
        speed_pick = sorted(
            final,
            key=lambda n: (-n["success_rate"], -n["speed_score"], n["median_ms"] or 999.0, n["jitter_ms"]),
        )[0]

    used_names = {}
    for node in final:
        if node["country"]:
            base = country_display(node["country"])
        else:
            base = "Неизвестно"
        used_names[base] = used_names.get(base, 0) + 1
        num = used_names[base]
        new_name = base if num == 1 else base + "-" + str(num)
        node["display_name"] = new_name
        node["final_raw"] = rename_node(node, new_name)

    pinned_uris = [item["uri"] for item in pinned]
    top_lines = pinned_uris + [n["final_raw"] for n in final]
    top_text = "\n".join(top_lines)
    write_file("top30.txt", top_text)
    b64_text = base64.b64encode((top_text + "\n").encode("utf-8")).decode("ascii")
    write_file("top30.b64.txt", b64_text)

    report = []
    for item in pinned:
        report.append({
            "display_name": item["display_name"],
            "source": "pinned",
            "file": item["file"],
            "scheme": "awg",
            "host": item["host"],
            "port": item["port"],
            "country": item["country"],
            "pinned": True,
        })
    for n in final:
        report.append({
            "display_name": n["display_name"],
            "source": n["source"],
            "scheme": n["scheme"],
            "host": n["host"],
            "port": n["port"],
            "resolved_ip": n["resolved_ip"],
            "country": n["country"],
            "success_rate": n["success_rate"],
            "median_ms": n["median_ms"],
            "jitter_ms": n["jitter_ms"],
            "total_score": n["total_score"],
            "game_score": n["game_score"],
            "speed_score": n["speed_score"],
            "pinned": False,
        })
    with open(os.path.join(OUT_DIR, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    clash_name = None
    clash_line = ""
    if game_pick:
        country = country_display(game_pick["country"]) or "Неизвестно"
        ms = int(round(game_pick["median_ms"] or 0.0))
        clash_name = "Clash Royale | " + country + " | " + str(ms) + "ms"
        clash_line = rename_node(game_pick, clash_name)
    write_file("clash_royale.txt", clash_line)

    speed_name = None
    speed_line = ""
    if speed_pick:
        country = country_display(speed_pick["country"]) or "Неизвестно"
        speed_name = "Speed | " + country + " | best"
        speed_line = rename_node(speed_pick, speed_name)
    write_file("speed.txt", speed_line)

    summary = {
        "selected": len(final),
        "pinned": len(pinned),
        "source_counts": {},
        "country_counts": {},
        "clash_royale_selected": clash_name,
        "speed_selected": speed_name,
        "pinned_configs": [item["file"] for item in pinned],
        "generated_files": [
            "output/top30.txt",
            "output/top30.b64.txt",
            "output/report.json",
            "output/summary.yaml",
            "output/clash_royale.txt",
            "output/speed.txt",
        ] + ["output/" + item["file"] for item in pinned],
    }
    for item in pinned:
        summary["source_counts"]["pinned"] = summary["source_counts"].get("pinned", 0) + 1
        summary["country_counts"][item["country"]] = summary["country_counts"].get(item["country"], 0) + 1
    for n in final:
        src = n["source"]
        summary["source_counts"][src] = summary["source_counts"].get(src, 0) + 1
        country = n["country"] or "unknown"
        summary["country_counts"][country] = summary["country_counts"].get(country, 0) + 1
    with open(os.path.join(OUT_DIR, "summary.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(summary, f, allow_unicode=True, sort_keys=False)

    print("INFO: pinned:", len(pinned))
    print("INFO: selected:", len(final))
    print("INFO: clash_royale:", clash_name)
    print("INFO: speed:", speed_name)


if __name__ == "__main__":
    try:
        main()
        print("DONE")
    except Exception as exc:
        traceback.print_exc()
        print("FATAL:", exc)
        sys.exit(1)
