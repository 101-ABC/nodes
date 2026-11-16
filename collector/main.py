"""NODARIUM 采集器：抓取 -> 解析 -> 去重 -> 测活 -> 生成四类产物。

用法：
    python collector/main.py            # 正常跑一轮
    python collector/main.py --dry      # 只抓取解析，不测活、不写文件
    python collector/main.py --limit 200
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import build  # noqa: E402
import parse  # noqa: E402
import probe  # noqa: E402

CST = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def load_sources():
    cfg = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    return cfg, [s for s in cfg["sources"] if s.get("enable", True)]


def gather(sources):
    """并发抓取所有源，返回 {id: text|None} 与耗时统计。"""
    result = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(12, len(sources) or 1)) as pool:
        futs = {pool.submit(fetch, s["url"]): s for s in sources}
        for fut, s in futs.items():
            pass
        for fut, s in [(f, futs[f]) for f in futs]:
            sid = s["id"]
            try:
                result[sid] = fut.result()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
                result[sid] = None
                print(f"  [FAIL] {sid:14s} {type(e).__name__}")
    return result, time.time() - t0


def collect(sources, payloads):
    """解析 + 去重，返回 nodes 列表（含 sources 集合）。"""
    by_fp = {}
    stats = []
    for s in sources:
        text = payloads.get(s["id"])
        if not text:
            stats.append({"id": s["id"], "repo": s["repo"], "ok": False, "lines": 0, "parsed": 0})
            continue
        lines = parse.split_lines(text)
        parsed = 0
        for line in lines:
            n = parse.parse_line(line)
            if not n:
                continue
            parsed += 1
            fp = n["fp"]
            if fp in by_fp:
                by_fp[fp]["srcs"].add(s["repo"])
                continue
            n["srcs"] = {s["repo"]}
            n["cats"] = {s["cat"]}
            n["country"] = parse.guess_country(n["name"])
            by_fp[fp] = n
        stats.append({"id": s["id"], "repo": s["repo"], "ok": True, "lines": len(lines), "parsed": parsed})
    return list(by_fp.values()), stats


def load_state(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def to_frontend(n, rtt, st, cfg, idx):
    country = n["country"]
    raw_name = n["name"] or f"{build.country_name(country)}-{idx:03d}"
    short = re.sub(r"[\U0001F1E6-\U0001F1FF]{2}", "", raw_name)
    short = re.sub(r"\s{2,}", " ", short).strip(" |-—·_")
    if country != "--" and short.upper().startswith(country):
        short = short[len(country):].strip(" |-—·_")
    short = short[:24] or f"{country}-{idx:03d}"
    srcs = sorted(n["srcs"])
    risks = []
    if len(srcs) == 1:
        risks.append({"lv": "hi", "t": "仅 1 个源收录，随时可能失效"})
    if rtt > 500:
        risks.append({"lv": "md", "t": f"延迟 {rtt}ms，实际体验偏差"})
    if n["port"] not in (443, 8443, 2053, 2083, 2087, 2096):
        risks.append({"lv": "lo", "t": f"非标准端口 {n['port']}，部分网络环境可能拦"})
    if not risks:
        risks.append({"lv": "lo", "t": "无明显风险标记"})

    cat = "public"
    if "airport" in n["cats"]:
        cat = "airport"
    elif len(srcs) <= 1:
        cat = "free"

    disp = f"[{rtt}ms] {country} {short}".strip()
    return {
        "id": idx,
        "fp": n["fp"],
        "name": disp,                     # 写进订阅的显示名（带延迟，Karing 里好认）
        "region": build.country_name(country),
        "city": "",
        "flag": country,
        "note": short,
        "proto": n["type"],
        "cat": cat,
        "catTxt": {"airport": "机场", "public": "公益聚合", "free": "公开免费"}[cat],
        "host": n["server"],
        "port": n["port"],
        "rtt": rtt,
        "streak": st.get("streak", 0),
        "isNew": st.get("streak", 0) <= 1,
        "tls": bool(n.get("tls")),
        "transport": n.get("net") or "tcp",
        "enc": n.get("cipher") or n.get("scy") or ("tls1.3" if n.get("tls") else "none"),
        "sni": n.get("sni") or "—",
        "path": n.get("path") or "—",
        "asn": "—",
        "org": "—",
        "ipType": "未知",
        "isCF": False,
        "first": st.get("first", now_str()[:16]),
        "lastOk": now_str()[11:16],
        "rtts": st.get("rtts", [rtt])[-5:],
        "srcs": [{"repo": r, "star": "—"} for r in srcs],
        "risk": risks[:3],
        "raw": n["raw"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="不测活、不写文件")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个原始节点（调试用）")
    args = ap.parse_args()

    cfg, sources = load_sources()
    print(f"== NODARIUM 采集器 == {now_str()}  源 {len(sources)} 个")

    print("[1/5] 抓取…")
    payloads, dt = gather(sources)
    ok_src = sum(1 for v in payloads.values() if v)
    print(f"      完成 {ok_src}/{len(sources)} 个源，用时 {dt:.1f}s")

    print("[2/5] 解析去重…")
    nodes, stats = collect(sources, payloads)
    for s in stats:
        flag = "OK " if s["ok"] else "ERR"
        print(f"      [{flag}] {s['id']:14s} 行 {s['lines']:5d} 解析 {s['parsed']:5d}  {s['repo']}")
    print(f"      去重后 {len(nodes)} 个唯一节点")

    if args.limit:
        nodes = nodes[: args.limit]

    if args.dry:
        print("[dry] 跳过测活与写盘")
        return

    print("[3/5] TCP 测活…")
    pcfg = cfg.get("probe", {})
    t0 = time.time()
    rtts = probe.probe_all(nodes, timeout=pcfg.get("timeout", 2.0),
                           concurrency=pcfg.get("concurrency", 512))
    alive = [(n, r) for n, r in zip(nodes, rtts) if r]
    print(f"      存活 {len(alive)}/{len(nodes)}，用时 {time.time()-t0:.1f}s")

    print("[4/5] 更新存活历史…")
    state_path = ROOT / "data" / "state.json"
    state = load_state(state_path)
    ttl = timedelta(hours=pcfg.get("state_ttl_hours", 72))
    cutoff = datetime.now(CST) - ttl
    fresh = {}
    for n, rtt in alive:
        old = state.get(n["fp"], {})
        streak = int(old.get("streak", 0)) + 1
        hist = (old.get("rtts") or [])[-4:] + [rtt]
        fresh[n["fp"]] = {
            "first": old.get("first") or now_str()[:16],
            "streak": streak,
            "rtts": hist[-5:],
            "last": now_str(),
        }
    kept = 0
    for fp, v in state.items():
        if fp in fresh:
            continue
        try:
            last = datetime.strptime(v.get("last", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
        except ValueError:
            continue
        if last >= cutoff:
            fresh[fp] = dict(v, streak=0)   # 本轮掉线，存活链清零但不立即删
            kept += 1
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
    print(f"      历史 {len(fresh)} 条（其中本轮掉线保留 {kept} 条）")

    print("[5/5] 生成产物…")
    alive.sort(key=lambda x: (-len(x[0]["srcs"]), x[1]))
    front = [to_frontend(n, r, fresh.get(n["fp"], {}), cfg, i + 1) for i, (n, r) in enumerate(alive)]

    best_min = pcfg.get("best_min_streak", 6)
    best = [f for f in front if f["streak"] >= best_min][: pcfg.get("best_limit", 50)]
    if len(best) < 10:                      # 冷启动兜底：历史不足时取最快的
        best = front[: min(50, len(front))]

    # 组装订阅用的节点（name 换成带延迟的显示名）
    for f in front:
        f["raw"] = f["raw"]
    sub_nodes = []
    for f in front:
        sub_nodes.append({
            "name": f["name"], "type": f["proto"], "server": f["host"], "port": f["port"],
            "secret": next((x[0]["secret"] for x in alive if x[0]["fp"] == f["fp"]), ""),
            "cipher": f["enc"], "net": f["transport"], "path": f["path"], "sni": f["sni"],
            "tls": f["tls"], "raw": f["raw"],
        })
    best_fps = {f["fp"] for f in best}
    best_nodes = [x for x, f in zip(sub_nodes, front) if f["fp"] in best_fps]

    sub = ROOT / "sub"
    sub.mkdir(parents=True, exist_ok=True)
    data = ROOT / "data"
    data.mkdir(parents=True, exist_ok=True)

    build.write_clash(sub / "clash.yaml", sub_nodes, pcfg.get("full_limit", 500))
    build.write_clash(sub / "clash-best.yaml", best_nodes, pcfg.get("best_limit", 50))
    build.write_base64(sub / "base64.txt", sub_nodes, pcfg.get("full_limit", 500))
    build.write_base64(sub / "base64-best.txt", best_nodes, pcfg.get("best_limit", 50))
    build.write_singbox(sub / "singbox.json", sub_nodes, pcfg.get("full_limit", 500))
    build.write_singbox(sub / "singbox-best.json", best_nodes, pcfg.get("best_limit", 50))

    meta = {
        "updated": now_str(),
        "stats": {"full": len(sub_nodes), "best": len(best_nodes),
                  "avg": round(sum(x["rtt"] for x in front) / max(1, len(front))),
                  "added": sum(1 for f in front if f["isNew"])},
        "sources": [{"repo": s["repo"], "id": s["id"], "ok": s["ok"], "lines": s["lines"],
                     "parsed": s["parsed"], "contrib": s["parsed"]} for s in stats],
    }
    # ---- 页面用数据：sources / log / srcdrop 与前端结构对齐 ----
    page_sources = []
    page_srcdrop = []
    for s in stats:
        page_sources.append({
            "repo": s["repo"], "star": "—",
            "kind": "抓取正常" if s["ok"] else "抓取失败",
            "desc": (f"本轮解析 {s['parsed']} 行" if s["ok"] else "本轮抓取失败，检查仓库路径或网络"),
            "contrib": s["parsed"],
        })
        page_srcdrop.append({"repo": s["repo"], "add": s["parsed"],
                             "drop": max(0, s["lines"] - s["parsed"])})
    page_sources.sort(key=lambda x: -x["contrib"])

    log_path = data / "log.json"
    try:
        log_hist = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log_hist = []
    log_hist.insert(0, {"t": now_str()[11:], "add": meta["stats"]["added"],
                        "drop": max(0, len(nodes) - len(sub_nodes)),
                        "keep": len(sub_nodes)})
    log_hist = log_hist[:10]
    log_path.write_text(json.dumps(log_hist, ensure_ascii=False), encoding="utf-8")

    payload = dict(meta)
    payload.update({"sources": page_sources, "log": log_hist, "srcdrop": page_srcdrop})
    build.write_nodes_json(data / "nodes.json", front, payload)
    (data / "nodes.js").write_text(
        "window.__NODES__ = " + json.dumps(payload | {"nodes": front}, ensure_ascii=False) + ";",
        encoding="utf-8")

    # 页面：模板替换用户名
    tpl = ROOT / "web" / "index.html"
    if tpl.exists():
        user = cfg.get("output", {}).get("user", "USERNAME")
        base = cfg.get("output", {}).get("base_url", f"https://{user}.github.io/nodes")
        html = tpl.read_text(encoding="utf-8")
        html = html.replace("https://USERNAME.github.io/nodes", base).replace("USERNAME", user)
        (ROOT / "index.html").write_text(html, encoding="utf-8")
        print(f"      index.html 已生成（{user}）")

    print(f"完成：全量 {len(sub_nodes)} 条 / 精选 {len(best_nodes)} 条 / 平均 {meta['stats']['avg']}ms")


if __name__ == "__main__":
    main()
