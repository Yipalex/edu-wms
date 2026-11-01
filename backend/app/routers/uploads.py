"""照片静态访问：GET /uploads/{path}（DESIGN §6，公开）。

不用 StaticFiles 直挂 UPLOAD_DIR，而是自己实现路径解析：
- resolve() 后强制校验仍在 UPLOAD_DIR 之内（防 ../ 路径穿越）
- 只允许白名单图片扩展名
- 404 中文提示
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings

router = APIRouter(prefix="/uploads", tags=["文件访问"])

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@router.get("/{file_path:path}")
def serve_upload(file_path: str):
    root = Path(settings.UPLOAD_DIR).resolve()
    target = (root / file_path).resolve()
    # 路径穿越防护：解析后的绝对路径必须仍在上传根目录内
    if not str(target).startswith(str(root) + "/") and target != root:
        return JSONResponse(
            status_code=400,
            content={"detail": "非法的文件路径", "code": "ERR_BAD_PATH"},
        )
    if target.suffix.lower() not in ALLOWED_EXT:
        return JSONResponse(
            status_code=400,
            content={"detail": "不支持的文件类型", "code": "ERR_BAD_FILE_TYPE"},
        )
    if not target.is_file():
        return JSONResponse(
            status_code=404,
            content={"detail": "文件不存在或已被删除", "code": "ERR_NOT_FOUND"},
        )
    return FileResponse(target)
