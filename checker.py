#!/usr/bin/env python3
import base64
import json
import os
import re
import socket
import statistics
import sys
import time
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

SOURCES = [
    "https://sub.aska.lol/Ux7lmK0xkIl2",
    "https://connliberty.com/connection/subs/dcf2b960-d490-40dd-a18b-1718550f939e",
    "https://akonit.tech/sub/f9afd2d3-3858-403e-bbc9-9a720420c188",
    "https://sub.vlessfo.ru/vlessforu/working_configs.txt",
]

OUT_DIR = "output"
TOP_N = 30
MAX_TEST_PER_SOURCE = 25
MAX_PER_SOURCE_FINAL = 15
MIN_SUCCESS = 0.66
ATTEMPTS = 3
TIMEOUT = 3.0

SCHEMES = ("vless://", "vmess://", "trojan://", "hysteria2://", "hy2://")
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
    low = text.lower()
    flag = flag_to_country(low)
    if flag:
        return flag
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
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(SCHEMES):
            found.append(line)
            continue
        decoded = try_b64_line(line)
        if decoded:
            for piece in decoded.splitlines():
                piece = piece.strip()
                if piece.startswith(SCHEMES):
                    found.append(piece)
    return found


def parse_generic(uri, scheme):
    try:
        parsed = urlparse(uri)
        host = parsed.hostname or ""
        port = parsed.port or 443
        name = unquote(parsed.fragment or "")
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
        return {"scheme": "vmess", "host": host, "port": port, "name": name, "data": data, "raw": uri}
    except Exception:
        return None


def parse_node(line):
    if line.startswith("vmess://"):
        return parse_vmess(line)
    if line.startswith("vless://"):
        return parse_generic(line, "vless")
    if line.startswith("trojan://"):
        return parse_generic(line, "trojan")
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


def fetch_source(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; subscription-checker/1.0)"}
    try:
        resp = requests.get(url, timeout=20, headers=headers)
        resp.raise_for_status()
    except Exception:
        resp = requests.get(url, timeout=20, headers=headers, verify=False)
        resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def probe(host, port):
    samples = []
    ok = 0
    for _ in range(ATTEMPTS):
        start = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=TIMEOUT):
                ok += 1
                samples.append((time.monotonic() - start) * 1000.0)
        except Exception:
            pass
    return ok, samples


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
    if token:
        try:
            headers = {"Accept": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            resp = requests.get("https://ipinfo.io/" + ip + "/json", headers=headers, timeout=10)
            if resp.status_code == 200:
                cc = resp.json().get("country")
                if cc:
                    return cc
        except Exception:
            pass
    try:
        resp = requests.get("http://ip-api.com/json/" + ip + "?fields=countryCode", timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("countryCode")
    except Exception:
        pass
    return None


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
    print("INFO: probing", len(candidates), "nodes in parallel, wait...")

    def probe_node(node):
        ok, samples = probe(node["host"], node["port"])
        node["_ok"] = ok
        node["_samples"] = samples

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(probe_node, candidates))

    tested = []
    for node in candidates:
        ok = node["_ok"]
        samples = node["_samples"]
        rate = ok / float(ATTEMPTS)
        if rate < MIN_SUCCESS:
            continue
        ip = resolve_host(node["host"])
        if not node["country"] and ip:
            node["country"] = lookup_country(ip, token)
        if node["country"] == "RU":
            continue
        median_ms = statistics.median(samples) if samples else None
        jitter_ms = statistics.pstdev(samples) if len(samples) > 1 else 0.0
        node["resolved_ip"] = ip
        node["success_rate"] = round(rate, 2)
        node["median_ms"] = round(median_ms, 1) if median_ms is not None else None
        node["jitter_ms"] = round(jitter_ms, 1)
        tested.append(node)
        print("INFO: ok", node["scheme"], node["host"], node["port"], "rate:", rate, "ms:", median_ms)

    print("INFO: passed filter:", len(tested))

    for node in tested:
        med = node["median_ms"] if node["median_ms"] is not None else 300.0
        jit = node["jitter_ms"] if node["jitter_ms"] is not None else 50.0
        src_index = SOURCES.index(node["source"]) if node["source"] in SOURCES else 9
        source_bonus = max(0, 10 - src_index * 3)
        node["total_score"] = round(node["success_rate"] * 100.0 - med * 0.1 - jit * 0.2, 1)
        node["game_score"] = round(node["success_rate"] * 100.0 - med * 0.15 - jit * 0.3, 1)
        node["speed_score"] = round(node["success_rate"] * 100.0 - med * 0.1 - jit * 0.1 + source_bonus, 1)
        node["geo_rank"] = GAME_GEO.index(node["country"]) if node["country"] in GAME_GEO else 999

    tested.sort(key=lambda n: n["total_score"], reverse=True)

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
            key=lambda n: (-n["success_rate"], n["median_ms"] or 999.0, n["jitter_ms"], n["geo_rank"]),
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

    top_text = "\n".join(n["final_raw"] for n in final)
    if not top_text.endswith("\n"):
        top_text += "\n"
    write_file("top30.txt", top_text)
    b64_text = base64.b64encode(top_text.encode("utf-8")).decode("ascii")
    write_file("top30.b64.txt", b64_text)

    report = []
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
        })
    with open(os.path.join(OUT_DIR, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    clash_name = None
    clash_line = ""
    if game_pick:
        country = country_display(game_pick["country"])
        ms = int(round(game_pick["median_ms"] or 0.0))
        clash_name = "Clash Royale | " + country + " | " + str(ms) + "ms"
        clash_line = rename_node(game_pick, clash_name)
    write_file("clash_royale.txt", clash_line)

    speed_name = None
    speed_line = ""
    if speed_pick:
        country = country_display(speed_pick["country"])
        speed_name = "Speed | " + country + " | best"
        speed_line = rename_node(speed_pick, speed_name)
    write_file("speed.txt", speed_line)

    summary = {
        "selected": len(final),
        "source_counts": {},
        "country_counts": {},
        "clash_royale_selected": clash_name,
        "speed_selected": speed_name,
        "generated_files": [
            "output/top30.txt",
            "output/top30.b64.txt",
            "output/report.json",
            "output/summary.yaml",
            "output/clash_royale.txt",
            "output/speed.txt",
        ],
    }
    for n in final:
        src = n["source"]
        summary["source_counts"][src] = summary["source_counts"].get(src, 0) + 1
        country = n["country"] or "unknown"
        summary["country_counts"][country] = summary["country_counts"].get(country, 0) + 1
    with open(os.path.join(OUT_DIR, "summary.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(summary, f, allow_unicode=True, sort_keys=False)

    print("INFO: selected:", len(final))
    print("INFO: clash_royale:", clash_name)
    print("INFO: speed:", speed_name)


if __name__ == "__main__":
    try:
        main()
        print("DONE")
    except Exception as exc:
        print("FATAL:", exc)
        sys.exit(1)
