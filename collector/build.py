"""把已测活的节点写成 Clash / base64 / sing-box / 前端 JSON 四类产物。"""
import base64
import json
from pathlib import Path

from parse import COUNTRIES

CLASH_TEST_URL = "http://cp.cloudflare.com/generate_204"


# ---------- YAML 小工具 ----------
def q(s) -> str:
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def yaml_proxy(p: dict) -> str:
    t = p["type"]
    lines = [f"  - name: {q(p['name'])}", f"    type: {t}",
             f"    server: {q(p['server'])}", f"    port: {p['port']}"]
    if t == "ss":
        lines.append(f"    cipher: {q(p.get('cipher') or 'aes-256-gcm')}")
        lines.append(f"    password: {q(p['secret'])}")
    elif t == "trojan":
        lines.append(f"    password: {q(p['secret'])}")
        lines.append("    udp: true")
        lines.append("    skip-cert-verify: false")
        if p.get("sni"):
            lines.append(f"    sni: {q(p['sni'])}")
    elif t in ("hysteria2", "tuic"):
        lines.append(f"    password: {q(p['secret'])}")
        lines.append("    skip-cert-verify: false")
        if p.get("sni"):
            lines.append(f"    sni: {q(p['sni'])}")
        if t == "hysteria2":
            lines.append("    up: \"50 Mbps\"")
            lines.append("    down: \"200 Mbps\"")
    else:  # vless / vmess
        lines.append(f"    uuid: {q(p['secret'])}")
        if t == "vmess":
            lines.append("    alterId: 0")
            lines.append("    cipher: auto")
        else:
            lines.append(f"    encryption: none")
        lines.append("    udp: true")
        if p.get("tls"):
            lines.append("    tls: true")
            if p.get("sni"):
                lines.append(f"    servername: {q(p['sni'])}")
            lines.append("    skip-cert-verify: false")
        net = p.get("net") or "tcp"
        if net in ("ws", "httpupgrade"):
            lines.append(f"    network: {net}")
            lines.append("    ws-opts:")
            lines.append(f"      path: {q(p.get('path') or '/')}")
            if p.get("sni"):
                lines.append("      headers:")
                lines.append(f"        Host: {q(p['sni'])}")
        elif net in ("grpc",):
            lines.append("    network: grpc")
            lines.append("    grpc-opts:")
            lines.append(f"      grpc-service-name: {q((p.get('path') or '').strip('/'))}")
        elif net in ("h2", "http"):
            lines.append("    network: h2")
            lines.append("    h2-opts:")
            lines.append(f"      path: {q(p.get('path') or '/')}")
            if p.get("sni"):
                lines.append("      host:")
                lines.append(f"        - {q(p['sni'])}")
    return "\n".join(lines)


def write_clash(path: Path, nodes, limit: int):
    nodes = nodes[:limit]
    names = [n["name"] for n in nodes]
    if not names:
        path.write_text("# 本轮无可用节点\n", encoding="utf-8")
        return
    head = [
        "# NODARIUM 自动生成，请勿手改",
        "mixed-port: 7890",
        "allow-lan: false",
        "bind-address: '*'",
        "mode: rule",
        "log-level: warning",
        "ipv6: false",
        "",
        "proxies:",
    ]
    body = [yaml_proxy(n) for n in nodes]
    join_list = "\n".join(f"      - {q(n)}" for n in names)
    groups = [
        "",
        "proxy-groups:",
        "  - name: \"自动选择\"",
        "    type: url-test",
        f"    url: {q(CLASH_TEST_URL)}",
        "    interval: 300",
        "    tolerance: 50",
        "    proxies:",
        join_list,
        "  - name: \"故障转移\"",
        "    type: fallback",
        f"    url: {q(CLASH_TEST_URL)}",
        "    interval: 300",
        "    proxies:",
        join_list,
        "  - name: \"手动选择\"",
        "    type: select",
        "    proxies:",
        "      - \"自动选择\"",
        "      - \"故障转移\"",
        join_list,
        "",
        "rules:",
        "  - GEOIP,CN,DIRECT",
        "  - MATCH,自动选择",
        "",
    ]
    path.write_text("\n".join(head) + "\n" + "\n".join(body) + "\n" + "\n".join(groups), encoding="utf-8")


def write_base64(path: Path, nodes, limit: int):
    links = [n["raw"] for n in nodes[:limit] if n.get("raw")]
    raw = "\n".join(links).encode("utf-8")
    path.write_text(base64.b64encode(raw).decode(), encoding="utf-8")


def write_singbox(path: Path, nodes, limit: int):
    outs = []
    for n in nodes[:limit]:
        o = {"type": n["type"], "tag": n["name"], "server": n["server"], "server_port": n["port"]}
        t = n["type"]
        if t in ("vless",):
            o["uuid"] = n["secret"]
        elif t == "vmess":
            o["uuid"] = n["secret"]
            o["security"] = "auto"
            o["alter_id"] = 0
        elif t in ("trojan", "hysteria2", "tuic"):
            o["password"] = n["secret"]
        elif t == "ss":
            o["method"] = n.get("cipher") or "aes-256-gcm"
            o["password"] = n["secret"]
        if n.get("tls") and t in ("vless", "vmess", "trojan"):
            o["tls"] = {"enabled": True, "server_name": n.get("sni") or n["server"], "insecure": False}
        net = n.get("net") or "tcp"
        if net == "ws" and t in ("vless", "vmess", "trojan"):
            o["transport"] = {"type": "ws", "path": n.get("path") or "/",
                              "headers": {"Host": n.get("sni") or n["server"]}}
        elif net == "grpc" and t in ("vless", "vmess", "trojan"):
            o["transport"] = {"type": "grpc", "service_name": (n.get("path") or "").strip("/")}
        outs.append(o)
    data = {
        "log": {"level": "warn"},
        "outbounds": [{"type": "selector", "tag": "选择", "outbounds": [o["tag"] for o in outs] + ["direct"]}] + outs
        + [{"type": "direct", "tag": "direct"}],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def write_nodes_json(path: Path, nodes, meta: dict):
    path.write_text(json.dumps(meta | {"nodes": nodes}, ensure_ascii=False, indent=1), encoding="utf-8")


def country_name(code: str) -> str:
    return COUNTRIES.get(code, code if code != "--" else "未知")
