# 重写落地（Phase 5，2026-10-20）

> 票 #30 的交付说明。旧实现已从仓库删除；这里是新架构的"从哪看、怎么跑、门禁是什么、
> 出问题怎么回滚、还剩什么"的唯一入口。历史文档保留在 `docs/`，但只作考古。

---

## 1. 架构

```
浏览器（Vue 3 SPA, frontend/dist）
   │  socket.io（对局/大厅/观战/聊天）        HTTP（账号/排行/回放/公告/健康）
   ▼                                            ▼
uvicorn ── FastAPI app（backend/src/battleship/main.py）
   │              │
   │              ├── realtime/  python-socketio handler（61 入站 / 89 出站）
   │              ├── http/      REST 路由 + SQLAlchemy 会话 + SPA/静态托管
   │              ├── services/  用例编排（结算=单事务）
   │              ├── domain/    纯规则（无框架、无数据库）
   │              └── repositories/  唯一 SQL 位置
   ▼
SQLite（WAL，Alembic 版本化，21 张业务表 + 索引 + 视图）
```

- **运行时只有一份应用**：`uvicorn battleship.main:app` 以字符串目标导入，避免
  "`__main__` 与模块各建一份"的历史双实例坑。
- **前后端同源**：Vite 构建产物由同一个 ASGI 应用托管（`/assets` 内容哈希 + 一年
  immutable，页面 `no-cache`），没有第二个静态服务器。
- **没有事件循环补丁**：后台任务（掉线宽限、连锁/回合超时）是 asyncio 定时任务，
  房间销毁时取消。
- **只有一个栈**：`/legacy`、`BACKEND_STACK`、`FRONTEND_MODE=legacy`、
  `ARENA_SCREENS_*` 全部移除；残留 env 启动即失败（D30）。

---

## 2. 目录

```
backend/
  pyproject.toml           依赖（fastapi/uvicorn/python-socketio/pydantic/sqlalchemy/alembic/werkzeug）
  alembic.ini  migrations/ 首个 revision = 0001_initial_schema
  src/battleship/
    main.py                组合根：配置 → 日志 → 路由 → SPA → Socket.IO ASGI
    config.py              Pydantic Settings；SECRET_KEY 必填，缺失即失败
    contracts/             事件清单、Pydantic 模型、JSON Schema 导出
    domain/                对局、布船、魔法/连锁、AI、反作弊、匹配、成长、社交、观战
    services/              用例编排与事务边界
    repositories/           SQLAlchemy 模型、UoW、迁移与 schema 校验
    realtime/              Socket.IO server/handlers/emitter/identity/timers
    http/                  路由、会话、错误体、SPA 托管、限流
    infra/                 配置落地、结构化日志、指标、健康检查、限流
frontend/
  public/card_faces/       48 张卡面（Vite 构建期打包成内容哈希资产）
  src/screens/             11 屏（start/placement/rps/game/lobby/leaderboard/profile/
                           settings/replay/spectate/game-over）
  src/stores/              Pinia（game/home/lobby/match/placement/rps/result/replay/settings/...）
  src/realtime/, src/socket/   typed socket 客户端与生成的事件类型
  src/router/index.ts      11 条冻结路由
  src/styles/              tokens/base/components/screens
ops/
  build.py                 后端安装 + 前端构建 + 产物校验（48 卡面）
  migrate.py               Alembic + 备份 + 校验（systemd ExecStartPre）
  healthcheck.py           /health 轮询
  rollback.py              5 分钟回滚（备份恢复 + 切 commit/release + 健康检查）
  run_stack.py             本地一键起全栈（fail-fast）
  systemd/battleship.service, deploy.env.example, README.md
static/avatars/            唯一的运行期用户数据（头像，冻结 URL /static/avatars/...）
docs/, docs/adr/           设计/决策；历史文档保留
```

