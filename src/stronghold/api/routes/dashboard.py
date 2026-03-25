"""API route: dashboard — serves HTML pages for The Stronghold UI.

Dashboard pages require authentication (server-side check).
Login/logout/callback pages and static JS assets are public.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

router = APIRouter()

_DASHBOARD_CANDIDATES = [
    Path(__file__).parent.parent.parent / "dashboard",
    Path("/app/src/stronghold/dashboard"),
    Path("src/stronghold/dashboard"),
]

_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "connect-src 'self'",
        "img-src 'self' data:",
    ]
)

_LOGIN_REDIRECT = HTMLResponse(status_code=302, headers={"Location": "/login"})


def _serve_page(filename: str) -> HTMLResponse:
    """Serve an HTML dashboard page with no-cache and CSP headers."""
    for d in _DASHBOARD_CANDIDATES:
        filepath = d / filename
        if filepath.exists():
            return HTMLResponse(
                content=filepath.read_text(encoding="utf-8"),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Content-Security-Policy": _CSP,
                },
            )
    return HTMLResponse(
        content=f"<h1>Page not found: {filename}</h1>",
        status_code=404,
    )


async def _check_auth(request: Request) -> bool:
    """Server-side auth check for dashboard pages.

    Returns True if authenticated (valid auth header or session cookie).
    Returns False if no valid credentials found.
    """
    container = getattr(getattr(request.app, "state", None), "container", None)
    if not container:
        return False  # No container yet (startup) — deny access until ready

    # Check auth header
    auth_header = request.headers.get("authorization")
    if auth_header:
        try:
            await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
            return True
        except ValueError:
            pass

    # Check session cookie — must actually validate the token, not just check existence
    cookie_name = container.config.auth.session_cookie_name
    cookie_value = request.cookies.get(cookie_name)
    if not cookie_value:
        return False
    try:
        await container.auth_provider.authenticate(
            f"Bearer {cookie_value}",
            headers=dict(request.headers),
        )
        return True
    except ValueError:
        return False


@router.get("/dashboard/skills")
async def skills_dashboard(request: Request) -> HTMLResponse:
    """The Armory — skill management dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("skills.html")


@router.get("/dashboard/security")
async def security_dashboard(request: Request) -> HTMLResponse:
    """The Watchtower — security dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("security.html")


@router.get("/dashboard/outcomes")
async def outcomes_dashboard(request: Request) -> HTMLResponse:
    """The Treasury — outcomes and analytics dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("outcomes.html")


@router.get("/dashboard/agents")
async def agents_dashboard(request: Request) -> HTMLResponse:
    """The Knights — agent roster dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("agents.html")


@router.get("/dashboard/mcp")
async def mcp_dashboard(request: Request) -> HTMLResponse:
    """The Forge — MCP server management dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("mcp.html")


@router.get("/dashboard/quota")
async def quota_dashboard(request: Request) -> HTMLResponse:
    """The Ledger — provider quota and budget dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("quota.html")


@router.get("/dashboard/profile")
async def profile_dashboard(request: Request) -> HTMLResponse:
    """Profile — user identity and preferences."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("profile.html")


@router.get("/dashboard/leaderboard")
async def leaderboard_dashboard(request: Request) -> HTMLResponse:
    """The Arena — leaderboard and rankings."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("leaderboard.html")


@router.get("/dashboard/team")
async def team_dashboard(request: Request) -> HTMLResponse:
    """The Barracks — team administration dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("team.html")


@router.get("/dashboard/dungeon")
async def dungeon_dashboard(request: Request) -> HTMLResponse:
    """The Dungeon — strikes, violations, and appeals management."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("dungeon.html")


@router.get("/dashboard/org")
async def org_dashboard(request: Request) -> HTMLResponse:
    """The Throne Room — organization administration dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("org.html")


# ── Login & Auth (public — no auth required) ──


@router.get("/logout")
async def logout_redirect() -> HTMLResponse:
    """Logout — full nuclear option.

    Returns a page that:
    1. Server Set-Cookie headers delete HttpOnly cookies
    2. Client JS deletes everything JS can reach
    3. Client JS waits 500ms for cookies to clear
    4. Only THEN redirects to login page
    """
    html = (
        "<!DOCTYPE html><html><head>"
        "<title>Logging out...</title></head>\n"
        '<body style="background:#1a1a2e;color:#d4d0c8;'
        "font-family:monospace;display:flex;align-items:center;"
        'justify-content:center;height:100vh;margin:0">'
        """
<div style="text-align:center">
<div style="font-size:3rem;margin-bottom:16px">&#x1F3F0;</div>
<div>Logging out of the fortress...</div>
</div>
<script>
localStorage.clear();
sessionStorage.clear();
document.cookie.split(';').forEach(function(c){
  var n=c.split('=')[0].trim();
  document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
  document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;secure';
  document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;secure;samesite=lax';
});
// Wait for cookie deletion to take effect before redirecting
setTimeout(function(){location.href='/';},500);
</script>
</body></html>"""
    )

    response = HTMLResponse(content=html)
    # Server-side: delete HttpOnly cookies that JS can't reach
    for name in (
        "stronghold_session",
        "stronghold_logged_in",
        "sh_session_v2",
        "sh_logged_in_v2",
        "sh_session",
        "sh_logged_in",
    ):
        response.delete_cookie(key=name, path="/")
        response.delete_cookie(key=name, path="/", secure=True, httponly=True, samesite="lax")
        response.delete_cookie(key=name, path="/", secure=True, samesite="lax")
    return response


@router.get("/login")
async def login_page() -> HTMLResponse:
    """The Gates — login page."""
    return _serve_page("login.html")


@router.get("/login/callback")
async def login_callback() -> HTMLResponse:
    """OIDC callback — login page JS handles the code exchange."""
    return _serve_page("login.html")


_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _serve_js(filename: str) -> Response:
    """Serve a JS file with no-cache headers."""
    for d in _DASHBOARD_CANDIDATES:
        filepath = d / filename
        if filepath.exists():
            return Response(
                content=filepath.read_text(encoding="utf-8"),
                media_type="application/javascript",
                headers=_NO_CACHE,
            )
    return Response(content=f"// {filename} not found", media_type="application/javascript")


@router.get("/dashboard/auth.js")
async def auth_js() -> Response:
    return _serve_js("auth.js")


@router.get("/dashboard/scan-report.js")
async def scan_report_js() -> Response:
    return _serve_js("scan-report.js")
