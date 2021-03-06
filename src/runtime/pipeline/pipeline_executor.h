/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

/*!
 * \brief pipeline executor
 * \file pipeline_executor.h
 */
#ifndef TVM_RUNTIME_PIPELINE_PIPELINE_EXECUTOR_H_
#define TVM_RUNTIME_PIPELINE_PIPELINE_EXECUTOR_H_

#include <tvm/runtime/registry.h>

#include <array>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "pipeline_scheduler.h"
namespace tvm {
namespace runtime {
/*!
 * \brief pipeline executor.
 *  This executor class use the module list and dependency configuration of modules as
 *  the parameters and executes these modules on heterogeneous targets in a pipeline
 *  parallel manner to improve throughput.
 *
 *  This executor can be accessed by various language via TVM runtime PackedFunc API.
 */
class TVM_DLL PipelineExecutor : public ModuleNode {
 public:
  /*!
   * \Return the type key of the executor.
   */
  const char* type_key() const final { return "PipelineExecutor"; }
  /*!
   * \brief Initialize the pipeline executor with module array and JSON text.
   * \param modules The module list used for building pipeline.
   * \param pipeline_json The configuration of modules dependencies.
   */
  void Init(const std::vector<Module>& modules, const std::string& pipeline_json);
  /*!
   * \brief Use the information of mod_config to create a list of graph executor.
   * \param mod_config The configuration information generated by the library export function call.
   */
  std::vector<Module> CreateGraphModules(const ModuleConfig& mod_config);
  /*!
   * \brief Give frontends an access to packed functions.
   * \param name The name of the function.
   * \param sptr_to_self The pointer to the module node.
   * \return The corresponding packed function.
   */
  virtual PackedFunc GetFunction(const std::string& name, const ObjectPtr<Object>& sptr_to_self);

  /*!
   * \brief Get the number of outputs.
   *
   * \return The number of outputs.
   */
  int NumOutputs() const { return num_outputs_; }

  /*!\brief Load the module files information.*/
  ModuleConfig& LoadModuleConfig(dmlc::JSONReader* reader) {
    reader->BeginArray();
    while (reader->NextArrayItem()) {
      std::string key;
      reader->BeginObject();
      int mod_idx = -1;
      std::string lib_name;
      std::string json_name;
      std::string params_name;
      std::string dev;
      while (reader->NextObjectItem(&key)) {
        if (key == "mod_idx") {
          reader->Read(&mod_idx);
        } else if (key == "lib_name") {
          reader->Read(&lib_name);
        } else if (key == "json_name") {
          reader->Read(&json_name);
        } else if (key == "params_name") {
          reader->Read(&params_name);
        } else if (key == "dev") {
          reader->Read(&dev);
        } else {
          LOG(FATAL) << "do not support key " << key;
        }
      }
      ICHECK(mod_idx >= 0) << "Invalid mod_idx value " << mod_idx;
      // Load the lib, json, and params information.
      ICHECK(!lib_name.empty()) << "lib_name is empty.";
      ICHECK(!json_name.empty()) << "json_name is empty.";
      ICHECK(!params_name.empty()) << "params_name is empty.";
      mod_config_[mod_idx] = GraphModuleLoadInfo(lib_name, json_name, params_name, dev);
    }
    return mod_config_;
  }

 private:
  /*!\brief The class used to execute and schedule the pipeline logic.*/
  PipelineScheduler pipeline_scheduler_;
  /*!\brief The dependency information of each graph runtime module of the pipeline.*/
  PipelineConfig pipeline_config_;
  /*!\brief The module information used to create the graph runtimes.*/
  ModuleConfig mod_config_;
  /*!\brief How many outputs are in this pipeline executor.*/
  size_t num_outputs_ = 0;
  /*!\brief Json loader.*/
  PipelineConfig& LoadPipelineConfig(dmlc::JSONReader* reader) {
    reader->BeginArray();
    while (reader->NextArrayItem()) {
      std::string key;
      reader->BeginObject();
      int mod_idx = -1;
      OutputMap output;
      std::string dev;
      while (reader->NextObjectItem(&key)) {
        if (key == "mod_idx") {
          reader->Read(&mod_idx);
        } else if (key == "dev") {
          reader->Read(&dev);
        } else if (key == "output") {
          reader->Read(&output);
        } else {
          LOG(FATAL) << "do not support key " << key;
        }
      }
      ICHECK(mod_idx >= 0) << "Invalid mod_idx value " << mod_idx;
      // Check if the output is successfully read.
      ICHECK(!output.Empty()) << "Invalid output binding result.";
      pipeline_config_.Insert(mod_idx, output);
    }
    return pipeline_config_;
  }
};
}  // namespace runtime
}  // namespace tvm
#endif  // TVM_RUNTIME_PIPELINE_PIPELINE_EXECUTOR_H_
