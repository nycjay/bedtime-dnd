import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import APP_NAME, EMAIL_ENABLED
from app.deps import AuthRequired, templates
from app.routes import auth, campaigns, friends, game, players, settings

logging.basicConfig(level=logging.INFO)
logging.getLogger("google_genai").setLevel(logging.WARNING)

app = FastAPI(title="Bedtime D&D")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register route modules
app.include_router(auth.router)
app.include_router(campaigns.router)
app.include_router(friends.router)
app.include_router(players.router)
app.include_router(game.router)
app.include_router(settings.router)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"email_enabled": EMAIL_ENABLED})


@app.get("/")
async def root():
    return RedirectResponse(url="/campaigns")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse(url="/static/favicon.png", status_code=301)


@app.get("/manifest.json")
async def manifest():
    return JSONResponse(
        {
            "name": APP_NAME,
            "short_name": APP_NAME[:12],
            "start_url": "/campaigns",
            "display": "standalone",
            "background_color": "#111827",
            "theme_color": "#d97706",
            "icons": [
                {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
            ],
        },
        media_type="application/manifest+json",
    )


@app.exception_handler(AuthRequired)
async def auth_required_handler(request: Request, exc: AuthRequired):
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def custom_error_handler(request: Request, exc: StarletteHTTPException):
    ctx = {"code": exc.status_code, "message": exc.detail or "Something went wrong"}
    if exc.status_code == 404:
        ctx["message"] = "Page not found"
    return templates.TemplateResponse(request, "error.html", ctx, status_code=exc.status_code)


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).error(f"Unhandled error: {exc}")
    ctx = {"code": 500, "message": "The magic fizzled. Something went wrong."}
    return templates.TemplateResponse(request, "error.html", ctx, status_code=500)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
