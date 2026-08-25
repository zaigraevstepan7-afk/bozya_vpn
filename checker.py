#!/usr/bin/env python3
import base64
import glob
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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    # Griffon (needs x-hwid). Also used to refresh pinned 🇫🇷 Франция.
    "https://cdn.griffon-guard.com/sub/HaJY2J3e4hUzVaCc",
    # Nebula Curse: country nodes + LTE БС. Hiddify UA returns vless:// lines.
    "https://sub.nebulacurse.space/W83--xXdonEXYRBB/",
]

# Stable device id for panels that require HWID (Happ / Hiddify / Remnawave).
SUB_HWID = os.environ.get("SUB_HWID", "b7c4e2a1f9d83c5e6a0b1d2e3f4a5b6c")

# Always prepended to the subscription. Not probed and not counted toward TOP_N.
# Cloudflare/AmneziaWG WARP — keep even if TCP ping fails.
PINNED_AWG_CONFIGS = [
    ("LTEdWARPv2_99.conf", "DE"),
    ("LTEfWARPv2_40.conf", "FI"),
    ("LTEpWARPv2_60.conf", "PL"),
]

# Pinned Xray/Happ custom JSON configs. After AWG pins. Dead ones (TCP fail) are dropped,
# except AWG/Cloudflare above.
PINNED_CUSTOM_JSON = [
    ("FastCone_Switzerland.json", "CH", "🇨🇭 Швейцария"),
    ("VIP_LTE_Finland.json", "FI", "🇫🇮 Лютый обход | VIP LTE Финляндия"),
    ("Griffon_France.json", "FR", "🇫🇷 Франция"),
]

GRIFFON_SUB_URL = "https://cdn.griffon-guard.com/sub/HaJY2J3e4hUzVaCc"
FASTCONE_SUB_URL = "https://sub.fast-cone.com/32e027b8a8074dd41d9afe073fd85a01"
FASTCONE_HAPP_URL = "https://p.kfwl.lol/ua=happ/os=android/" + FASTCONE_SUB_URL
NEBULACURSE_SUB_URL = "https://sub.nebulacurse.space/W83--xXdonEXYRBB/"
NEBULACURSE_HAPP_URL = "https://p.kfwl.lol/ua=happ/os=android/" + NEBULACURSE_SUB_URL
MIN_NEBULA_BS = 5

OUT_DIR = os.path.join(BASE_DIR, "output")
TOP_N = 30
MAX_TEST_PER_SOURCE = 80
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


def _cidr_addresses(address):
    parts = []
    for raw in (address or "").split(","):
        item = raw.strip()
        if not item:
            continue
        if "/" in item:
            parts.append(item)
        elif ":" in item:
            parts.append(item + "/128")
        else:
            parts.append(item + "/32")
    return parts


def _encode_query(items):
    parts = []
    for key, value in items:
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        # Encode '+' '/' '=' so base64 keys and I1 tags stay intact.
        parts.append(key + "=" + quote(text, safe="-_"))
    return "&".join(parts)


def awg_conf_to_uri(interface, peer, display_name):
    """Build Happ-compatible WireGuard share links.

    Happ docs only document wireguard:// (not awg://). Unknown schemes are
    dropped from subscriptions, which is why BS servers never showed up.
    Keep titles short (<=30 chars) and put the full name in serverDescription.
    """
    private_key = interface.get("PrivateKey") or ""
    public_key = peer.get("PublicKey") or ""
    address = interface.get("Address") or ""
    endpoint = peer.get("Endpoint") or ""
    host, port = split_endpoint(endpoint)
    if not private_key or not public_key or not address or not host or not port:
        return None
    addrs = _cidr_addresses(address)
    if not addrs:
        return None
    # Prefer IPv4 local address — Happ WireGuard examples use a single address.
    addr_v4 = next((item for item in addrs if ":" not in item.split("/", 1)[0]), addrs[0])
    reserved = peer.get("Reserved") or interface.get("Reserved") or "0,0,0"
    # Keep Happ URIs short: oversized links (esp. I1) are dropped from subscriptions.
    # Amnezia I1/Jc for PattNG go into output/pattng-bs.json (Finalmask), not here.
    query = [
        ("publickey", public_key),
        ("address", addr_v4),
        ("mtu", interface.get("MTU") or "1280"),
        ("dns", re.sub(r"\s+", "", interface.get("DNS") or "")),
        ("allowedips", peer.get("AllowedIPs") or "0.0.0.0/0,::/0"),
        ("reserved", reserved),
        ("keepalive", peer.get("PersistentKeepalive") or "25"),
        ("presharedkey", peer.get("PresharedKey")),
    ]
    query_str = _encode_query(query)
    userinfo = quote(private_key, safe="-_")
    # Title: "Белый список | 🇩🇪 Германия" (fits Happ's ~30 char limit).
    short = (display_name or "Белый список")[:30]
    desc = base64.b64encode((display_name or short).encode("utf-8")).decode("ascii")
    fragment = quote(short, safe="") + "?serverDescription=" + desc
    return [
        "wireguard://" + userinfo + "@" + host + ":" + str(port) + "?" + query_str + "#" + fragment,
    ]


