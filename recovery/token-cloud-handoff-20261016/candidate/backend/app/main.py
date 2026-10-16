from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .prompt_api import router as prompt_router
from .config import settings
from .database import Base, engine

app = FastAPI(title="Development Team Simulator", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(prompt_router)


@app.on_event("startup")
def create_tables():
    # 在应用启动时创建尚不存在的数据库表。
    Base.metadata.create_all(engine)


@app.get("/health")
def health():
    # 返回服务健康状态。
    return {"status": "ok"}