被删除（Phase 5）：旧后端全部根模块与启动脚本、旧 `requirements.txt`、`templates/`、
`static/` 下的旧前端资产（`static/card_faces` 已迁入 `frontend/public`）、仓内
`tests/` 与 `tools/`（仓外 `battleship-verify` 有对照副本）、以及重复的根
`changelog.py`（公告现在只有后端一份真源）。

---

## 3. 契约

**HTTP**：49 条冻结客户端路由（`backend/src/battleship/http/routes.py` 的
`LEGACY_ROUTES`，名字是历史资产）+ 新栈附加的 health/metrics/contracts/docs +
SPA 入口（`GET /` 与 catch-all）。`/legacy` 不再注册（404）；`/lobby`、
`/leaderboard` 等由 SPA catch-all 服务。

**Socket.IO**：入站 61（47 普通 + 14 调试，调试事件受 `ENABLE_TEST_EVENTS` 门控）；
出站 89（82 字面量 + 7 个参数化：`friend_request/accepted/invite/message`、
`recent_opponent`、`spectate_joined/left`）。ack 形如 `43<ackId><JSON>`，没有长度位。

**身份**：匹配房座位 key = 入队 sid；真实 user_id 在 `Player.user_id`；客户端用服务端
下发的 `player_id`。观战只进 `spectate:<room_id>`，不写进 `room.players`。

**错误体**：已录制路由保持旧形状 `{"error": "..."}`（D19）；`POST /login(JSON)`、
`POST /register(JSON)`、`GET /api/profile(401)`、`/api/change_password` 仍是结构化
`{"error":{code,message,field}}`（D26，历史遗留，未收录在录制样本里）。

**数据**：SQLite/WAL；Alembic 版本表 `alembic_version`；结算（对局 + 回放 + 用户统计/
段位/经验）在同一事务提交（D12）。迁移前 SQLite 在线备份，失败自动恢复。

**前端**：11 条冻结路由；`data-testid` 是门禁契约；没有 `window.gameState`；
测试钩子只在 test 构建注入；卡面从 `frontend/public/card_faces` 在构建期 import，
缺图返回 `null`（卡片退化无美术层）。

**契约产物**：`contracts/export_schema.py` 可导出 JSON Schema 与
`frontend/src/socket/events.gen.ts`；`frontend/scripts/check-contract.mjs` 在
`pnpm build` 前校验 `CONTRACT_SCHEMA_HASH`。

---

## 4. 门禁

测试资产不入仓（D4）；门禁都对**集成分支工作区**跑（D7）。

| 门禁 | 命令 | 覆盖 |
| --- | --- | --- |
| Phase 5 收尾 | `pytest cases/30-cleanup` | 旧文件/旧导入消失、单栈冷启动、路由表、48 卡面、ops dry-run、文档与公告 |
| 后端 | `pytest cases/4`–`19` | 组合根、数据层、鉴权、房间、布船、对局、魔法、连锁、AI、大厅、成长、排位、观战、回放、HTTP |
| 逐屏 | `pytest cases/21`–`28`、`31`、`33` | 壳与每屏静态/行为契约 |
| 浏览器 | `tools/web/run_all.py` | 22 个 `data-testid` 工具 + D33 截图指纹基线 |

`SKIP` 不算绿，当前允许的归因只有 rank-help / room / collection。

Phase 5 记录的证据（2026-10-20，impl/30-cleanup @ d907b1e + 本票改动）：

- `cases/30-cleanup`：**229 passed**（含真实 Chromium 冷启动冒烟、`/legacy` 404、
  旧 cookie 一次性重登提示、48 张 webp 进 manifest/资产、ops dry-run 与真实迁移备份）；
- 六屏回归 `cases/21`–`28`、`31`、`33`：全绿（21:11 / 22:8 / 23:10 / 24:8 /
  25:12 / 26:10 / 27:10 / 28:13 / 31:20 / 33:5）；
