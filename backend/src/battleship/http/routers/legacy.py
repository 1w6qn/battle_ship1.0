"""迁移窗口：旧 SPA 页面入口与静态资源由新后端托管。

Session/flash 说明：旧前端用 fetch 提交表单后读取返回 HTML 里的
#flash-toast 来展示服务端原因。这里仍然由服务端渲染这个节点，cookie 是
签名会话（见 http/session.py），读一次 flash 就把它从 cookie 里清掉。

/login、/register、/logout 由 http/routers/auth.py 负责（它们要读写会话），
这里只保留纯页面入口。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ...legacy.render import render_legacy_index
from ..session import pop_flashes, read_session, session_username, write_session

router = APIRouter(tags=["legacy"], include_in_schema=False)


def render_legacy_page(request: Request,
                       messages: list[tuple[str, str]] | None = None) -> HTMLResponse:
    settings = request.app.state.settings
    assets = request.app.state.assets
    template = assets.templates_dir / "index.html"
    if not template.is_file():
        raise HTTPException(status_code=503, detail="旧页面模板不存在（迁移窗口内需要 templates/index.html）")

    session_data = read_session(request)
    flashes = messages
    if flashes is None:
        flashes = pop_flashes(session_data)
    body = render_legacy_index(
        template,
        username=session_username(session_data),
        asset_v=assets.asset_version,
        arena_mode=settings.arena_screens_mode,
        arena_screen_list=settings.arena_screen_list,
        messages=flashes,
    )
    response = HTMLResponse(body)
    if flashes:
        # The flash was consumed; persist the session without it.
        write_session(response, request, session_data)
    return response


def _render(request: Request) -> HTMLResponse:
    return render_legacy_page(request)


@router.get("/", response_class=HTMLResponse)
def legacy_index(request: Request) -> HTMLResponse:
    return _render(request)


@router.get("/legacy", response_class=HTMLResponse)
@router.get("/legacy/{path:path}", response_class=HTMLResponse)
def legacy_spa(request: Request, path: str = "") -> HTMLResponse:
    return _render(request)


# 旧栈里这些路径都是 render_template('index.html')；窗口期保持同一入口。
# /lobby 在旧栈里由 server.py 单独注册，但渲染的是同一份模板。
for _page in ("leaderboard", "lobby"):
    router.add_api_route(
        f"/{_page}",
        legacy_index,
        methods=["GET"],
        response_class=HTMLResponse,
        include_in_schema=False,
    )