def awg_conf_to_clash(interface, peer, display_name):
    private_key = interface.get("PrivateKey") or ""
    public_key = peer.get("PublicKey") or ""
    address = interface.get("Address") or ""
    endpoint = peer.get("Endpoint") or ""
    host, port = split_endpoint(endpoint)
    addrs = _cidr_addresses(address)
    if not private_key or not public_key or not host or not port or not addrs:
        return None
    ip4 = next((item.split("/", 1)[0] for item in addrs if ":" not in item.split("/", 1)[0]), None)
    ip6 = next((item.split("/", 1)[0] for item in addrs if ":" in item.split("/", 1)[0]), None)
    reserved_raw = peer.get("Reserved") or interface.get("Reserved") or "0,0,0"
    reserved = []
    for part in reserved_raw.replace("[", "").replace("]", "").split(","):
        part = part.strip()
        if part.isdigit():
            reserved.append(int(part))
    if len(reserved) != 3:
        reserved = [0, 0, 0]
    option = {}
    for key, src in (
        ("jc", "Jc"), ("jmin", "Jmin"), ("jmax", "Jmax"),
        ("s1", "S1"), ("s2", "S2"), ("s3", "S3"), ("s4", "S4"),
        ("h1", "H1"), ("h2", "H2"), ("h3", "H3"), ("h4", "H4"),
        ("i1", "I1"), ("i2", "I2"), ("i3", "I3"), ("i4", "I4"), ("i5", "I5"),
    ):
        value = interface.get(src)
        if value is None or str(value).strip() == "":
            continue
        if key in ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4", "h1", "h2", "h3", "h4"):
            try:
                option[key] = int(value)
                continue
            except Exception:
                pass
        option[key] = str(value)
    proxy = {
        "name": display_name,
        "type": "wireguard",
        "server": host,
        "port": int(port),
        "private-key": private_key,
        "public-key": public_key,
        "udp": True,
        "mtu": int(interface.get("MTU") or 1280),
        "reserved": reserved,
        "allowed-ips": [item.strip() for item in (peer.get("AllowedIPs") or "0.0.0.0/0, ::/0").split(",") if item.strip()],
    }
    if ip4:
        proxy["ip"] = ip4
    if ip6:
        proxy["ipv6"] = ip6
    if option:
        proxy["amnezia-wg-option"] = option
    return proxy


def _i1_to_hex(i1):
    text = (i1 or "").strip()
    match = re.search(r"<b\s+0x([0-9a-fA-F]+)>", text)
    if match:
        return match.group(1).lower()
    if re.fullmatch(r"[0-9a-fA-F]+", text) and len(text) % 2 == 0:
        return text.lower()
    return None


def awg_to_finalmask(interface):
    """Map AmneziaWG I1/Jc junk into Xray Finalmask UDP noise for PattNG/Xray.

    Spec: https://xtls.github.io/en/config/transports/finalmask.html
    PattNG applies streamSettings.finalmask on WireGuard outbounds (CUSTOM JSON
    is passed to the core as-is).
    """
    noises = []
    i1_hex = _i1_to_hex(interface.get("I1"))
    if i1_hex:
        noises.append({
            "type": "hex",
            "packet": i1_hex,
            "delay": "0",
        })
    try:
        jc = int(interface.get("Jc") or 0)
    except Exception:
        jc = 0
    jmin = str(interface.get("Jmin") or "40").strip() or "40"
    jmax = str(interface.get("Jmax") or "70").strip() or "70"
    size = jmin + "-" + jmax
    for _ in range(max(0, min(jc, 10))):
        noises.append({
            "rand": size,
            "delay": "0-5",
        })
    if not noises:
        return None
    return {
        "udp": [
            {
                "type": "noise",
                "settings": {
                    "reset": "25-60",
                    "noise": noises,
                },
            }
        ]
    }


def _pattng_shell(remarks, outbound):
    return {
        "remarks": remarks,
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "tag": "socks",
            "port": 10808,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": True},
        }],
        "outbounds": [
            outbound,
            {"tag": "direct", "protocol": "freedom"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [],
        },
    }


