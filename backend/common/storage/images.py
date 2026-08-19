"""Image validation and WebP processing shared by upload endpoints."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from rest_framework import exceptions, status

MAX_UPLOAD_SIZE = 10 * 1024 * 1024
MAX_PROCESSED_WIDTH = 1600
THUMBNAIL_WIDTH = 400
WEBP_QUALITY = 82

ALLOWED_IMAGE_MIME_TYPES = frozenset(
    {
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
    }
)


class UnsupportedFileType(exceptions.APIException):
    """Return the documented error for a non-image upload."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "UNSUPPORTED_FILE_TYPE"
    default_detail = "The file type is not supported."


class FileTooLarge(exceptions.APIException):
    """Return the documented error for an oversized upload."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "FILE_TOO_LARGE"
    default_detail = "The uploaded file exceeds the size limit."


@dataclass(frozen=True)
class ProcessedImage:
    """WebP image variants ready for storage by a caller."""

    image: ContentFile
    thumbnail: ContentFile


def _webp_content(image, *, width: int, filename: str) -> ContentFile:
    """Resize ``image`` to ``width`` when needed and encode it as WebP."""
    if image.width > width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height))

    output = BytesIO()
    image.save(output, format="WEBP", quality=WEBP_QUALITY)
    return ContentFile(output.getvalue(), name=filename)


def process_uploaded_image(uploaded_file) -> ProcessedImage:
    """Validate an upload and return its WebP original and thumbnail variants.

    Pillow is imported lazily so management commands that only inspect model state
    do not require the optional runtime image dependency to be installed yet.
    """
    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise FileTooLarge()
    if uploaded_file.content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise UnsupportedFileType()

    from PIL import Image, UnidentifiedImageError

    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as source:
            source.verify()
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as source:
            actual_mime_type = Image.MIME.get(source.format)
            if actual_mime_type != uploaded_file.content_type:
                raise UnsupportedFileType()
            image = source.convert("RGBA" if "A" in source.getbands() else "RGB")
            stem = Path(uploaded_file.name or "image").stem or "image"
            filename = f"{stem}.webp"
            return ProcessedImage(
                image=_webp_content(image.copy(), width=MAX_PROCESSED_WIDTH, filename=filename),
                thumbnail=_webp_content(
                    image.copy(), width=THUMBNAIL_WIDTH, filename=f"{stem}_thumbnail.webp"
                ),
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnsupportedFileType() from exc


def save_thumbnail_beside(field_file, thumbnail: ContentFile) -> str:
    """Persist ``thumbnail`` next to an already-saved image and return its storage name.

    API §21 requires a thumbnail per uploaded image. ``Workspace`` has no thumbnail column and
    this Story adds no model field, so the variant is stored alongside its original under a
    derived name and located by convention rather than by a database reference.
    """
    saved_name = field_file.name
    directory = str(Path(saved_name).parent)
    stem = Path(saved_name).stem
    target = f"{stem}_thumbnail.webp"
    if directory not in ("", "."):
        target = f"{directory}/{target}"
    return field_file.storage.save(target, thumbnail)
