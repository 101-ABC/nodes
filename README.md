# NODARIUM · 节点订阅站

一个纯静态的免费节点聚合站：每 3 小时自动抓取高星 GitHub 源 → 解析去重 → TCP 测活 → 生成 Clash / Base64 / sing-box 三种订阅，页面即时展示。

- 前端：单文件 `web/index.html`（构建时生成根目录 `index.html`），无后端、无 CDN 依赖
- 采集器：`collector/*.py`，**只用 Python 标准库**，无需 pip 安装任何东西
- 托管：GitHub Actions 定时跑 + GitHub Pages 静态托管，**零费用**

---

## 目录结构

```
.
├─ index.html                 # 构建产物（由 web/index.html 替换 USERNAME 后生成）
├─ web/index.html             # 页面模板（改这里，不要改根目录的）
├─ collector/
│  ├─ sources.json            # 数据源清单 + 参数（唯一需要你改的配置）
│  ├─ parse.py                # 订阅文本 → 标准节点（vmess/vless/trojan/ss/hy2/tuic）
│  ├─ probe.py                # asyncio 并发 TCP 测活
│  ├─ build.py                # 生成 clash/base64/singbox/nodes.json
│  ├─ main.py                 # 主流程
│  └─ report.py               # Actions 摘要
├─ sub/                       # 订阅产物（自动生成）
│  ├─ clash.yaml / clash-best.yaml
│  ├─ base64.txt / base64-best.txt
│  └─ singbox.json / singbox-best.json
├─ data/                      # 页面数据 + 存活历史（自动生成）
└─ .github/workflows/update.yml
```

---

## 部署（一次就好）

1. 在 GitHub 新建**公开**仓库，名字随意（下面以 `nodes` 为例）。
2. 把本目录全部文件推上去。
3. 打开 `collector/sources.json`，把 `output.user` 改成你的 GitHub 用户名：

   ```json
   "output": {
     "user": "你的用户名",
     "base_url": "https://你的用户名.github.io/nodes"
   }
   ```

4. 仓库 → **Settings → Pages** → Source 选 **Deploy from a branch** → 分支 `main`、目录 `/ (root)` → Save。
5. 仓库 → **Actions** → 左侧 `sync-nodes` → **Run workflow** 手动跑一次，等 2–5 分钟。
6. 打开 `https://你的用户名.github.io/nodes/`。

订阅地址（生成后）：

| 用途 | 地址 |
|---|---|
| Karing / Clash Verge / Mihomo Party | `.../sub/clash.yaml` |
| Karing 精选（推荐日常） | `.../sub/clash-best.yaml` |
| 小火箭 / v2rayN / v2rayNG | `.../sub/base64.txt` |
| sing-box | `.../sub/singbox.json` |

---

## 本地调试

```bash
# 只抓取解析，不测活不写盘（看源还活着没）
python collector/main.py --dry

# 只处理前 200 个节点，快速验证
python collector/main.py --limit 200
```

> 本机在墙内时 `raw.githubusercontent.com` 直连会全部失败（URLError），这是网络问题不是代码问题。
> 采集器在 GitHub Actions（海外机房）上跑才通。

---

## 关键参数（`collector/sources.json`）

| 字段 | 含义 | 默认 |
|---|---|---|
| `interval_hours` | 同步间隔（同时改 `update.yml` 的 cron） | 3 |
| `probe.timeout` | TCP 握手超时（秒） | 2.0 |
| `probe.concurrency` | 并发探测数 | 512 |
| `probe.best_min_streak` | 进「精选」所需的连续存活轮数 | 6 |
| `probe.best_limit` / `full_limit` | 精选 / 全量的条数上限 | 50 / 500 |
| `probe.state_ttl_hours` | 掉线节点在历史里保留多久 | 72 |
| `sources[].enable` | 单个源开关 | true |

---

## 判定逻辑

- **去重**：`sha1(协议|服务器|端口|密钥)`，同一节点被 10 个源收录只留一条
- **测活**：TCP 连接 `server:port` 成功即算存活，同时记录 RTT
- **连续存活轮数（streak）**：连续多少轮都测活成功，掉线一次清零
- **精选**：`streak ≥ 6`（约 18 小时）的节点，最多 50 条
- **失效处理**：不保留、不进订阅，直接从产物中消失

> 延迟是 **GitHub 海外机房**测出来的，只能当参考。真实可用性以你手机 Karing 里的内置测速为准。

---

## 常见问题

**Q：Actions 跑完但页面没变？**
Pages 构建有延迟，等 1–2 分钟刷新；或看 Actions 里有没有红色失败。

**Q：某天源全挂 / 节点变很少？**
看 Actions 摘要里的「失败源」列表。把 `sources.json` 里那个源的 `enable` 改 `false`，或换新仓库地址。

**Q：会不会被 GitHub 暂停？**
仓库连续 60 天没有任何提交才会暂停。每 3 小时一次自动提交，不会触发。

**Q：花钱吗？**
公开仓库的 Actions 分钟数不计费，Pages 免费额度 100 GB/月，这个站用量不到 1%。

---

## 免责

节点全部来自公开仓库，本站只做聚合与连通性探测，不存储、不代理任何流量。
免费公共节点安全性未知，不要用于登录银行、支付等高价值账号。
