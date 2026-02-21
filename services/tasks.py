import os
import json
import redis
import inspect
from celery import shared_task
from ai_engine import get_model_function
from utils.logger_config import logger

@shared_task(bind=True, name='ai.generate')
def generate_ai_response(self, channel_id, model_name, db_user_id, user_data):
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = redis.from_url(redis_url)

    logger.info(f"Starting AI task for model {model_name} on channel {channel_id}")

    model_func = get_model_function(model_name)
    if not model_func:
        error_msg = json.dumps({"error": f"Model {model_name} not found"})
        r.publish(channel_id, error_msg)
        r.publish(channel_id, "DONE")
        return

    try:
        if inspect.isgeneratorfunction(model_func):
            for chunk in model_func(db_user_id, user_data):
                if isinstance(chunk, dict):
                    msg = json.dumps(chunk)
                else:
                    msg = str(chunk)
                r.publish(channel_id, msg)
        else:
            result = model_func(db_user_id, user_data)
            if isinstance(result, dict):
                r.publish(channel_id, json.dumps(result))
            else:
                r.publish(channel_id, str(result))

    except Exception as e:
        logger.error(f"Error in background AI task: {e}", exc_info=True)
        r.publish(channel_id, json.dumps({"error": str(e)}))
    finally:
        r.publish(channel_id, "DONE")
