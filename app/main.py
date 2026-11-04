from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request
from starlette.templating import Jinja2Templates

from app.api import router
from app.config import Settings, get_settings
from app.database import Base, build_engine, get_db
from app import models  # noqa: F401

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def create_app(settings: Settings | None = None, database_url: str | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app_engine = build_engine(database_url) if database_url else build_engine(app_settings.database_url)
    session_factory = sessionmaker(bind=app_engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        Base.metadata.create_all(bind=app_engine)
        yield
        app_engine.dispose()

    app = FastAPI(title=app_settings.app_name, version="1.0.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.engine = app_engine
    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix=app_settings.api_prefix)

    def app_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = app_db

    def render_page(request: Request, page: str, **context):
        firebase_config = None
        if all(
            (
                app_settings.firebase_web_api_key,
                app_settings.firebase_web_auth_domain,
                app_settings.firebase_web_project_id,
                app_settings.firebase_web_app_id,
            )
        ):
            firebase_config = {
                "apiKey": app_settings.firebase_web_api_key,
                "authDomain": app_settings.firebase_web_auth_domain,
                "projectId": app_settings.firebase_web_project_id,
                "appId": app_settings.firebase_web_app_id,
            }
        return templates.TemplateResponse(
            request=request,
            name=page,
            context={"request": request, "firebase_config": firebase_config, **context},
        )

    @app.get("/", include_in_schema=False)
    def landing(request: Request):
        return render_page(request, "landing.html", page_title="Photoreal faces for every post & persona")

    @app.get("/product", include_in_schema=False)
    def product(request: Request):
        return render_page(request, "product.html", page_title="Create a face")

    @app.get("/login", include_in_schema=False)
    def login_page(request: Request):
        return render_page(request, "auth.html", page_title="Welcome back", auth_mode="login")

    @app.get("/register", include_in_schema=False)
    def register_page(request: Request):
        return render_page(request, "auth.html", page_title="Create your account", auth_mode="register")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard_page(request: Request):
        return render_page(request, "dashboard.html", page_title="Your dashboard")

    @app.get("/gallery", include_in_schema=False)
    def gallery_page(request: Request):
        return render_page(request, "gallery.html", page_title="Your gallery")

    @app.get("/billing", include_in_schema=False)
    def billing_page(request: Request):
        return render_page(request, "billing.html", page_title="Credits & billing")

    return app


app = create_app()