def awg_conf_to_pattng_json(interface, peer, display_name):
    """Full Xray custom config that stock PattNG imports and runs as-is."""
    private_key = interface.get("PrivateKey") or ""
    public_key = peer.get("PublicKey") or ""
    address = interface.get("Address") or ""
    endpoint = peer.get("Endpoint") or ""
    host, port = split_endpoint(endpoint)
    addrs = _cidr_addresses(address)
    if not private_key or not public_key or not host or not port or not addrs:
        return None
    reserved_raw = peer.get("Reserved") or interface.get("Reserved") or "0,0,0"
    reserved = []
    for part in reserved_raw.replace("[", "").replace("]", "").split(","):
        part = part.strip()
        if part.isdigit():
            reserved.append(int(part))
    if len(reserved) != 3:
        reserved = [0, 0, 0]
    outbound = {
        "tag": "proxy",
        "protocol": "wireguard",
        "settings": {
            "secretKey": private_key,
            "address": addrs,
            "peers": [{
                "endpoint": host + ":" + str(port),
                "publicKey": public_key,
            }],
            "mtu": int(interface.get("MTU") or 1280),
            "reserved": reserved,
            "domainStrategy": "ForceIP",
        },
    }
    finalmask = awg_to_finalmask(interface)
    if finalmask:
        outbound["streamSettings"] = {"finalmask": finalmask}
    return _pattng_shell(display_name or "Белый список", outbound)


def share_uri_to_pattng_json(uri, remarks=None):
    """Best-effort share-link → PattNG CUSTOM JSON (regular nodes in full sub)."""
    node = parse_node(uri)
    if not node:
        return None
    title = remarks or node.get("name") or (node.get("host") or "node")
    scheme = node["scheme"]
    try:
        parsed = urlparse(uri)
        query = {}
        if parsed.query:
            for part in parsed.query.split("&"):
                if "=" not in part:
                    continue
                k, v = part.split("=", 1)
                query[unquote(k)] = unquote(v)
        host = parsed.hostname or node.get("host")
        port = parsed.port or node.get("port") or 443
        if not host:
            return None
        stream = {}
        network = (query.get("type") or query.get("network") or "tcp").lower()
        if network in ("ws", "websocket"):
            stream["network"] = "ws"
            stream["wsSettings"] = {
                "path": query.get("path") or "/",
                "headers": {"Host": query.get("host") or query.get("sni") or host},
            }
        elif network in ("grpc", "gun"):
            stream["network"] = "grpc"
            stream["grpcSettings"] = {"serviceName": query.get("serviceName") or query.get("path") or ""}
        elif network in ("httpupgrade",):
            stream["network"] = "httpupgrade"
            stream["httpupgradeSettings"] = {
                "path": query.get("path") or "/",
                "host": query.get("host") or "",
            }
        elif network in ("xhttp", "splithttp"):
            stream["network"] = "xhttp"
            stream["xhttpSettings"] = {
                "path": query.get("path") or "/",
                "host": query.get("host") or "",
                "mode": query.get("mode") or "",
            }
        else:
            stream["network"] = "tcp"

        security = (query.get("security") or query.get("tls") or "none").lower()
        if security in ("tls", "reality"):
            stream["security"] = security
            tls = {
                "serverName": query.get("sni") or query.get("host") or host,
                "fingerprint": query.get("fp") or "",
                "allowInsecure": query.get("allowInsecure") in ("1", "true", "TRUE"),
            }
            alpn = query.get("alpn")
            if alpn:
                tls["alpn"] = [x for x in alpn.split(",") if x]
            if security == "reality":
                tls["publicKey"] = query.get("pbk") or ""
                tls["shortId"] = query.get("sid") or ""
                tls["spiderX"] = query.get("spx") or ""
            key = "realitySettings" if security == "reality" else "tlsSettings"
            stream[key] = tls

        if scheme == "vless":
            uuid = unquote(parsed.username or "")
            if not uuid:
                return None
            user = {"id": uuid, "encryption": query.get("encryption") or "none"}
            if query.get("flow"):
                user["flow"] = query.get("flow")
            outbound = {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": host,
                        "port": int(port),
                        "users": [user],
                    }]
                },
                "streamSettings": stream,
            }
            return _pattng_shell(title, outbound)

        if scheme == "trojan":
            password = unquote(parsed.username or "")
            if not password:
                return None
            if "security" not in stream:
                stream["security"] = "tls"
                stream["tlsSettings"] = {
                    "serverName": query.get("sni") or host,
                    "allowInsecure": query.get("allowInsecure") in ("1", "true", "TRUE"),
                }
            outbound = {
                "tag": "proxy",
                "protocol": "trojan",
                "settings": {
                    "servers": [{
                        "address": host,
                        "port": int(port),
                        "password": password,
                    }]
                },
                "streamSettings": stream,
            }
            return _pattng_shell(title, outbound)

        if scheme == "hysteria2":
            password = unquote(parsed.username or "")
            if not password:
                return None
            hy = {
                "password": password,
            }
            if query.get("obfs"):
                hy["obfs"] = query.get("obfs")
            if query.get("obfs-password") or query.get("obfsPassword"):
                hy["obfsPassword"] = query.get("obfs-password") or query.get("obfsPassword")
            outbound = {
                "tag": "proxy",
                "protocol": "hysteria2",
                "settings": {
                    "servers": [{
                        "address": host,
                        "port": int(port),
                        **hy,
                    }]
                },
                "streamSettings": {
                    "network": "hysteria",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": query.get("sni") or host,
                        "allowInsecure": query.get("insecure") in ("1", "true", "TRUE"),
                    },
                },
            }
            return _pattng_shell(title, outbound)

        if scheme == "vmess" and node.get("data"):
            data = node["data"]
            net = (data.get("net") or "tcp").lower()
            scy = data.get("scy") or "auto"
            stream_v = {"network": "ws" if net in ("ws", "websocket") else net}
            if stream_v["network"] == "ws":
                stream_v["wsSettings"] = {
                    "path": data.get("path") or "/",
                    "headers": {"Host": data.get("host") or data.get("sni") or host},
                }
            tls_on = (data.get("tls") or "").lower() in ("tls", "reality")
            if tls_on:
                stream_v["security"] = "tls"
                stream_v["tlsSettings"] = {
                    "serverName": data.get("sni") or data.get("host") or host,
                    "allowInsecure": False,
                }
            outbound = {
                "tag": "proxy",
                "protocol": "vmess",
                "settings": {
                    "vnext": [{
                        "address": data.get("add") or host,
                        "port": int(data.get("port") or port),
                        "users": [{
                            "id": data.get("id") or "",
                            "alterId": int(data.get("aid") or 0),
                            "security": scy,
                        }],
                    }]
                },
                "streamSettings": stream_v,
            }
            return _pattng_shell(title, outbound)
    except Exception:
        return None
    return None


