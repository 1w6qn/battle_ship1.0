"""Host the built Vue shell (`frontend/dist`) with SPA deep-link fallback.

Ticket #21 owns the wiring, not the switch: `FRONTEND_MODE` defaults to
`legacy`, so the migration window keeps serving the old template until #20
flips it. In `spa` mode:

* `/assets/<hashed>` is served from `dist/assets` with a one-year immutable
  cache (the filename already carries the content hash);
* `/` and any non-reserved deep link return `dist/index.html` (no-cache) with
  `X-Frontend-Build` derived from `.vite/manifest.json`;
* API, Socket.IO and legacy `/static` paths are never swallowed;
* a missing build fails startup instead of silently serving the old page.

No extra server process: the built bundle is mounted on the existing ASGI app.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

#: First path segments that must keep their existing owner. The catch-all only
#: runs after all API routers, so this list is a safety net for unmatched paths.
RESERVED_PREFIXES: frozenset[str] = frozenset(
    {
        "api",
        "assets",
        "static",
        "socket.io",
        "health",
        "healthz",
        "metrics",
        "docs",
        "openapi.json",
        "login",
        "register",
        "logout",
        "legacy",
        "admin",
        "user_stats",
    }
)

IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
INDEX_CACHE = "no-cache"
BUILD_ID_HEADER = "X-Frontend-Build"


class HashedAssets(StaticFiles):
    """Static files whose names already contain a content hash."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers.setdefault("cache-control", IMMUTABLE_CACHE)
        return response


def frontend_build_id(dist: Path) -> str:
    """Stable id for the deployed bundle: hash of the Vite manifest bytes."""

    manifest = dist / ".vite" / "manifest.json"
    if not manifest.is_file():
        return ""
    return hashlib.sha256(manifest.read_bytes()).hexdigest()[:16]


def install(app: FastAPI, dist: str | Path) -> str:
    """Mount the SPA on `app`; returns the build id (also sent as a header)."""

    dist = Path(dist).resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(
            f"FRONTEND_MODE=spa 但找不到构建产物: {index}。"
            "先运行 pnpm build（或把 FRONTEND_DIST 指向 dist 目录）。"
        )

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            HashedAssets(directory=str(assets_dir)),
            name="frontend-assets",
        )

    build_id = frontend_build_id(dist)
    router = APIRouter(tags=["frontend"], include_in_schema=False)

    def index_response() -> FileResponse:
        headers = {"cache-control": INDEX_CACHE}
        if build_id:
            headers[BUILD_ID_HEADER] = build_id
        return FileResponse(index, media_type="text/html", headers=headers)

    @router.get("/")
    def spa_index() -> FileResponse:
        return index_response()

    @router.get("/{spa_path:path}")
    def spa_fallback(spa_path: str) -> FileResponse:
        first = spa_path.split("/", 1)[0]
        if first in RESERVED_PREFIXES:
            raise HTTPException(status_code=404)

        candidate = (dist / spa_path).resolve()
        try:
            inside = candidate.is_relative_to(dist)
        except ValueError:  # pragma: no cover - different drives on Windows
            inside = False
        if inside and candidate.is_file():
            return FileResponse(candidate)

        # File-like paths should 404 rather than render the shell; client routes
        # (including /profile/123 id segments) fall back to index.html.
        if Path(spa_path).suffix:
            raise HTTPException(status_code=404)
        return index_response()

    app.include_router(router)
    return build_id


__all__ = ["install", "frontend_build_id", "RESERVED_PREFIXES", "HashedAssets"]
