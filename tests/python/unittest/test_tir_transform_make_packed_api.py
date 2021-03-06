# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import numpy

import tvm
from tvm import te
from tvm.driver.build_module import schedule_to_module


def test_makeapi():
    """Not yet working, mock design"""
    n = te.size_var("n")
    A = te.placeholder((n,), name="A")
    B = te.placeholder((n,), name="B")
    C = te.compute(A.shape, lambda *i: A(*i) + B(*i), name="C")
    s = te.create_schedule(C.op)

    mod = schedule_to_module(s, [n, A, B, C])
    mod = tvm.tir.transform.StorageFlatten(64)(mod)
    mod = tvm.tir.transform.Apply(
        lambda f: f.with_attr(
            {
                "target": tvm.target.Target("llvm"),
                "global_symbol": "main",
            }
        )
    )(mod)

    num_unpacked_args = 2
    f = tvm.tir.transform.MakePackedAPI(num_unpacked_args)(mod)["main"]
    assert len(f.params) == 8


if __name__ == "__main__":
    test_makeapi()
