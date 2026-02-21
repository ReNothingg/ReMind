from functools import wraps
from flask import request, session
from utils.responses import make_error
from utils.auth import UserChatHistory, ChatShare, db


def require_auth(view_func):
    @wraps(view_func)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return make_error(
                "Authentication required",
                status=401,
                code="auth_required"
            )
        return view_func(*args, **kwargs)
    return decorated_function


def check_resource_ownership(resource_type, resource_id_arg='resource_id'):
    def decorator(view_func):
        @wraps(view_func)
        def decorated_function(*args, **kwargs):

            if "user_id" not in session:
                return make_error(
                    "Authentication required",
                    status=401,
                    code="auth_required"
                )

            try:
                user_id = int(session.get("user_id"))
            except (ValueError, TypeError):
                return make_error(
                    "Invalid session",
                    status=401,
                    code="invalid_session"
                )


            resource_id = None


            if resource_id_arg in kwargs:
                resource_id = kwargs[resource_id_arg]


            if not resource_id:
                resource_id = request.args.get(resource_id_arg)


            if not resource_id:
                try:
                    data = request.get_json(silent=True) or {}
                    resource_id = data.get(resource_id_arg)
                except:
                    pass


            if not resource_id:
                resource_id = request.form.get(resource_id_arg)

            if not resource_id:
                return make_error(
                    "Resource ID not provided",
                    status=400,
                    code="missing_resource_id"
                )


            is_owner = False

            if resource_type == 'chat':
                chat = UserChatHistory.query.filter_by(
                    user_id=user_id,
                    session_id=str(resource_id)
                ).first()
                is_owner = chat is not None

            elif resource_type == 'chat_share':
                share = ChatShare.query.filter_by(
                    user_id=user_id,
                    session_id=str(resource_id)
                ).first()
                is_owner = share is not None

            elif resource_type == 'public_chat':


                share = ChatShare.query.filter_by(
                    session_id=str(resource_id)
                ).first()

                if share and share.is_public:

                    is_owner = True
                elif share and share.user_id == user_id:

                    is_owner = True

            if not is_owner:
                return make_error(
                    "Access denied",
                    status=403,
                    code="access_denied"
                )


            return view_func(*args, **kwargs)

        return decorated_function
    return decorator


def verify_resource_access(user_id, resource_type, resource_id):
    if not user_id:
        return False

    if resource_type == 'chat':
        chat = UserChatHistory.query.filter_by(
            user_id=user_id,
            session_id=str(resource_id)
        ).first()
        return chat is not None

    elif resource_type == 'chat_share':
        share = ChatShare.query.filter_by(
            user_id=user_id,
            session_id=str(resource_id)
        ).first()
        return share is not None

    elif resource_type == 'public_chat':
        share = ChatShare.query.filter_by(
            session_id=str(resource_id)
        ).first()
        return share is not None and share.is_public

    return False


def add_ownership_filter(query, user_id, ownership_column='user_id'):
    return query.filter(getattr(query.model, ownership_column) == user_id)
