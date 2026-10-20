"""Server LJK Reader Online: API + web admin daerah (/scan) + panel superadmin (/admin)."""
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import WEB_DIR as WEB
from .db import Base, engine
from .routers import admin, auth, files, scan, sync

app = FastAPI(title="LJK Reader Online", version="1.0")
for r in (auth.router, admin.router, scan.router, sync.router, files.router):
    app.include_router(r)


@app.on_event("startup")
def _create_tables():
    Base.metadata.create_all(engine)


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(WEB / "index.html")


@app.get("/scan", include_in_schema=False)
def _scan():
    return RedirectResponse(url="/scan/")


@app.get("/admin", include_in_schema=False)
def _admin():
    return RedirectResponse(url="/admin/")


app.mount("/scan", StaticFiles(directory=WEB / "scan", html=True), name="scan")
app.mount("/admin", StaticFiles(directory=WEB / "admin", html=True), name="admin")
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
