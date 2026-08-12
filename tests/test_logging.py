# Copyright 2026 memQ Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging

from xdqc._logging import workflow_logging


def test_workflow_logging_restores_logger_state_after_repeated_calls() -> None:
    logger = logging.getLogger("xdqc")
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
