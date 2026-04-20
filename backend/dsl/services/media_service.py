"""媒体服务模块.

提供图片存储、缩略图生成和媒体文件服务.
"""

import io
import uuid
from pathlib import Path

from PIL import Image
from fastapi import UploadFile

from utils.logger import logger
from utils.settings import config


class MediaService:
    """媒体服务类.

    处理图片上传、存储、缩略图生成和文件服务.
    """

    # 缩略图最大宽度
    THUMBNAIL_MAX_WIDTH: int = 300
    # 允许的图片格式
    ALLOWED_IMAGE_FORMATS: set[str] = {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/x-png",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/x-bmp",
        "image/x-ms-bmp",
    }
    # 最大文件大小 (10MB)
    MAX_FILE_SIZE: int = 10 * 1024 * 1024

    @staticmethod
    def ensure_media_directories() -> None:
        """确保媒体存储目录存在."""
        media_path = Path(config.MEDIA_STORAGE_PATH)
        original_path = media_path / "original"
        thumbnail_path = media_path / "thumbnail"

        original_path.mkdir(parents=True, exist_ok=True)
        thumbnail_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generate_unique_filename(original_filename: str) -> str:
        """生成唯一的文件名.

        Args:
            original_filename: 原始文件名

        Returns:
            str: 生成的唯一文件名
        """
        file_extension = Path(original_filename).suffix.lower()
        if file_extension not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            file_extension = ".png"
        return f"{uuid.uuid4()}{file_extension}"

    @staticmethod
    def generate_unique_attachment_filename(original_filename: str) -> str:
        """生成附件文件名.

        Args:
            original_filename: 原始文件名

        Returns:
            str: 生成的唯一附件文件名
        """
        file_extension = Path(original_filename).suffix.lower()
        sanitized_extension = file_extension[:20] if file_extension else ""
        return f"{uuid.uuid4()}{sanitized_extension}"

    @staticmethod
    def create_thumbnail(image: Image.Image, max_width: int = 300) -> Image.Image:
        """创建缩略图.

        Args:
            image: 原始图片对象
            max_width: 最大宽度

        Returns:
            Image.Image: 缩略图对象
        """
        width, height = image.size
        if width <= max_width:
            return image.copy()

        ratio = max_width / width
        new_height = int(height * ratio)

        return image.resize((max_width, new_height), Image.Resampling.LANCZOS)

    @staticmethod
    async def save_image(upload_file: UploadFile) -> tuple[str, str]:
        """保存上传的图片并生成缩略图.

        Args:
            upload_file: FastAPI 上传文件对象

        Returns:
            tuple[str, str]: (原图相对路径, 缩略图相对路径)

        Raises:
            ValueError: 当文件类型不支持或处理失败时
        """
        MediaService.ensure_media_directories()

        # 验证文件类型
        if upload_file.content_type not in MediaService.ALLOWED_IMAGE_FORMATS:
            raise ValueError(f"Unsupported image format: {upload_file.content_type}")

        # 生成唯一文件名
        unique_filename = MediaService.generate_unique_filename(
            upload_file.filename or "image.png"
        )

        media_path = Path(config.MEDIA_STORAGE_PATH)
        original_path = media_path / "original" / unique_filename
        thumbnail_path = media_path / "thumbnail" / unique_filename

        try:
            # 读取文件内容
            file_content = await upload_file.read()

            if len(file_content) > MediaService.MAX_FILE_SIZE:
                raise ValueError(
                    f"File too large. Max size: {MediaService.MAX_FILE_SIZE / 1024 / 1024}MB"
                )

            # 打开图片
            image = Image.open(io.BytesIO(file_content))

            # 转换为 RGB 如果需要（处理透明 PNG）
            if image.mode in ("RGBA", "P"):
                rgb_image = image.convert("RGB")
            else:
                rgb_image = image

            # 保存原图
            rgb_image.save(original_path, quality=95, optimize=True)

            # 生成并保存缩略图
            thumbnail_image = MediaService.create_thumbnail(
                rgb_image, MediaService.THUMBNAIL_MAX_WIDTH
            )
            thumbnail_image.save(thumbnail_path, quality=85, optimize=True)

            logger.info(f"Saved image: {unique_filename}")

            return (
                str(original_path.relative_to(config.BASE_DIR)),
                str(thumbnail_path.relative_to(config.BASE_DIR)),
            )

        except Exception as error:
            logger.error(f"Failed to process image: {error}")
            raise ValueError(f"Failed to process image: {error}") from error

    @staticmethod
    async def save_attachment(upload_file: UploadFile) -> str:
        """保存上传的附件.

        Args:
            upload_file: FastAPI 上传文件对象

        Returns:
            str: 附件相对路径

        Raises:
            ValueError: 当文件为空或处理失败时
        """
        MediaService.ensure_media_directories()

        unique_filename = MediaService.generate_unique_attachment_filename(
            upload_file.filename or "attachment"
        )
        media_path = Path(config.MEDIA_STORAGE_PATH)
        attachment_path = media_path / "original" / unique_filename

        try:
            file_content = await upload_file.read()

            if not file_content:
                raise ValueError("Uploaded file is empty")

            if len(file_content) > MediaService.MAX_FILE_SIZE:
                raise ValueError(
                    f"File too large. Max size: {MediaService.MAX_FILE_SIZE / 1024 / 1024}MB"
                )

            attachment_path.write_bytes(file_content)
            logger.info(f"Saved attachment: {unique_filename}")

            return str(attachment_path.relative_to(config.BASE_DIR))
        except Exception as error:
            logger.error(f"Failed to save attachment: {error}")
            raise ValueError(f"Failed to save attachment: {error}") from error

    @staticmethod
    def delete_stored_media_files(relative_media_path_list: list[str | None]) -> None:
        """Delete stored media files for a failed log-creation path.

        Args:
            relative_media_path_list: 需要清理的相对或绝对路径列表
        """
        for relative_media_path in relative_media_path_list:
            if not relative_media_path:
                continue

            candidate_media_path = Path(relative_media_path)
            absolute_media_path = (
                candidate_media_path
                if candidate_media_path.is_absolute()
                else (config.BASE_DIR / candidate_media_path)
            )

            try:
                if absolute_media_path.exists():
                    absolute_media_path.unlink()
                    logger.info(f"Deleted orphaned media file: {absolute_media_path}")
            except OSError as error:
                logger.warning(
                    "Failed to delete orphaned media file %s: %s",
                    absolute_media_path,
                    error,
                )

    @staticmethod
    def get_image_path(filename: str, is_thumbnail: bool = False) -> Path | None:
        """获取图片文件路径.

        Args:
            filename: 文件名
            is_thumbnail: 是否获取缩略图

        Returns:
            Path | None: 文件路径或 None（如果不存在）
        """
        subdir = "thumbnail" if is_thumbnail else "original"
        file_path = Path(config.MEDIA_STORAGE_PATH) / subdir / filename

        if file_path.exists():
            return file_path
        return None
