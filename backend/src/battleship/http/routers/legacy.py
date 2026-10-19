"""迁移窗口：旧 SPA 页面入口与静态资源由新后端托管。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ...legacy.render import render_legacy_index

router = APIRouter(tags=["legacy"], include_in_schema=False)


def _render(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    assets = request.app.state.assets
    template = assets.templates_dir / "index.html"
    if not template.is_file():
        raise HTTPException(status_code=503, detail="旧页面模板不存在（迁移窗口内需要 templates/index.html）")
    body = render_legacy_index(
        template,
        username=None,
        asset_v=assets.asset_version,
        arena_mode=settings.arena_screens_mode,
        arena_screen_list=settings.arena_screen_list,
    )
    return HTMLResponse(body)


@router.get("/", response_class=HTMLResponse)
def legacy_index(request: Request) -> HTMLResponse:
    return _render(request)


@router.get("/legacy", response_class=HTMLResponse)
@router.get("/legacy/{path:path}", response_class=HTMLResponse)
def legacy_spa(request: Request, path: str = "") -> HTMLResponse:
    return _render(request)


# 旧栈里这些路径都是 render_template('index.html')；窗口期保持同一入口。
for _page in ("login", "register", "logout", "leaderboard"):
    router.add_api_route(
        f"/{_page}",
        legacy_index,
        methods=["GET"],
        response_class=HTMLResponse,
        include_in_schema=False,
    )