def load_pinned_awg():
    pinned = []
    errors = []
    for filename, country in PINNED_AWG_CONFIGS:
        path = os.path.join(BASE_DIR, filename)
        if not os.path.isfile(path):
            errors.append("pinned config missing: " + path)
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            interface, peer = parse_wg_conf(text)
            display_name = "Белый список | " + (country_display(country) or country)
            uris = awg_conf_to_uri(interface, peer, display_name)
            clash = awg_conf_to_clash(interface, peer, display_name)
            pattng = awg_conf_to_pattng_json(interface, peer, display_name)
            if not uris or not clash or not pattng:
                errors.append("pinned config incomplete: " + filename)
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
                "uris": uris,
                "clash": clash,
                "pattng": pattng,
            })
            print("INFO: pinned", filename, "->", display_name)
        except Exception as exc:
            errors.append("pinned config failed: " + filename + " " + str(exc))
    if errors:
        raise RuntimeError("pinned AWG configs must always be present: " + "; ".join(errors))
    if len(pinned) != len(PINNED_AWG_CONFIGS):
        raise RuntimeError("pinned AWG configs must always be present")
    return pinned


def custom_json_to_vless_uri(doc, display_name):
    """Build a Happ-compatible vless:// share link from an Xray custom config."""
    outbounds = doc.get("outbounds") or []
    outbound = next((o for o in outbounds if isinstance(o, dict) and o.get("protocol") == "vless"), None)
    if not outbound:
        return None
    vnext = ((outbound.get("settings") or {}).get("vnext") or [None])[0]
    if not vnext:
        return None
    user = (vnext.get("users") or [None])[0] or {}
    uuid = user.get("id") or ""
    host = vnext.get("address") or ""
    port = vnext.get("port") or 443
    if not uuid or not host:
        return None
    stream = outbound.get("streamSettings") or {}
    xh = stream.get("xhttpSettings") or stream.get("splithttpSettings") or {}
    tls = stream.get("tlsSettings") or stream.get("realitySettings") or {}
    security = stream.get("security") or "none"
    params = [
        ("encryption", user.get("encryption") or "none"),
        ("security", security),
        ("type", stream.get("network") or stream.get("method") or "tcp"),
    ]
    if user.get("flow"):
        params.append(("flow", user.get("flow")))
    sni = tls.get("serverName") or tls.get("server_name") or host
    if sni:
        params.append(("sni", sni))
    fp = tls.get("fingerprint") or ""
    if fp:
        params.append(("fp", fp))
    alpn = tls.get("alpn") or []
    if isinstance(alpn, list) and alpn:
        params.append(("alpn", ",".join(alpn)))
    elif isinstance(alpn, str) and alpn:
        params.append(("alpn", alpn))
    if security == "reality":
        if tls.get("publicKey"):
            params.append(("pbk", tls.get("publicKey")))
        if tls.get("shortId"):
            params.append(("sid", tls.get("shortId")))
        if tls.get("spiderX"):
            params.append(("spx", tls.get("spiderX")))
    network = (stream.get("network") or "").lower()
    if network in ("xhttp", "splithttp"):
        if xh.get("mode"):
            params.append(("mode", xh.get("mode")))
        if xh.get("host"):
            params.append(("host", xh.get("host")))
        if xh.get("path"):
            params.append(("path", xh.get("path")))
        extra = xh.get("extra")
        if extra is not None:
            if isinstance(extra, (dict, list)):
                params.append(("extra", json.dumps(extra, ensure_ascii=False, separators=(",", ":"))))
            else:
                params.append(("extra", str(extra)))
    elif network in ("ws", "websocket"):
        ws = stream.get("wsSettings") or {}
        params.append(("path", ws.get("path") or "/"))
        host_h = (ws.get("headers") or {}).get("Host") or ""
        if host_h:
            params.append(("host", host_h))
    query = _encode_query(params)
    fragment = quote(display_name or doc.get("remarks") or host, safe="")
    return "vless://" + uuid + "@" + host + ":" + str(port) + "?" + query + "#" + fragment


