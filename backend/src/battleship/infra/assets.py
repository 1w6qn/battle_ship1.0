"""静态资产定位与内容哈希清单。

迁移窗口内要同时托管旧栈的 `static/` + `templates/`（旧前端照常跑）和
未来 `frontend/dist` 的构建产物。路径发现只做一件事：从模块位置向上找到
同时有 `templates/index.html` 或 `static/` 的仓库根。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


def _looks_like_repo_root(path: Path) -> bool:
    return (path / "templates" / "index.html").is_file() or (path / "static").is_dir()


@dataclass(frozen=True)
class AssetPaths:
    root: Path
    static_dir: Path
    templates_dir: Path
    frontend_dist: Path

    @classmethod
    def discover(cls, root: str | Path | None = None) -> "AssetPaths":
        candidates: list[Path] = []
        if root is not None:
            candidates.append(Path(root))
        env_root = os.environ.get("BATTLESHIP_ROOT")
        if env_root:
            candidates.append(Path(env_root))

        here = Path(__file__).resolve()
        candidates.extend(here.parents)
        candidates.append(Path.cwd())

        for candidate in candidates:
            resolved = candidate.resolve()
            if _looks_like_repo_root(resolved):
                return cls(
                    root=resolved,
                    static_dir=resolved / "static",
                    templates_dir=resolved / "templates",
                    frontend_dist=resolved / "frontend" / "dist",
                )

        # 没有仓库根时退回当前目录：服务仍能启动，健康检查会指出静态资源缺失。
        fallback = Path.cwd().resolve()
        return cls(
            root=fallback,
            static_dir=fallback / "static",
            templates_dir=fallback / "templates",
            frontend_dist=fallback / "frontend" / "dist",
        )

    def asset_version(self, rel_path: str) -> str:
        """旧模板的 `?v=`：优先内容哈希清单，回退 mtime（旧行为）。"""

        manifest = self.load_manifest()
        entry = manifest.get(rel_path) if manifest else None
        if isinstance(entry, dict) and entry.get("file"):
            return str(entry.get("hash") or entry.get("file"))
        if isinstance(entry, str):
            return entry
        target = self.static_dir / rel_path
        try:
            return str(int(target.stat().st_mtime))
        except OSError:
            return "0"

    def load_manifest(self) -> dict:
        for candidate in (
            self.frontend_dist / ".vite" / "manifest.json",
            self.frontend_dist / "manifest.json",
        ):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return data
        return {}

    def content_hash(self, rel_path: str) -> str | None:
        target = self.static_dir / rel_path
        try:
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return None

    def safe_join(self, rel_path: str) -> Path | None:
        target = (self.static_dir / rel_path).resolve()
        try:
            target.relative_to(self.static_dir.resolve())
        except ValueError:
            return None
        return target
