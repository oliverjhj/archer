import os
import secrets
from fastapi import APIRouter, Request, Response, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth.csrf import generate_csrf_token, validate_csrf_token
from ..auth.jwt import create_jwt_token
from ..core.paths import BASE_DIR
from ..core.limiter import limiter

router = APIRouter()

@router.get("/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def get_login(request: Request, response: Response):
    try:
        csrf_token = generate_csrf_token()
        with open(BASE_DIR / "templates" / "login.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        
        csrf_input = f'<input type="hidden" name="csrf_token" value="{csrf_token}">'
        html_content = html_content.replace(
            '<button type="submit" class="login-btn">',
            f'{csrf_input}\n            <button type="submit" class="login-btn">'
        )
        
        # Detect if running locally (HTTP) or in production (HTTPS)
        is_secure = request.url.scheme == "https"
        
        html_response = HTMLResponse(content=html_content)
        html_response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,
            secure=is_secure,
            samesite="strict",
            max_age=3600
        )
        return html_response
    except FileNotFoundError:
        return HTMLResponse("<h1>Error: login.html not found.</h1>")

@router.post("/login")
@limiter.limit("5/minute")
async def do_login(request: Request, response: Response, username: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid or expired CSRF token. Please refresh the page and try again.")
    
    expected_user = os.environ.get("WEB_USERNAME", "").strip()
    expected_pass = os.environ.get("WEB_PASSWORD", "").strip()
    
    is_correct_username = secrets.compare_digest(username.strip(), expected_user)
    is_correct_password = secrets.compare_digest(password.strip(), expected_pass)
    
    if is_correct_username and is_correct_password and expected_user != "":
        jwt_token = create_jwt_token(username.strip())
        
        # Default redirect is now /landing instead of /dashboard
        target_url = request.cookies.get("intended_url", "/landing")
        
        # Detect if running locally (HTTP) or in production (HTTPS)
        is_secure = request.url.scheme == "https"
        
        redirect = RedirectResponse(url=target_url, status_code=303)
        redirect.set_cookie(
            key="archer_session",
            value=jwt_token,
            httponly=True,
            secure=is_secure,
            samesite="strict",
            max_age=86400
        )
        redirect.delete_cookie("intended_url")
        return redirect
    else:
        try:
            # Generate new CSRF token for retry
            csrf_token = generate_csrf_token()
            
            with open(BASE_DIR / "templates" / "login.html", "r", encoding="utf-8") as f:
                html = f.read()
                
                # Inject CSRF token
                csrf_input = f'<input type="hidden" name="csrf_token" value="{csrf_token}">'
                html = html.replace(
                    '<button type="submit" class="login-btn">',
                    f'{csrf_input}\n                <button type="submit" class="login-btn">'
                )
                
                # The error goes above the fields, where it is read before
                # the visitor types again. Styled by .login-error in the
                # login stylesheet, so it follows the page's theme.
                error_msg = (
                    '<div class="login-error" role="alert">'
                    'Incorrect username or password. Please try again.'
                    '</div>'
                )
                target_tag = '<form action="/login" method="POST">'
                if target_tag in html:
                    html = html.replace(target_tag, target_tag + '\n                ' + error_msg)
                
                # Detect if running locally (HTTP) or in production (HTTPS)
                is_secure = request.url.scheme == "https"
                
                html_response = HTMLResponse(content=html)
                html_response.set_cookie(
                    key="csrf_token",
                    value=csrf_token,
                    httponly=False,
                    secure=is_secure,
                    samesite="strict",
                    max_age=3600
                )
                return html_response
        except FileNotFoundError:
            return HTMLResponse("<h1>Error: login.html not found.</h1>")

