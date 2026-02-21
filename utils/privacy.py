import os
import json
import hashlib
import shutil
from datetime import datetime
from flask import session

from config import CHATS_FOLDER, UPLOAD_FOLDER, CREATE_IMAGE_FOLDER


def anonymize_ip(ip_address):
    if not ip_address:
        return None

    if ':' in ip_address:  # IPv6
        parts = ip_address.split(':')
        if len(parts) > 2:
            return ':'.join(parts[:3]) + '::0'
    else:  # IPv4
        parts = ip_address.split('.')
        if len(parts) == 4:
            return '.'.join(parts[:3]) + '.0'

    return None


def hash_for_logging(value, salt='remind_log'):
    if not value:
        return None
    combined = f"{salt}:{value}"
    return hashlib.sha256(combined.encode()).hexdigest()[:12]


def get_user_data_locations(user_id):
    return {
        'database': [
            'user',
            'user_settings',
            'user_chat_history',
            'chat_share',
        ],
        'files': {
            'chats': CHATS_FOLDER,
            'uploads': UPLOAD_FOLDER,
            'generated_images': CREATE_IMAGE_FOLDER,
        }
    }


def export_user_data(user_id):
    from utils.auth import User, UserSettings, UserChatHistory, ChatShare, db

    export_data = {
        'exported_at': datetime.utcnow().isoformat(),
        'user_id': user_id,
    }
    user = User.query.get(user_id)
    if user:
        export_data['profile'] = {
            'username': user.username,
            'email': user.email,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'is_confirmed': user.is_confirmed,
            'oauth_provider': user.oauth_provider,
        }
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings:
        export_data['settings'] = settings.to_dict()
    chats = UserChatHistory.query.filter_by(user_id=user_id).all()
    export_data['chats'] = [chat.to_dict() for chat in chats]
    shares = ChatShare.query.filter_by(user_id=user_id).all()
    export_data['shares'] = [share.to_dict() for share in shares]

    return export_data


def delete_user_data(user_id, delete_account=False):
    from utils.auth import User, UserSettings, UserChatHistory, ChatShare, db
    from utils.audit_log import log_audit_event, AuditEvents

    results = {
        'user_id': user_id,
        'deleted_at': datetime.utcnow().isoformat(),
        'items_deleted': {},
    }

    try:
        shares_deleted = ChatShare.query.filter_by(user_id=user_id).delete()
        results['items_deleted']['chat_shares'] = shares_deleted
        chats = UserChatHistory.query.filter_by(user_id=user_id).all()
        chat_session_ids = [chat.session_id for chat in chats]
        chats_deleted = UserChatHistory.query.filter_by(user_id=user_id).delete()
        results['items_deleted']['chats'] = chats_deleted
        files_deleted = 0
        for session_id in chat_session_ids:
            try:
                safe_id = ''.join(c for c in session_id if c.isalnum() or c in '-_')
                chat_file = CHATS_FOLDER / f"{safe_id}.json"
                if chat_file.exists():
                    os.remove(chat_file)
                    files_deleted += 1
            except Exception:
                pass
        results['items_deleted']['chat_files'] = files_deleted
        settings_deleted = UserSettings.query.filter_by(user_id=user_id).delete()
        results['items_deleted']['settings'] = settings_deleted
        if delete_account:
            user = User.query.get(user_id)
            if user:
                db.session.delete(user)
                results['items_deleted']['account'] = 1
                results['account_deleted'] = True

        db.session.commit()
        log_audit_event(AuditEvents.DELETE_USER_DATA, {
            'items_deleted': results['items_deleted'],
            'account_deleted': delete_account
        }, user_id)

        return results

    except Exception as e:
        db.session.rollback()
        raise e


def anonymize_user_data(user_id):
    from utils.auth import User, UserSettings, UserChatHistory, db

    user = User.query.get(user_id)
    if not user:
        return False
    anonymous_id = hashlib.sha256(str(user_id).encode()).hexdigest()[:12]
    user.username = f"deleted_user_{anonymous_id}"
    user.email = f"{anonymous_id}@deleted.invalid"
    user.password = None
    user.confirmation_token = None
    user.reset_token = None
    user.oauth_id = None
    UserSettings.query.filter_by(user_id=user_id).delete()
    chats = UserChatHistory.query.filter_by(user_id=user_id).all()
    for chat in chats:
        chat.title = "Deleted Chat"
        chat.messages_data = "[]"

    db.session.commit()
    return True


class PrivacySettings:
    LOG_IP_ADDRESSES = False
    LOG_USER_AGENTS = False
    LOG_EMAIL_ADDRESSES = False
    AUDIT_LOG_RETENTION = 90
    SESSION_LOG_RETENTION = 30
    CHAT_RETENTION = 365
    ANONYMIZE_IPS = True
    HASH_EMAILS_IN_LOGS = True