def custom_vless_host_port(doc):
    ob = next((o for o in (doc.get("outbounds") or []) if isinstance(o, dict) and o.get("protocol") == "vless"), {})
    vnext = ((ob.get("settings") or {}).get("vnext") or [{}])[0]
    return vnext.get("address"), vnext.get("port")


def tcp_alive(host, port, attempts=3, timeout=2.5):
    if not host or not port:
        return False
    ok = 0
    for _ in range(attempts):
        success, _ms = probe_once(host, int(port), timeout=timeout)
        if success:
            ok += 1
    return ok >= 2


def _write_json(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _pin_entry_from_doc(filename, country, display_name, doc):
    doc = dict(doc)
    doc["remarks"] = display_name
    uri = custom_json_to_vless_uri(doc, display_name)
    dest = os.path.join(OUT_DIR, filename)
    _write_json(dest, doc)
    host, port = custom_vless_host_port(doc)
    return {
        "file": filename,
        "display_name": display_name,
        "country": country,
        "host": host,
        "port": port,
        "uris": [uri] if uri else [],
        "clash": None,
        "pattng": doc,
        "kind": "custom",
    }


def load_pinned_custom():
    """Load pinned CUSTOM JSON. Drop non-Cloudflare pins whose TCP probe fails."""
    pinned = []
    for filename, country, display_name in PINNED_CUSTOM_JSON:
        path = os.path.join(BASE_DIR, filename)
        if not os.path.isfile(path):
            print("WARN: pinned custom missing, skip:", filename)
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if not isinstance(doc, dict):
                print("WARN: pinned custom not an object, skip:", filename)
                continue
            host, port = custom_vless_host_port(doc)
            if not tcp_alive(host, port):
                print("WARN: drop dead pinned custom", filename, host, port)
                continue
            entry = _pin_entry_from_doc(filename, country, display_name, doc)
            pinned.append(entry)
            print("INFO: pinned custom", filename, "->", display_name)
        except Exception as exc:
            print("WARN: pinned custom failed:", filename, str(exc))

    nebula_auto = os.path.join(BASE_DIR, "Nebula_Auto.json")
    if os.path.isfile(nebula_auto):
        try:
            with open(nebula_auto, "r", encoding="utf-8") as f:
                doc = json.load(f)
            remarks = (doc.get("remarks") if isinstance(doc, dict) else None) or "🇪🇺 Автовыбор"
            dest = os.path.join(OUT_DIR, "Nebula_Auto.json")
            _write_json(dest, doc)
            host, port = custom_vless_host_port(doc)
            pinned.append({
                "file": "Nebula_Auto.json",
                "display_name": remarks,
                "country": "EU",
                "host": host,
                "port": port,
                "uris": [],
                "clash": None,
                "pattng": doc,
                "kind": "custom",
            })
            print("INFO: pinned custom Nebula_Auto.json ->", remarks)
        except Exception as exc:
            print("WARN: Nebula_Auto.json failed:", str(exc))

    for path in sorted(glob.glob(os.path.join(BASE_DIR, "Nebula_BS_*.json"))):
        filename = os.path.basename(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if not isinstance(doc, dict):
                continue
            remarks = doc.get("remarks") or filename
            host, port = custom_vless_host_port(doc)
            if not tcp_alive(host, port):
                print("WARN: drop dead nebula BS", filename, host, port)
                continue
            country = flag_to_country(remarks) or "EU"
            entry = _pin_entry_from_doc(filename, country, remarks, doc)
            pinned.append(entry)
            print("INFO: pinned custom", filename, "->", remarks)
        except Exception as exc:
            print("WARN: nebula BS failed:", filename, str(exc))
    return pinned


def fetch_source(url):
    headers = {
        "User-Agent": "HiddifyNext/2.0",
        "Accept": "text/plain,application/json,*/*",
        "x-hwid": SUB_HWID,
        "X-HWID": SUB_HWID,
    }
    try:
        resp = requests.get(url, timeout=30, headers=headers)
        resp.raise_for_status()
    except requests.exceptions.SSLError:
        resp = requests.get(url, timeout=30, headers=headers, verify=False)
        resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def refresh_griffon_france_pin():
    """Refresh pinned 🇫🇷 Франция from Griffon sub; keep last file on failure."""
    path = os.path.join(BASE_DIR, "Griffon_France.json")
    try:
        text = fetch_source(GRIFFON_SUB_URL)
        lines = extract_nodes(text)
        france_uri = None
        for line in lines:
            node = parse_node(line)
            name = (node or {}).get("name") or ""
            if "#" in line and not name:
                name = unquote(line.split("#", 1)[1])
            low = name.lower()
            if "🇫🇷" in name and ("франц" in low or "france" in low):
                france_uri = line.strip()
                break
        if not france_uri:
            print("WARN: Griffon France node not found, keeping previous pin")
            return
        display = "🇫🇷 Франция"
        # Prefer full custom JSON via Happ proxy when available; else URI→CUSTOM.
        doc = None
        try:
            proxy = "https://p.kfwl.lol/ua=happ/os=android/" + GRIFFON_SUB_URL
            resp = requests.get(
                proxy,
                timeout=45,
                headers={"User-Agent": "Happ/Android", "x-hwid": SUB_HWID},
                verify=False,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    rem = item.get("remarks") or ""
                    if "🇫🇷" in rem and "Франция" in rem:
                        doc = dict(item)
                        break
        except Exception as exc:
            print("WARN: Griffon Happ-JSON refresh failed:", str(exc))
        if doc is None:
            doc = share_uri_to_pattng_json(france_uri, display)
        if not doc:
            print("WARN: could not build Griffon France config, keeping previous pin")
            return
        doc["remarks"] = display
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        uri_path = os.path.join(BASE_DIR, "Griffon_France.uri")
        renamed = rename_node(parse_node(france_uri), display) if parse_node(france_uri) else france_uri
        # rename_node needs scheme; fallback to raw with new fragment
        if parse_node(france_uri):
            with open(uri_path, "w", encoding="utf-8") as f:
                f.write(rename_node(parse_node(france_uri), display) + "\n")
        print("INFO: refreshed Griffon France pin")
    except Exception as exc:
        print("WARN: Griffon France refresh failed, keeping previous pin:", str(exc))


def refresh_fastcone_switzerland_pin():
    """Refresh pinned 🇨🇭 Швейцария from FastCone Happ JSON; keep last file on failure."""
    path = os.path.join(BASE_DIR, "FastCone_Switzerland.json")
    display = "🇨🇭 Швейцария"
    try:
        resp = requests.get(
            FASTCONE_HAPP_URL,
            timeout=45,
            headers={"User-Agent": "Happ/Android", "x-hwid": SUB_HWID},
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        doc = None
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                rem = item.get("remarks") or ""
                if "🇨🇭" in rem or "Швейцария" in rem or "Switzerland" in rem:
                    doc = dict(item)
                    break
        if not doc:
            print("WARN: FastCone Switzerland node not found, keeping previous pin")
            return
        doc["remarks"] = display
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("INFO: refreshed FastCone Switzerland pin")
    except Exception as exc:
        print("WARN: FastCone Switzerland refresh failed, keeping previous pin:", str(exc))


def _happ_vless_outbound(doc):
    for o in doc.get("outbounds") or []:
        if isinstance(o, dict) and o.get("protocol") == "vless":
            return o
    return None


def _clone_proxy_outbound(doc, tag):
    ob = _happ_vless_outbound(doc)
    if not ob:
        return None
    copy = json.loads(json.dumps(ob))
    copy["tag"] = tag
    return copy


def refresh_nebulacurse_pins(token=""):
    """Pin Автовыбор + at least 5 non-RU LTE БС from Nebula Curse. Refresh each run."""
    for path in glob.glob(os.path.join(BASE_DIR, "Nebula_BS_*.json")):
        try:
            os.remove(path)
        except Exception:
            pass
    auto_path = os.path.join(BASE_DIR, "Nebula_Auto.json")
    try:
        resp = requests.get(
            NEBULACURSE_HAPP_URL,
            timeout=45,
            headers={"User-Agent": "Happ/Android", "x-hwid": SUB_HWID},
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            print("WARN: Nebula Curse JSON is not a list, keeping previous pins")
            return
    except Exception as exc:
        print("WARN: Nebula Curse fetch failed, keeping previous pins:", str(exc))
        return

    jobs = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        rem = item.get("remarks") or ""
        host, port = custom_vless_host_port(item)
        if not host or not port:
            continue
        jobs.append((i, rem, host, int(port), item))

    probe_stats = {"ok": 0, "fail": 0}
    results = []

    def one(job):
        i, rem, host, port, item = job
        ok = 0
        samples = []
        ip = None
        try:
            ip = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4][0]
        except Exception:
            return i, rem, host, port, item, 0, None, None
        for _ in range(3):
            success, ms = probe_once(host, port, timeout=2.5)
            if success:
                ok += 1
                samples.append(ms)
        med = statistics.median(samples) if samples else None
        return i, rem, host, port, item, ok, med, ip

    with ThreadPoolExecutor(max_workers=16) as pool:
        for row in pool.map(one, jobs):
            i, rem, host, port, item, ok, med, ip = row
            alive = ok >= 2
            probe_stats["ok" if alive else "fail"] += 1
            print(
                "INFO: nebula probe",
                "OK" if alive else "FAIL",
                rem,
                host + ":" + str(port),
                "med:" + (str(round(med, 1)) if med is not None else "-"),
            )
            results.append({
                "i": i, "rem": rem, "host": host, "port": port, "item": item,
                "ok": alive, "med": med, "ip": ip,
            })

    print(
        "INFO: nebula ping: working",
        probe_stats["ok"],
        "dead",
        probe_stats["fail"],
        "total",
        probe_stats["ok"] + probe_stats["fail"],
    )

    country_nodes = []
    bs_nodes = []
    seen_host = set()
    for row in results:
        rem = row["rem"]
        if not row["ok"]:
            continue
        if is_ru(rem) or "🇷🇺" in rem:
            continue
        cc = None
        if row["ip"]:
            cc = lookup_country(row["ip"], token)
        if cc == "RU":
            print("INFO: skip nebula RU IP", rem, row["ip"])
            continue
        row["country"] = cc
        key = (row["host"], row["port"])
        if "БС" in rem or rem.startswith("🇪🇺LTE-"):
            if key in seen_host:
                continue
            seen_host.add(key)
            bs_nodes.append(row)
        elif "мост" in rem.lower() and "rev.2" not in rem.lower() and row["port"] == 596:
            continue
        else:
            country_nodes.append(row)

    bs_nodes.sort(key=lambda r: r["med"] if r["med"] is not None else 9999)
    if len(bs_nodes) < MIN_NEBULA_BS:
        print("WARN: only", len(bs_nodes), "unique non-RU nebula BS alive, need", MIN_NEBULA_BS)
    picked_bs = bs_nodes[:8]
    if len(picked_bs) < MIN_NEBULA_BS:
        print("WARN: nebula BS pins below minimum")
    for idx, row in enumerate(picked_bs, start=1):
        doc = dict(row["item"])
        num = None
        m = re.search(r"LTE-(\d+)", row["rem"])
        if m:
            num = m.group(1)
        geo = country_display(row.get("country")) if row.get("country") else "🇪🇺 Европа"
        display = "Белый список | LTE-" + (num or str(idx)) + " · " + geo
        doc["remarks"] = display
        path = os.path.join(BASE_DIR, "Nebula_BS_%02d.json" % idx)
        _write_json(path, doc)
        print("INFO: nebula BS pin", display, row["host"] + ":" + str(row["port"]), "ms", round(row["med"] or 0, 1))

    # Unique country endpoints for auto-select (skip RU, skip dead).
    auto_members = []
    auto_seen = set()
    for row in country_nodes:
        if "LTE-" in row["rem"] or "БС" in row["rem"]:
            continue
        key = (row["host"], row["port"])
        if key in auto_seen:
            continue
        auto_seen.add(key)
        auto_members.append(row)
    auto_members.sort(key=lambda r: r["med"] if r["med"] is not None else 9999)
    auto_members = auto_members[:8]
    if auto_members:
        outbounds = []
        tags = []
        for i, row in enumerate(auto_members, start=1):
            tag = "auto-" + str(i)
            ob = _clone_proxy_outbound(row["item"], tag)
            if not ob:
                continue
            outbounds.append(ob)
            tags.append(tag)
        if tags:
            outbounds.append({"tag": "direct", "protocol": "freedom"})
            outbounds.append({"tag": "block", "protocol": "blackhole"})
            auto_doc = {
                "remarks": "🇪🇺 Автовыбор",
                "log": {"loglevel": "warning"},
                "inbounds": [{
                    "tag": "socks",
                    "port": 10808,
                    "listen": "127.0.0.1",
                    "protocol": "socks",
                    "settings": {"udp": True},
                }],
                "outbounds": outbounds,
                "routing": {
                    "domainStrategy": "AsIs",
                    "balancers": [{
                        "tag": "auto",
                        "selector": tags,
                        "strategy": {"type": "leastPing"},
                    }],
                    "rules": [{
                        "type": "field",
                        "network": "tcp,udp",
                        "balancerTag": "auto",
                    }],
                },
                "observatory": {
                    "subjectSelector": tags,
                    "probeUrl": "https://www.gstatic.com/generate_204",
                    "probeInterval": "1m",
                    "enableConcurrency": True,
                },
            }
            _write_json(auto_path, auto_doc)
            print("INFO: nebula auto-select members", len(tags), [r["rem"] for r in auto_members[:len(tags)]])
    else:
        print("WARN: no nebula country nodes for auto-select")


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
    refresh_fastcone_switzerland_pin()
    refresh_griffon_france_pin()
    refresh_nebulacurse_pins(token)
    pinned_custom = load_pinned_custom()
    # Order: AWG whitelist, then healthy custom pins (CH / VIP FI / FR / auto / nebula BS).
    pinned_all = pinned + pinned_custom
    pinned_keys = set()
    for item in pinned_all:
        if item.get("host") and item.get("port"):
            pinned_keys.add(("vless", item["host"], int(item["port"]) if str(item["port"]).isdigit() else item["port"]))
            pinned_keys.add((item.get("kind") or "awg", item["host"], item["port"]))
            pinned_keys.add(("wireguard", item["host"], item["port"]))
            pinned_keys.add(("any", item["host"], int(item["port"]) if str(item["port"]).isdigit() else item["port"]))

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
            if ("any", node["host"], node["port"]) in pinned_keys or key in pinned_keys:
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

    pinned_uris = []
    for item in pinned_all:
        pinned_uris.extend(item["uris"])
    top_lines = pinned_uris + [n["final_raw"] for n in final]
    top_text = "\n".join(top_lines)
    write_file("top30.txt", top_text)
    b64_text = base64.b64encode((top_text + "\n").encode("utf-8")).decode("ascii")
    write_file("top30.b64.txt", b64_text)
    # Tiny subscription with only BS/AWG pins — use if the mixed list drops them.
    awg_uris = []
    for item in pinned:
        awg_uris.extend(item["uris"])
    write_file("bs.txt", "\n".join(awg_uris))
    write_file("happ-bs.txt", "\n".join(awg_uris))
    write_file("bs.b64.txt", base64.b64encode(("\n".join(awg_uris) + "\n").encode("utf-8")).decode("ascii"))
    write_file("happ-bs.b64.txt", base64.b64encode(("\n".join(awg_uris) + "\n").encode("utf-8")).decode("ascii"))
    clash_doc = {
        "proxies": [item["clash"] for item in pinned if item.get("clash")],
        "proxy-groups": [{
            "name": "Белый список",
            "type": "select",
            "proxies": [item["display_name"] for item in pinned if item.get("clash")],
        }],
    }
    with open(os.path.join(OUT_DIR, "whitelist.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(clash_doc, f, allow_unicode=True, sort_keys=False)
    pattng_docs = [item["pattng"] for item in pinned]
    with open(os.path.join(OUT_DIR, "pattng-bs.json"), "w", encoding="utf-8") as f:
        json.dump(pattng_docs, f, ensure_ascii=False, indent=2)
        f.write("\n")
    pattng_min = json.dumps(pattng_docs, ensure_ascii=False, separators=(",", ":"))
    write_file("pattng-bs.min.json", pattng_min)
    write_file(
        "pattng-bs.b64.txt",
        base64.b64encode(pattng_min.encode("utf-8")).decode("ascii"),
    )
    # Full PattNG: AWG + VIP LTE pins first, then regular nodes.
    pattng_full = [item["pattng"] for item in pinned_all]
    for n in final:
        converted = share_uri_to_pattng_json(n["final_raw"], n["display_name"])
        if converted:
            pattng_full.append(converted)
        else:
            print("WARN: skip PattNG convert", n.get("display_name"), n.get("scheme"))
    with open(os.path.join(OUT_DIR, "pattng-full.json"), "w", encoding="utf-8") as f:
        json.dump(pattng_full, f, ensure_ascii=False, indent=2)
        f.write("\n")
    pattng_full_min = json.dumps(pattng_full, ensure_ascii=False, separators=(",", ":"))
    write_file("pattng-full.min.json", pattng_full_min)
    write_file(
        "pattng-full.b64.txt",
        base64.b64encode(pattng_full_min.encode("utf-8")).decode("ascii"),
    )

    report = []
    for item in pinned_all:
        report.append({
            "display_name": item["display_name"],
            "source": "pinned",
            "file": item["file"],
            "scheme": item.get("kind") or "awg",
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
        "pinned": len(pinned_all),
        "source_counts": {},
        "country_counts": {},
        "clash_royale_selected": clash_name,
        "speed_selected": speed_name,
        "pinned_configs": [item["file"] for item in pinned_all],
        "generated_files": [
            "output/top30.txt",
            "output/top30.b64.txt",
            "output/bs.txt",
            "output/happ-bs.txt",
            "output/pattng-bs.json",
            "output/pattng-bs.min.json",
            "output/pattng-bs.b64.txt",
            "output/pattng-full.json",
            "output/pattng-full.min.json",
            "output/pattng-full.b64.txt",
            "output/whitelist.yaml",
            "output/report.json",
            "output/summary.yaml",
            "output/clash_royale.txt",
            "output/speed.txt",
        ] + ["output/" + item["file"] for item in pinned_all],
    }
    for item in pinned_all:
        summary["source_counts"]["pinned"] = summary["source_counts"].get("pinned", 0) + 1
        summary["country_counts"][item["country"]] = summary["country_counts"].get(item["country"], 0) + 1
    for n in final:
        src = n["source"]
        summary["source_counts"][src] = summary["source_counts"].get(src, 0) + 1
        country = n["country"] or "unknown"
        summary["country_counts"][country] = summary["country_counts"].get(country, 0) + 1
    with open(os.path.join(OUT_DIR, "summary.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(summary, f, allow_unicode=True, sort_keys=False)

    print("INFO: pinned:", len(pinned_all))
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
