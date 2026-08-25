try:
    from celery import shared_task
except ImportError:  # Local environments may run without the optional worker package.
    shared_task = None


if shared_task is not None:

    @shared_task(bind=True, name="mapping.process_map_request")
    def process_map_request_task(self, map_request_id, run_id=None):
        from .views import _process_map_request_in_background

        return _process_map_request_in_background(map_request_id, run_id)


    @shared_task(bind=True, name="mapping.continue_conversation")
    def continue_conversation_task(
        self, map_request_id, message_text, run_id=None, include_clarification_context=False
    ):
        from .views import _continue_conversation_in_background

        return _continue_conversation_in_background(
            map_request_id, message_text, run_id, include_clarification_context
        )

else:
    process_map_request_task = None
    continue_conversation_task = None
