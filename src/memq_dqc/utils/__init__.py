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

"""Internal helpers shared across memq_dqc.

This subpackage is **not** part of the public API. Its contents are
implementation details of the partitioners and circuit builders, and may
change without notice. Import them from their defining modules
(``memq_dqc.utils.circuit_utils``, ``memq_dqc.utils.common``) rather than from this
package, and prefer the documented entry points in [memq_dqc][memq_dqc] for anything
user-facing.
"""
