from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Prevent clickjacking attacks
        response.headers["X-Frame-Options"] = "DENY"
        
        # Legacy XSS protection (for older browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Force HTTPS connections (HSTS)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Content Security Policy - Allow Watson Assistant and IBM Watsonx domains
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://web-chat.global.assistant.watson.appdomain.cloud https://web-chat.global.assistant.watson.cloud.ibm.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https://*.watson.appdomain.cloud https://*.watson.cloud.ibm.com https://eu-gb.ml.cloud.ibm.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "frame-ancestors 'none';"
        )
        
        # Control referrer information leakage
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions Policy (formerly Feature-Policy)
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # The login page's stylesheet keeps the same URL across deploys, so
        # browsers must check for a newer one each time instead of reusing a
        # cached copy. A matching ETag still makes that check cheap. The React
        # app's files under /assets have content hashes in their names and
        # need no such header.
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"

        return response

