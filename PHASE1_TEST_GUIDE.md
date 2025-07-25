# Phase 1 测试指南 - LLM Agent基础框架

## 🎯 测试目标

验证LLM Agent基础框架能够：
1. ✅ 连接MQTT并订阅所有相关topics
2. ✅ 接收并解析工厂状态消息
3. ✅ 生成自然语言事件描述
4. ✅ 发送简单的AGV控制命令
5. ✅ 与现有仿真系统兼容

## 🚀 测试步骤

### 步骤 1: 安装依赖

```bash
# 确保在项目根目录
cd /Users/zhaojiace/Documents/AgenticFactoria/test/25-AdventureX-SUPCON-Hackathon

# 同步依赖（包含新的LLM依赖）
uv sync
```

### 步骤 2: 启动工厂仿真

在第一个终端窗口启动工厂仿真：

```bash
# 启动多线仿真环境（不启用故障，启用交互菜单）
export TOPIC_ROOT="NLDF_MACOS_TEST"
uv run run_multi_line_simulation.py --menu --no-fault
```

等待看到以下输出：
```
🏭 Initializing Multi-Line Factory Simulation...
✅ Factory created with 3 production lines
📋 Order generation, fault system, and KPI calculation initialized
🎯 Command handler initialized and listening for agent commands
🚀 Starting Factory Simulation...
Interactive menu enabled. Type commands in the console.
```

### 步骤 3: 测试状态收集器（独立测试）

在第二个终端窗口运行状态收集器测试：

```bash
export TOPIC_ROOT="NLDF_MACOS_TEST"
uv run test_llm_agent.py
```

**预期输出**：
```
🧪 测试状态收集器...
AGV状态: {'unknown_AGV_1': {'device_id': 'AGV_1', 'status': 'idle', ...}}
工厂概览: {'total_agvs': 1, 'total_stations': 1, ...}
✅ 状态收集器测试完成
```

### 步骤 4: 测试完整LLM Agent

继续在第二个终端运行完整测试：

```bash
# 如果上一步没有运行完整测试，单独运行LLM Agent测试
export TOPIC_ROOT="NLDF_MACOS_TEST"
uv run python -m src.llm_agent.base_agent
```

**预期行为**：
1. LLM Agent连接到MQTT broker
2. 订阅所有工厂状态topics
3. 开始接收和处理状态消息
4. 每5秒做一次简单决策
5. 发送基础AGV移动命令

**预期输出示例**：
```
INFO - LLM Factory Agent initialized with topic root: NLDF_MACOS_TEST
INFO - Starting LLM Factory Agent...
INFO - MQTT connection established
INFO - Subscribed to all factory status topics
INFO - LLM Factory Agent started successfully
INFO - Making decision...
INFO - Sent 1 commands
```

### 步骤 5: 验证MQTT通信

在第三个终端窗口运行MQTT监控：

```bash
# 监控MQTT消息（如果有mosquitto客户端）
mosquitto_sub -h supos-ce-instance4.supos.app -p 1883 -t "NLDF_MACOS_TEST/+/+/+/+"

# 或者使用Python脚本监控
python -c "
import paho.mqtt.client as mqtt
import time

def on_message(client, userdata, msg):
    print(f'{msg.topic}: {msg.payload.decode()}')

client = mqtt.Client('monitor')
client.on_message = on_message
client.connect('supos-ce-instance4.supos.app', 1883, 60)
client.subscribe('NLDF_MACOS_TEST/+/+/+/+')
client.loop_forever()
"
```

### 步骤 6: 集成测试（启用LLM Agent的仿真）

停止之前的仿真，启动带LLM Agent的完整仿真：

```bash
export TOPIC_ROOT="NLDF_MACOS_TEST"
uv run run_multi_line_simulation.py --menu --no-fault --enable-llm-agent
```

**预期输出**：
```
🏭 Initializing Multi-Line Factory Simulation...
🤖 LLM Agent initialized
🚀 Starting Factory Simulation...
🤖 Starting LLM Agent...
🤖 LLM Agent started successfully
```

## ✅ 成功标准

### 基础功能验证
- [ ] LLM Agent能成功连接MQTT
- [ ] 能订阅所有相关topics（AGV、Station、Conveyor状态）
- [ ] 能接收并解析状态消息
- [ ] 能生成自然语言事件描述
- [ ] 能发送格式正确的命令到MQTT

### 状态管理验证
- [ ] StateCollector能正确存储和管理设备状态
- [ ] 能检测状态变化并生成相应事件
- [ ] 能提供工厂概览和生产线摘要
- [ ] 事件历史管理正常（保持最近30条）

### 命令发送验证
- [ ] 能生成符合AgentCommand schema的命令
- [ ] 命令能成功发送到正确的topic
- [ ] 仿真系统能接收并执行命令
- [ ] 系统响应能正确返回

### 集成验证
- [ ] LLM Agent与现有仿真系统兼容
- [ ] 不影响现有的命令处理和菜单功能
- [ ] 能与MultiLineCommandHandler共存
- [ ] 系统稳定运行无崩溃

## 🐛 常见问题排除

### 问题1: MQTT连接失败
```
ConnectionError: MQTT connection timeout
```

**解决方案**：
- 检查网络连接
- 确认MQTT broker地址正确
- 检查防火墙设置

### 问题2: 导入错误
```
ImportError: No module named 'src.llm_agent'
```

**解决方案**：
```bash
# 确保在正确目录
pwd  # 应该显示项目根目录
# 重新同步依赖
uv sync
# 检查模块路径
python -c "import sys; print(sys.path)"
```

### 问题3: 没有收到状态消息
```
收集到的AGV状态数: 0
```

**解决方案**：
- 确保工厂仿真正在运行
- 检查topic名称是否匹配（TOPIC_ROOT）
- 验证MQTT连接状态

### 问题4: 命令发送失败
```
Error sending command: ...
```

**解决方案**：
- 检查AgentCommand schema验证
- 确认topic格式正确
- 验证MQTT客户端权限

## 📊 性能基准

在正常运行状态下，期望的性能指标：

- **MQTT连接时间**: < 3秒
- **状态消息处理延迟**: < 100ms
- **决策生成间隔**: 5秒（可配置）
- **内存使用**: < 100MB
- **CPU使用**: < 5%（空闲时）

## 🔄 下一步

Phase 1测试通过后，可以进入**Phase 2: Preprocess层实现**：

1. 实现事件过滤和智能筛选
2. 添加自然语言转换增强
3. 实现上下文管理和压缩
4. 准备集成真正的LLM API

## 📝 测试报告模板

```
Phase 1 测试报告
==================

测试时间: ___________
测试环境: macOS / Python _____
测试人员: ___________

基础功能测试:
□ MQTT连接: ✅/❌
□ 状态接收: ✅/❌  
□ 命令发送: ✅/❌
□ 系统集成: ✅/❌

发现问题:
1. _________________
2. _________________

性能表现:
- 连接时间: _____ 秒
- 内存使用: _____ MB
- 消息处理: _____ 条/秒

总体评价: ✅通过 / ❌未通过

备注: _______________
```

---

**🎉 准备好开始测试了吗？按照上面的步骤逐一验证LLM Agent基础框架！** 