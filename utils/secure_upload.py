import os
import mimetypes
import hashlib
from pathlib import Path
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
import uuid
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg',
    'pdf', 'txt', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'json', 'csv', 'xml', 'yaml', 'yml',
    'zip', 'tar', 'gz', '7z', 'rar'
}

BLOCKED_EXTENSIONS = {
    'exe', 'msi', 'scr', 'pif', 'vbs', 'js', 'jar', 'bat', 'cmd', 'com',
    'pdb', 'cpp', 'c', 'h', 'hpp', 'cxx', 'py', 'rb', 'php', 'jsp', 'asp',
    'aspx', 'pl', 'sh', 'bash', 'ps1',
    'dll', 'so', 'dylib', 'sys', 'drv',
    'ini', 'conf', 'config', 'env', 'htaccess',
}

ALLOWED_MIME_TYPES = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/svg+xml': 'svg',
    'image/bmp': 'bmp',
    'application/pdf': 'pdf',
    'text/plain': 'txt',
    'application/msword': 'doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.ms-powerpoint': 'ppt',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    'application/json': 'json',
    'text/csv': 'csv',
    'application/xml': 'xml',
    'text/yaml': 'yaml',
    'application/x-yaml': 'yml',
}
MAX_FILE_SIZES = {
    'image': 50 * 1024 * 1024,
    'document': 100 * 1024 * 1024,
    'archive': 500 * 1024 * 1024,
    'default': 50 * 1024 * 1024,
}


