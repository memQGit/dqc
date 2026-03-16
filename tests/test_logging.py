import logging

from memq_dqc._logging import workflow_logging


def test_workflow_logging_restores_logger_state_after_repeated_calls() -> None:
    logger = logging.getLogger("memq_dqc")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate

    logger.handlers = []
    logger.setLevel(logging.NOTSET)
    logger.propagate = False

    try:
        with workflow_logging("info"):
            assert len(logger.handlers) == 1
            first_handler = logger.handlers[0]

        assert logger.handlers == []

        with workflow_logging("info"):
            assert len(logger.handlers) == 1
            second_handler = logger.handlers[0]

        assert logger.handlers == []
        assert first_handler is not second_handler
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate
