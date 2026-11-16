"""把本轮结果整理成 GitHub Actions 摘要（Markdown）。失败时不报错，避免影响主流程。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    p = ROOT / "data" / "nodes.json"
    print("### 本轮结果")
    if not p.exists():
        print("- 未生成 data/nodes.json，请查看任务日志")
        return
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("- data/nodes.json 解析失败")
        return

    s = d.get("stats", {})
    print(f"- 在役节点：**{s.get('full', 0)}** 条")
    print(f"- 精选节点：**{s.get('best', 0)}** 条")
    print(f"- 平均延迟：{s.get('avg', 0)} ms（数据中心测得）")
    print(f"- 更新时间：{d.get('updated', '—')}")

    srcs = d.get("sources", [])
    ok = [x for x in srcs if x.get("kind") == "抓取正常"]
    bad = [x for x in srcs if x.get("kind") != "抓取正常"]
    print(f"- 源正常：{len(ok)} 个 / 失败：{len(bad)} 个")
    if bad:
        print("- 失败源：" + "、".join(x.get("repo", "?") for x in bad))


if __name__ == "__main__":
    main()