def get_file_type_category(extension):

    if extension in {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'}:
        return 'image'
    elif extension in {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt'}:
        return 'document'
    elif extension in {'zip', 'tar', 'gz', '7z', 'rar'}:
        return 'archive'
    return 'default'


def get_max_file_size(extension):

    category = get_file_type_category(extension)
    return MAX_FILE_SIZES.get(category, MAX_FILE_SIZES['default'])


def validate_filename(filename):
    if not filename or not isinstance(filename, str):
        return False, 'Invalid filename', None
    filename = os.path.basename(filename)
    safe_name = secure_filename(filename)

    if not safe_name or safe_name == '':
        return False, 'Filename is not secure', None
    if len(safe_name) > 255:
        return False, 'Filename too long (max 255 characters)', None
    name_parts = safe_name.rsplit('.', 1)
    if len(name_parts) != 2:
        return False, 'Filename must have an extension', None

    extension = name_parts[1].lower()
    if extension in BLOCKED_EXTENSIONS:
        return False, f'File type .{extension} is not allowed', None
    if extension not in ALLOWED_EXTENSIONS:
        return False, f'File type .{extension} is not supported', None

    return True, None, safe_name


def validate_file_content(file_path):
    if not os.path.exists(file_path):
        return False, 'File not found'
    if not os.path.isfile(file_path):
        return False, 'Path is not a file'
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return False, 'File is empty'
    _, ext = os.path.splitext(file_path)
    ext = ext.lstrip('.').lower()

    max_size = get_max_file_size(ext)
    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        return False, f'File too large (max {max_mb:.0f} MB)'

    return True, None


def validate_mime_type(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)

    if not mime_type:
        mime_type = guess_mime_from_content(file_path)

    return mime_type is not None, mime_type


def guess_mime_from_content(file_path):
    try:
        with open(file_path, 'rb') as f:
            magic = f.read(12)
        if magic.startswith(b'\x89PNG'):
            return 'image/png'
        elif magic.startswith(b'\xff\xd8\xff'):
            return 'image/jpeg'
        elif magic.startswith(b'GIF8'):
            return 'image/gif'
        elif magic.startswith(b'RIFF') and b'WEBP' in magic:
            return 'image/webp'
        elif magic.startswith(b'%PDF'):
            return 'application/pdf'
        elif magic.startswith(b'{') or magic.startswith(b'['):
            return 'application/json'
        elif magic.startswith(b'PK'):
            return 'application/zip'
        elif all(chr(b) in ' \t\n\r' + chr(0x20) + ''.join(chr(i) for i in range(32, 127)) for b in magic[:min(12, len(magic))]):
            return 'text/plain'

    except Exception:
        pass

    return None


def secure_upload_file(file: FileStorage, upload_dir: Path, original_user_id: str = None):
    from utils.audit_log import log_audit_event, AuditEvents

    if not file or not file.filename:
        return False, 'No file provided', None
    is_valid, error, safe_name = validate_filename(file.filename)
    if not is_valid:
        log_audit_event(AuditEvents.FILE_UPLOAD_BLOCKED, {
            'reason': error,
            'original_name': file.filename[:100]
        }, original_user_id)
        return False, error, None
    name_parts = safe_name.rsplit('.', 1)
    extension = name_parts[1] if len(name_parts) == 2 else ''
    upload_dir = Path(upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    uuid_filename = f"{uuid.uuid4().hex}"
    if extension:
        uuid_filename = f"{uuid_filename}.{extension}"
    safe_path = upload_dir / uuid_filename
    try:
        resolved_path = safe_path.resolve()
        upload_dir_resolved = upload_dir.resolve()

        if not str(resolved_path).startswith(str(upload_dir_resolved)):
            log_audit_event(AuditEvents.FILE_UPLOAD_BLOCKED, {
                'reason': 'path_traversal_attempt',
                'original_name': file.filename[:100]
            }, original_user_id)
            return False, 'Invalid file path', None
    except Exception:
        return False, 'Invalid file path', None
    temp_name = f"temp_{uuid.uuid4().hex}_{uuid_filename}"
    temp_path = upload_dir / temp_name

    try:
        file.save(str(temp_path))
    except Exception as e:
        return False, f'Failed to save file', None
    is_valid, error = validate_file_content(str(temp_path))
    if not is_valid:
        try:
            os.remove(str(temp_path))
        except:
            pass
        log_audit_event(AuditEvents.FILE_UPLOAD_BLOCKED, {
            'reason': error,
            'original_name': file.filename[:100]
        }, original_user_id)
        return False, error, None
    detected_mime = validate_mime_with_magic(str(temp_path))
    if not detected_mime:
        try:
            os.remove(str(temp_path))
        except:
            pass
        log_audit_event(AuditEvents.FILE_UPLOAD_BLOCKED, {
            'reason': 'invalid_mime_type',
            'original_name': file.filename[:100]
        }, original_user_id)
        return False, 'Invalid file type', None
    if not is_mime_extension_match(detected_mime, extension):
        try:
            os.remove(str(temp_path))
        except:
            pass
        log_audit_event(AuditEvents.FILE_UPLOAD_BLOCKED, {
            'reason': 'mime_extension_mismatch',
            'detected_mime': detected_mime,
            'extension': extension,
            'original_name': file.filename[:100]
        }, original_user_id)
        return False, 'File type mismatch detected', None
    try:
        final_path = upload_dir / uuid_filename
        os.rename(str(temp_path), str(final_path))
    except Exception as e:
        try:
            os.remove(str(temp_path))
        except:
            pass
        return False, f'Failed to finalize file', None
    file_hash = calculate_file_hash(str(final_path))

    log_audit_event(AuditEvents.FILE_UPLOAD, {
        'filename': uuid_filename,
        'original_name': file.filename[:100],
        'mime_type': detected_mime,
        'size': final_path.stat().st_size
    }, original_user_id)

    return True, None, {
        'filename': final_path.name,
        'path': str(final_path),
        'size': final_path.stat().st_size,
        'mime_type': detected_mime,
        'hash': file_hash,
        'original_name': file.filename,
    }


def calculate_file_hash(file_path, algorithm='sha256'):

    hash_obj = hashlib.new(algorithm)
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    except Exception:
        return None


def validate_mime_with_magic(file_path):
    try:
        import magic
        mime = magic.Magic(mime=True)
        detected_mime = mime.from_file(file_path)
        if detected_mime in ALLOWED_MIME_TYPES:
            return detected_mime
        if detected_mime.startswith('text/') and 'text/plain' in ALLOWED_MIME_TYPES:
            return detected_mime

        return None
    except ImportError:
        return guess_mime_from_content(file_path)
    except Exception:
        return None


def is_mime_extension_match(mime_type, extension):
    if not mime_type or not extension:
        return False

    extension = extension.lower()
    extension_to_mime = {
        'png': ['image/png'],
        'jpg': ['image/jpeg'],
        'jpeg': ['image/jpeg'],
        'gif': ['image/gif'],
        'webp': ['image/webp'],
        'svg': ['image/svg+xml', 'text/xml', 'application/xml'],
        'bmp': ['image/bmp', 'image/x-bmp'],
        'pdf': ['application/pdf'],
        'txt': ['text/plain'],
        'json': ['application/json', 'text/plain'],
        'csv': ['text/csv', 'text/plain', 'application/csv'],
        'xml': ['application/xml', 'text/xml'],
        'yaml': ['text/yaml', 'application/x-yaml', 'text/plain'],
        'yml': ['text/yaml', 'application/x-yaml', 'text/plain'],
        'doc': ['application/msword'],
        'docx': ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/zip'],
        'xls': ['application/vnd.ms-excel'],
        'xlsx': ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/zip'],
        'ppt': ['application/vnd.ms-powerpoint'],
        'pptx': ['application/vnd.openxmlformats-officedocument.presentationml.presentation', 'application/zip'],
        'zip': ['application/zip', 'application/x-zip-compressed'],
        'tar': ['application/x-tar'],
        'gz': ['application/gzip', 'application/x-gzip'],
        '7z': ['application/x-7z-compressed'],
        'rar': ['application/x-rar-compressed', 'application/vnd.rar'],
    }

    expected_mimes = extension_to_mime.get(extension, [])
    return mime_type in expected_mimes or not expected_mimes


def is_safe_to_serve(file_path):
    file_path = Path(file_path)

    if not file_path.exists() or not file_path.is_file():
        return False

    _, ext = os.path.splitext(file_path)
    ext = ext.lstrip('.').lower()
    if ext in BLOCKED_EXTENSIONS:
        return False

    return True


def sanitize_filename_for_download(filename):
    if not filename:
        return 'download'
    filename = os.path.basename(filename)
    safe_chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_'
    sanitized = ''.join(c if c in safe_chars else '_' for c in filename)
    if len(sanitized) > 200:
        name, ext = os.path.splitext(sanitized)
        sanitized = name[:200-len(ext)] + ext

    return sanitized or 'download'
