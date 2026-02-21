def get_model_function(model_name: str):
    model_name_lower = model_name.lower()

    if model_name_lower == "gemini":
        from .gemini import gemini_stream
        return gemini_stream
    elif model_name_lower == "mindart":
        from .MindArt import MindArt_stream
        return MindArt_stream
    elif model_name_lower == "echo":
        from .echo import echo
        return echo
    elif model_name_lower == "echo_stream":
        from .echo import echo_stream
        return echo_stream

    return None
