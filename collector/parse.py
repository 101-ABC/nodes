"""订阅文本 -> 标准化节点对象。只用标准库。"""
import base64
import binascii
import hashlib
import json
import re
import urllib.parse

SUPPORTED = ("vmess", "vless", "trojan", "ss", "hysteria2", "tuic")
ALIAS = {"hy2": "hysteria2", "ssr": None}


def b64d(s: str) -> str:
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s).decode("utf-8", "ignore")
    except (binascii.Error, ValueError):
        return ""


def looks_base64(text: str) -> bool:
    t = text.strip()
    if not t or "://" in t:
        return False
    lines = [l for l in t.splitlines() if l.strip()]
    if len(lines) > 3:
        return False
    body = re.sub(r"\s+", "", t)
    return bool(re.fullmatch(r"[A-Za-z0-9+/=_-]{32,}", body))


def split_lines(payload: str):
    """源内容可能是 base64 也可能明文。"""
    payload = payload.strip()
    if not payload:
        return []
    if looks_base64(payload):
        out = b64d(payload)
        if "://" in out:
            return out.splitlines()
    return payload.splitlines()


def _qs(url) -> dict:
    return {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}


def _mk(type_, server, port, secret, name="", **kw):
    if not server or not port:
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    if not (0 < port < 65536):
        return None
    d = {
        "type": type_,
        "server": server.strip("[]"),
        "port": port,
        "secret": secret or "",
        "name": (name or "").strip(),
        "net": kw.get("net", "tcp"),
        "path": kw.get("path", "") or "",
        "sni": kw.get("sni", "") or "",
        "tls": bool(kw.get("tls", False)),
        "cipher": kw.get("cipher", ""),
        "extra": kw.get("extra", {}),
    }
    return d


def parse_vmess(link: str):
    body = b64d(link[8:])
    if not body:
        return None
    try:
        j = json.loads(body)
    except json.JSONDecodeError:
        return None
    return _mk(
        "vmess", j.get("add"), j.get("port"), j.get("id"), j.get("ps", ""),
        net=j.get("net", "tcp"), path=j.get("path", ""),
        sni=j.get("host", "") or j.get("sni", ""),
        tls=(j.get("tls") == "tls"),
        extra={"aid": j.get("aid", "0"), "scy": j.get("scy", "auto")},
    )


def parse_url(link: str):
    try:
        u = urllib.parse.urlsplit(link)
    except ValueError:
        return None
    scheme = ALIAS.get(u.scheme, u.scheme)
    if scheme not in SUPPORTED:
        return None
    q = _qs(u)
    name = urllib.parse.unquote(u.fragment or "")
    secret = urllib.parse.unquote(u.username or "")
    host, port = u.hostname, u.port
    net = q.get("type", q.get("net", "tcp"))
    path = urllib.parse.unquote(q.get("path", "")) or ""
    sni = q.get("sni", q.get("peer", q.get("host", ""))) or ""
    tls = q.get("security", q.get("tls", "")) in ("tls", "reality", "xtls") or scheme in ("trojan", "hysteria2", "tuic")
    return _mk(scheme, host, port, secret, name, net=net, path=path, sni=sni, tls=tls, extra=q)


def parse_ss(link: str):
    body = link[5:]
    name = ""
    if "#" in body:
        body, _, frag = body.partition("#")
        name = urllib.parse.unquote(frag)
    body = body.split("?")[0]
    if "@" in body:
        cred, _, hostpart = body.rpartition("@")
        if ":" not in cred:
            cred = b64d(cred)
        host, _, port = hostpart.rpartition(":")
        if ":" in cred:
            cipher, _, pwd = cred.partition(":")
            return _mk("ss", host, port, pwd, name, cipher=cipher)
        return None
    plain = b64d(body)
    if "@" not in plain:
        return None
    cred, _, hostpart = plain.rpartition("@")
    host, _, port = hostpart.rpartition(":")
    cipher, _, pwd = cred.partition(":")
    return _mk("ss", host, port, pwd, name, cipher=cipher)


def parse_line(line: str):
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return None
    low = line.lower()
    try:
        if low.startswith("vmess://"):
            n = parse_vmess(line)
        elif low.startswith("ss://"):
            n = parse_ss(line)
        elif low.startswith(("vless://", "trojan://", "hysteria2://", "hy2://", "tuic://")):
            n = parse_url(line)
        else:
            return None
    except Exception:
        return None
    if not n:
        return None
    n["raw"] = line
    n["fp"] = fingerprint(n)
    return n


def fingerprint(n: dict) -> str:
    key = f'{n["type"]}|{n["server"].lower()}|{n["port"]}|{n["secret"]}'
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# ---------- 地区识别 ----------

