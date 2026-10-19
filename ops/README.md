# ops/

Deployment helpers (planned): build, migrate, systemd unit, health check, rollback.
Scripts are added with the rewrite phases.

## 仓外契约门禁（P0，票 #2）

录制器、回放比对器、样本与归一化说明都在仓外
`D:/develop/battleship-verify`（spec 的测试资产策略：仓内不放测试/夹具）。
仓内只留这条运行指引。

```powershell
# 一键：每局起一个隔离旧栈（固定随机种子 + 全新 SQLite），录制、回放、再回放一次
D:/develop/battleship-verify/.venv/Scripts/python.exe `
  D:/develop/battleship-verify/tools/run_gate.py `
  --legacy-worktree D:/develop/battle_ship1.0/.agents/worktrees/refactor `
  --repeat 2

# 只对任意候选后端回放（退出码即门禁）
D:/develop/battleship-verify/.venv/Scripts/python.exe `
  D:/develop/battleship-verify/tools/verify.py replay --target http://127.0.0.1:5401
```

会话矩阵、归一化规则与已知边界见
`D:/develop/battleship-verify/notes/CONTRACT_NORMALIZATION.md`。
