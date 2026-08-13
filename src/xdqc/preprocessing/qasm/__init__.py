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

"""OpenQASM 3 preprocessing.

The public surface here is the set of entry points for getting an OpenQASM 3
program in and out of xdqc, plus :class:`CircuitQubit`, the qubit reference
those programs are expressed in terms of.

The statement-cleaning helpers and the ``Cleaned*`` node types are
implementation details of the circuit builders. They remain importable from
their defining modules (``xdqc.preprocessing.qasm.analysis``, ``.ast_utils``,
``.cleaning``, ``.types``) but are not part of the supported API and may
change without notice.
"""

from xdqc.preprocessing.qasm.io import (
    dump_qasm_program,
    load_qasm_program,
    parse_qasm_file,
    parse_qasm_source,
)
from xdqc.preprocessing.qasm.types import CircuitQubit

__all__ = [
    "CircuitQubit",
    "dump_qasm_program",
    "load_qasm_program",
    "parse_qasm_file",
    "parse_qasm_source",
]
