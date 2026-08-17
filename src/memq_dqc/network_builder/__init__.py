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

"""Browser-based editor for authoring memq_dqc network JSON files.

This subpackage ships a small local web application. It is a convenience
tool, not part of the compiler: it produces the same network JSON that
[memq_dqc.network.NetworkGraph][memq_dqc.network.network_graph.NetworkGraph] consumes, so nothing here is imported
by the compilation pipeline.

Launch it with the ``network-builder`` console script:

```bash
uv run network-builder
```

The module deliberately exports nothing at import time so that
``import memq_dqc`` never requires the optional Flask dependency.
"""