- 后端抽样 `cases/4`、`6`、`7`、`9`、`14`、`17`、`18`、`19`：全绿
  （27 / 26 / 16 / 37 / 26 / 39 / 21 / 25）；
- `tools/web/run_all.py`：**20 PASS / 2 SKIP / 0 FAIL**；SKIP 为 `rank-help`
  （help 屏未迁移）与 `cplus-screens`（room/collection 归因），
  `cplus-path` 双浏览器全链路通过。
- 公告是首页可见内容，改了它就让 `layout` / `changelog` / `wallpaper` 的截图基线
  发生**真实**变化；按 D33 只重录这四处指纹基线（home、layout-start、changelog、
  wallpaper-settings），其余屏未动。

**已退役的门禁**：`cases/20-gate` 的"迁移窗口"断言（旧页面仍 200、双栈并行；
`test_migration_window.py` 已显式 skip）随旧实现删除而失效；`cases/3-baseline`
的旧栈 pytest 只对旧栈工作树有效。它们的价值已由上面四类门禁接管，不再作为红线。

---

## 5. 回滚

`ops/rollback.py` 的固定顺序：校验备份（`PRAGMA integrity_check`）与目标 commit/
release → 停服 → 当前库安全副本 → 恢复备份 → 切 commit（`git checkout --detach`）
或 release 软链 → 重建前端 → 启动并轮询 `/health`。预算 5 分钟，超时打印 WARNING。

- 部署顺序：`ops/build.py` → `ops/migrate.py` → `systemctl restart battleship` →
  `ops/healthcheck.py`。
- systemd：`ops/systemd/battleship.service`（uvicorn，`EnvironmentFile`，
  `ExecStartPre` 跑迁移）。
- 跨 Phase 5 回滚（回到旧栈）必须保留一个旧 release 目录并用 `--release-dir`：
  旧提交里没有新栈的构建脚本。runbook 见 `ops/README.md`。
- 失败路径：脚本以 3 退出并打印"安全副本 + 上一个 commit + 启动命令"。

---

## 6. 残余与已知偏差

1. **动态壁纸**：设置屏只有入口与本机可用性检查；应用/播放从未迁进新界面。
   `/legacy` 删除后，设置屏的"打开壁纸库"入口改为只解释"暂未迁移"，不再跳转。
   这是 Phase 5 的已知功能缺口，不是新引入的回归。
2. **帮助/段位说明屏**：11 条冻结路由里没有 help；卡面图鉴（collection）与房间（room）
   仍是 `tools/web` 的归因 SKIP。
3. **两份 `field_magic_name`**（domain/magic/rules.py 与 domain/room/models.py）：
   输出一致但违反"单一实现"，D24 交最终 code-review 收敛。
4. **错误体不统一**：D19（录制路由旧形状）与 D26（4 条结构化）并存，按契约风险保留。
5. **观战/回放历史差异**：D31 清单（观战结束不自动跳大厅、回放缺 phase/round/chain
   时间线、回放卡面只显示卡名）仍未实现；属于已知偏差。
6. **旧录制基线**：`fixtures/contract` 的对局录制没有连锁帧，AI 样本对 RNG 敏感，
   掉线宽限是墙钟；`cases/20-gate` 的逐事件比对不再是 Phase 5 红线。
7. **头像仍放在 `static/avatars`**：这是玩家数据不是旧前端资产，保留同一冻结 URL，
   避免历史名片图片 404；其余 `static/` 内容已删除。
8. **卡面不做 public 目录的二次拷贝**：`frontend/vite.config.ts` 关闭 `publicDir`，
   由 `import.meta.glob` 产出内容哈希资产；`pnpm dev` 不再是"起全栈"的入口，
   本地统一走 `ops/run_stack.py`。
9. **玩家公告只有一条**："网站换了新架构，第一次进来可能要重新登录一次"；
   旧 cookie 的提示由 SPA 入口按一次性语义注入（不依赖已删除的模板）。