"""Host the built Vue shell (`frontend/dist`) with SPA deep-link fallback.

Phase 5 has exactly one frontend: the built bundle mounted on the existing ASGI
app (no extra server process). Contract:

* `/assets/<hashed>` is served from `dist/assets` with a one-year immutable
  cache (the filename already carries the content hash);
* `/` and any client deep link return `dist/index.html` (no-cache) with
  `X-Frontend-Build` derived from `.vite/manifest.json`;
* API, Socket.IO, avatars and any other reserved prefix are never swallowed;
* a missing build fails startup instead of silently serving nothing;
* a browser still carrying a cookie signed by the deleted stack gets the
  one-time re-login notice injected into the shell (migration-window semantics,
  kept because the changelog is behind a click). The notice is rendered exactly
  once: the stale cookie is replaced with a signed empty session in the same
  response.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..session import (
    read_session,
    session_cookie_invalid,
    write_session,
)

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

#: Player-facing one-time notice when a cookie from the deleted stack is rejected.
RE_LOGIN_NOTICE = "登录状态已更新，请重新登录一次。"

_NOTICE_HTML = (
    '<div data-testid="relogin-notice" role="status" style="position:relative;'
    "z-index:9999;padding:10px 16px;background:#312a52;color:#f4f1ff;"
    'font:14px/1.5 system-ui,-apple-system,\"Segoe UI\",sans-serif;text-align:center">'
    f"{RE_LOGIN_NOTICE}</div>"
)


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


def _index_body(dist: Path, request: Request) -> tuple[str, bool]:
    """Return (HTML, replaced_stale_cookie)."""

    html = (dist / "index.html").read_text(encoding="utf-8")
    if not session_cookie_invalid(request):
        return html, False

    marker = "<body>"
    if marker in html:
        html = html.replace(marker, marker + _NOTICE_HTML, 1)
    else:  # defensive: still show the notice for a hand-written index.html
        html = _NOTICE_HTML + html
    return html, True


def _index_response(dist: Path, build_id: str, request: Request) -> HTMLResponse:
    body, stale_cookie = _index_body(dist, request)
    headers = {"cache-control": INDEX_CACHE}
    if build_id:
        headers[BUILD_ID_HEADER] = build_id
    response = HTMLResponse(body, headers=headers)
    if stale_cookie:
        # Replace the unreadable legacy cookie immediately so the notice is
        # shown exactly once (the player still has to log in again).
        write_session(response, request, read_session(request))
    return response


def install(app: FastAPI, dist: str | Path) -> str:
    """Mount the SPA on `app`; returns the build id (also sent as a header)."""

    dist = Path(dist).resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(
            f"找不到前端构建产物: {index}。"
            "先运行 ops/build.py 或 pnpm build（或把 FRONTEND_DIST 指向 dist 目录）。"
        )

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            HashedAssets(directory=str(assets_dir)),
            name="frontend-assets",
        )

    build_id = frontend_build_id(dist)
    app.state.frontend_dist = dist
    app.state.frontend_build_id = build_id
    router = APIRouter(tags=["frontend"], include_in_schema=False)

    @router.get("/")
    def spa_index(request: Request) -> HTMLResponse:
        return _index_response(dist, build_id, request)

    @router.get("/{spa_path:path}")
    def spa_fallback(spa_path: str, request: Request) -> HTMLResponse:
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
        return _index_response(dist, build_id, request)

    app.include_router(router)
    return build_id


__all__ = [
    "install",
    "frontend_build_id",
    "RESERVED_PREFIXES",
    "HashedAssets",
    "RE_LOGIN_NOTICE",
]