COUNTRIES = {
    "HK": "香港", "TW": "台湾", "JP": "日本", "SG": "新加坡", "US": "美国", "KR": "韩国",
    "GB": "英国", "UK": "英国", "DE": "德国", "NL": "荷兰", "RU": "俄罗斯", "FR": "法国",
    "CA": "加拿大", "AU": "澳大利亚", "IN": "印度", "TR": "土耳其", "BR": "巴西",
    "VN": "越南", "TH": "泰国", "MY": "马来西亚", "PH": "菲律宾", "ID": "印尼",
    "AE": "阿联酋", "IT": "意大利", "ES": "西班牙", "SE": "瑞典", "CH": "瑞士",
    "PL": "波兰", "UA": "乌克兰", "FI": "芬兰", "NO": "挪威", "IE": "爱尔兰",
    "AT": "奥地利", "BE": "比利时", "DK": "丹麦", "CZ": "捷克", "RO": "罗马尼亚",
    "LT": "立陶宛", "LV": "拉脱维亚", "EE": "爱沙尼亚", "CL": "智利", "AR": "阿根廷",
    "ZA": "南非", "MX": "墨西哥", "KZ": "哈萨克斯坦", "SA": "沙特", "IL": "以色列",
    "NZ": "新西兰", "PT": "葡萄牙", "GR": "希腊", "HU": "匈牙利", "BG": "保加利亚",
}

FLAG_EMOJI = {
    "🇭🇰": "HK", "🇹🇼": "TW", "🇯🇵": "JP", "🇸🇬": "SG", "🇺🇸": "US", "🇰🇷": "KR",
    "🇬🇧": "GB", "🇩🇪": "DE", "🇳🇱": "NL", "🇷🇺": "RU", "🇫🇷": "FR", "🇨🇦": "CA",
    "🇦🇺": "AU", "🇮🇳": "IN", "🇹🇷": "TR", "🇧🇷": "BR", "🇻🇳": "VN", "🇹🇭": "TH",
    "🇲🇾": "MY", "🇵🇭": "PH", "🇮🇩": "ID", "🇦🇪": "AE", "🇮🇹": "IT", "🇪🇸": "ES",
    "🇸🇪": "SE", "🇨🇭": "CH", "🇵🇱": "PL", "🇺🇦": "UA", "🇫🇮": "FI", "🇳🇴": "NO",
    "🇮🇪": "IE", "🇦🇹": "AT", "🇧🇪": "BE", "🇩🇰": "DK", "🇨🇿": "CZ", "🇷🇴": "RO",
    "🇱🇹": "LT", "🇱🇻": "LV", "🇪🇪": "EE", "🇨🇱": "CL", "🇦🇷": "AR", "🇿🇦": "ZA",
    "🇲🇽": "MX", "🇰🇿": "KZ", "🇸🇦": "SA", "🇮🇱": "IL", "🇳🇿": "NZ", "🇵🇹": "PT",
    "🇬🇷": "GR", "🇭🇺": "HU", "🇧🇬": "BG",
}

CITY_WORDS = {
    "tokyo": "JP", "osaka": "JP", "singapore": "SG", "hongkong": "HK", "hong kong": "HK",
    "taipei": "TW", "seoul": "KR", "los angeles": "US", "san jose": "US", "seattle": "US",
    "new york": "US", "frankfurt": "DE", "london": "GB", "amsterdam": "NL",
    "moscow": "RU", "paris": "FR", "toronto": "CA", "sydney": "AU", "mumbai": "IN",
    "istanbul": "TR", "sao paulo": "BR", "hanoi": "VN", "bangkok": "TH", "jakarta": "ID",
    "dubai": "AE", "milan": "IT", "madrid": "ES", "stockholm": "SE", "zurich": "CH",
    "warsaw": "PL", "kyiv": "UA", "helsinki": "FI", "oslo": "NO", "dublin": "IE",
    "vienna": "AT", "brussels": "BE", "copenhagen": "DK", "prague": "CZ",
}


def guess_country(name: str) -> str:
    if not name:
        return "--"
    for emoji, code in FLAG_EMOJI.items():
        if emoji in name:
            return code
    low = name.lower()
    for word, code in CITY_WORDS.items():
        if word in low:
            return code
    m = re.search(r"(?:^|[^A-Za-z])([A-Z]{2})(?:[^A-Za-z]|$)", name)
    if m and m.group(1) in COUNTRIES:
        return m.group(1)
    for code, cn in COUNTRIES.items():
        if cn in name:
            return code
    return "--"
