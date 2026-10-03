# Load environment variables BEFORE any imports that read them
from dotenv import load_dotenv
load_dotenv()

# Now safe to import modules that read environment variables
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, status, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .core.paths import BASE_DIR, STATIC_DIR, FRONTEND_ASSETS_DIR
from .core.logging import configure_logging
from .core.security_headers import SecurityHeadersMiddleware
from .core.limiter import limiter
from .db.database import verify_database
from .api import auth_routes, page_routes, ask, schema_routes

# Configure logging
configure_logging()

# --- FASTAPI LIFESPAN EVENT HANDLER ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan event handler.

    Verifies the bundled database before the application accepts requests.
    The database is baked into the image at build time rather than downloaded
    from object storage, so this is a local check rather than a network call.

    Refusing to start without a valid database is deliberate: an application
    that serves errors on every query is worse than one that fails loudly at
    deploy time, where the failure is visible.
    """
    logging.info("Starting Archer application...")

    if not verify_database():
        logging.critical("FATAL: Application cannot start without database. Exiting.")
        raise RuntimeError("Database verification failed")

    logging.info("Database ready. FastAPI is now accepting requests.")
    
    yield  # Application runs here
    
    # Shutdown: Clean-up (optional)
    logging.info("Shutting down Archer application...")

# Initialise FastAPI with lifespan event handler
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter

# Log application initialisation
logging.info("Archer FastAPI application initialised successfully")

# Mount static files folder (login page stylesheet, favicon)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Serve the built React bundle. Guarded rather than assumed: a developer who
# has not run the frontend build should still get a working API, and the page
# route explains the situation instead of the application refusing to start.
if FRONTEND_ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_ASSETS_DIR)), name="assets")
    logging.info("Serving built frontend assets from %s", FRONTEND_ASSETS_DIR)
else:
    logging.warning(
        "No built frontend found at %s - the API will run but / will report it",
        FRONTEND_ASSETS_DIR,
    )

# Custom handler for RateLimitExceeded
def rate_limit_handler(request: Request, exc: Exception) -> Response:
    """Handle rate limit exceeded errors"""
    return _rate_limit_exceeded_handler(request, exc)  # type: ignore[arg-type]

app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

# Custom exception handler for 401 errors - redirect to login
@app.exception_handler(status.HTTP_401_UNAUTHORIZED)
async def redirect_to_login(request: Request, exc: HTTPException):
    """
    Handle unauthenticated requests.

    Page routes redirect to the login form, which is what a browser navigating
    to /landing or /chat should get. API routes under /api/ get a JSON 401
    instead: a fetch() call cannot do anything useful with a 303 to an HTML
    login page, and following it would hand the caller a page where it expected
    data. The frontend treats the JSON 401 as a session-expired signal.
    """
    if request.url.path.startswith("/api/"):
        detail = getattr(exc, "detail", "Not authenticated")
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": detail})

    response = RedirectResponse(url="/login", status_code=303)
    response.set_cookie(key="intended_url", value=str(request.url.path))
    return response

# Register Security Headers Middleware
app.add_middleware(SecurityHeadersMiddleware)

# Include routers
app.include_router(auth_routes.router)
app.include_router(page_routes.router)
app.include_router(ask.router)
app.include_router(schema_routes.router)

