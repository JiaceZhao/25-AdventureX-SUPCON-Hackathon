# LLM智能体系统分步实现路线图

## 🎯 总体目标
基于现有SUPCON工厂仿真平台，集成LLM驱动的智能决策系统，实现自然语言理解的工厂调度。

## 📋 现有代码分析

### 核心组件梳理
```
现有架构:
├── MQTT通信层
│   ├── MQTTClient (src/utils/mqtt_client.py)
│   ├── TopicManager (src/utils/topic_manager.py) 
│   └── MultiLineCommandHandler (src/agent_interface/multi_line_command_handler.py)
├── 仿真引擎
│   ├── Factory (src/simulation/factory_multi.py)
│   ├── Line (src/simulation/line.py)
│   └── 设备实体 (src/simulation/entities/)
├── 游戏逻辑
│   ├── OrderGenerator (src/game_logic/order_generator.py)
│   ├── KPICalculator (src/game_logic/kpi_calculator.py)
│   └── FaultSystem (src/game_logic/fault_system.py)
└── 配置系统
    ├── Schemas (config/schemas.py)
    └── Settings (config/settings.py)
```

### 关键接口分析
1. **MQTT Topics结构**:
   ```
   NLDF_TEST/
   ├── line{1,2,3}/
   │   ├── agv/{AGV_1,AGV_2}/status
   │   ├── station/{StationA,B,C,QualityCheck}/status  
   │   ├── conveyor/{Conveyor_AB,BC,CQ}/status
   │   └── alerts
   ├── warehouse/{RawMaterial,Warehouse}/status
   ├── orders/status
   ├── kpi/status
   ├── command/{line_id}     # 我们发送命令的地方
   └── response/{line_id}    # 系统响应的地方
   ```

2. **命令格式** (AgentCommand schema):
   ```json
   {
     "command_id": "optional_string", 
     "action": "move|load|unload|charge|get_result",
     "target": "AGV_1",
     "params": {"target_point": "P0"}
   }
   ```

3. **设备状态格式** (各种Status schemas):
   - AGVStatus: 位置、电量、载货、状态
   - StationStatus: 状态、缓冲区、统计
   - ConveyorStatus: 状态、缓冲区
   - WarehouseStatus: 缓冲区、统计

## 🚀 分阶段实施计划

### Phase 1: 基础框架搭建 (第1-2天)
**目标**: 创建LLM Agent骨架，能够监听MQTT并发送简单命令

#### Step 1.1: 创建LLM Agent基础类
```python
# 新文件: src/llm_agent/base_agent.py
class LLMFactoryAgent:
    - MQTT连接和监听
    - 基础状态管理
    - 简单命令发送
```

#### Step 1.2: 实现状态收集器
```python  
# 新文件: src/llm_agent/state_collector.py
class StateCollector:
    - 订阅所有相关MQTT topics
    - 维护完整的工厂状态快照
    - 基础事件过滤
```

#### Step 1.3: 集成现有系统
- 修改run_multi_line_simulation.py，支持启动LLM Agent
- 确保与现有MultiLineCommandHandler兼容

**测试验证**: LLM Agent能正常启动，收到MQTT消息，发送简单move命令

### Phase 2: Preprocess层实现 ✅ **已完成**
**目标**: 将MQTT状态转换为自然语言描述

#### Step 2.1: 事件转换器 ✅
```python
# 实现在: src/llm_agent/state_collector.py
- AGV状态 → "AGV AGV_1 从 空闲 转为 移动中，位置从 P0 变为 P1"
- 电量变化 → "AGV AGV_2 电量从 20.0% 变为 5.0% ⚠️ 紧急电量警告！立即充电"
- 传送带状态 → "传送带 conveyor_1 被阻塞，当前缓冲区有 2 个产品"
- 载货变化 → "AGV AGV_1 装载了 1 个产品，当前载货 1 个"
```

#### Step 2.2: 智能事件过滤 ✅
```python
class EventFilter (在StateCollector中实现):
    - ✅ 过滤重复/无关事件 (基于dedupe_key)
    - ✅ 电量变化>10%才报告 (可配置阈值)
    - ✅ 状态变化总是报告 (重要性评估)
    - ✅ 事件重要性评分 (5级: CRITICAL, HIGH, MEDIUM, LOW, NOISE)
    - ✅ 频率限制 (根据重要性调整过滤窗口)
```

#### Step 2.3: 上下文管理器 ✅
```python
class ContextManager (在StateCollector中实现):
    - ✅ 维护最近200个事件 (按重要性保留)
    - ✅ 事件重要性评分和优先级处理
    - ✅ 上下文压缩优化 (智能清理过期数据)
    - ✅ LLM就绪的结构化数据接口
    - ✅ 趋势分析和历史管理
```

**测试验证**: ✅ 6/6项测试全部通过
- ✅ 基础事件过滤: 电量阈值、状态变化检测  
- ✅ 自然语言生成: 警告信息、中文描述质量
- ✅ 事件重要性过滤: 多级分类、优先级处理
- ✅ 上下文管理: LLM上下文生成、工厂概览
- ✅ 事件去重: 重复检测、时间窗口管理
- ✅ 趋势分析: 电量趋势、历史分析

**成果文件**:
- `src/llm_agent/state_collector.py` (增强版StateCollector)
- `test_phase2_state_collector.py` (完整测试套件)
- `PHASE2_COMPLETION_SUMMARY.md` (详细报告)

### Phase 3: LLM Brain层实现 (第5-7天)
**目标**: 集成大模型决策能力

#### Step 3.1: LLM客户端封装
```python
# 新文件: src/llm_agent/llm_client.py  
class LLMClient:
    - 支持OpenAI GPT-4
    - 支持Anthropic Claude
    - 支持本地模型(可选)
    - 错误处理和重试
```

#### Step 3.2: Prompt工程
```python
# 新文件: src/llm_agent/prompts.py
class PromptManager:
    - 系统Prompt: 工厂布局、KPI目标、操作规则
    - Few-shot示例: 典型决策场景
    - 动态上下文: 当前状态+最近事件
```

#### Step 3.3: 决策引擎
```python
# 新文件: src/llm_agent/decision_engine.py
class DecisionEngine:
    - 构建完整prompt
    - 调用LLM API
    - 解析JSON响应
    - 决策历史管理
```

**测试验证**: LLM能理解工厂状态，生成合理的JSON命令列表

### Phase 4: Post-Guard层实现 (第8-9天)
**目标**: 确保LLM生成的命令安全可执行

#### Step 4.1: 命令校验器
```python
# 新文件: src/llm_agent/post_guard.py
class CommandValidator:
    - JSON Schema校验 (使用现有AgentCommand)
    - 电量安全检查
    - 路径有效性检查  
    - 设备状态检查
```

#### Step 4.2: 安全规则引擎
```python
class SafetyRules:
    - 电量<10%强制充电
    - 防止无效路径移动
    - 避免命令冲突
    - 载货容量检查
```

#### Step 4.3: 降级策略
```python  
class FallbackStrategy:
    - LLM失败时的安全命令
    - 紧急情况处理
    - 基础运输任务生成
```

**测试验证**: 能过滤不安全命令，LLM失败时有合理降级

### Phase 5: 系统集成优化 (第10-12天)
**目标**: 完整集成，性能优化

#### Step 5.1: LangGraph工作流
```python
# 新文件: src/llm_agent/workflow.py
- 使用LangGraph定义完整决策流程
- Preprocess → LLM Brain → Post-Guard → MQTT Publish
- 循环处理和错误恢复
```

#### Step 5.2: 批量决策优化
```python
class BatchManager:
    - 紧急事件立即处理
    - 常规事件批量处理(5秒间隔)
    - 事件重要性分级
```

#### Step 5.3: 成本控制
```python
class CostManager:
    - API调用成本监控
    - 预算控制机制
    - 降级策略触发
```

**测试验证**: 完整系统能稳定运行，响应时间<3秒，API成本可控

### Phase 6: 监控与调试 (第13-14天)
**目标**: 可观测性和持续改进

#### Step 6.1: 决策日志系统
```python
# 新文件: src/llm_agent/logging.py
class DecisionLogger:
    - 记录每次决策的完整上下文
    - 命令执行结果跟踪
    - KPI变化分析
```

#### Step 6.2: 性能监控
```python
class PerformanceMonitor:
    - 决策响应时间
    - LLM API成功率
    - 命令执行成功率
    - KPI趋势分析
```

#### Step 6.3: A/B测试框架
```python
class ABTestManager:
    - 多种决策策略对比
    - 性能指标收集
    - 自动策略切换
```

**测试验证**: 有完整的可观测性，能分析决策效果并持续优化

## 📂 新增文件结构

```
src/
├── llm_agent/              # 新增LLM智能体模块
│   ├── __init__.py
│   ├── base_agent.py       # LLM Agent主类
│   ├── state_collector.py  # 状态收集器
│   ├── preprocess.py       # 事件转换为自然语言
│   ├── llm_client.py       # LLM API客户端
│   ├── prompts.py          # Prompt管理
│   ├── decision_engine.py  # 决策引擎
│   ├── post_guard.py       # 安全校验
│   ├── workflow.py         # LangGraph工作流
│   ├── logging.py          # 决策日志
│   └── utils.py            # 工具函数
├── agent_interface/        # 现有的命令处理
├── simulation/             # 现有的仿真引擎
└── ...
```

## 🧪 每阶段测试策略

### Phase 1测试
```bash
# 启动仿真环境
uv run run_multi_line_simulation.py --menu --no-mqtt

# 启动LLM Agent (新)
uv run python -m src.llm_agent.base_agent --test-mode

# 验证: Agent能收到状态更新，发送基础命令
```

### Phase 2-3测试  
```bash
# 单元测试事件转换
pytest src/llm_agent/test_preprocess.py

# 集成测试LLM决策
pytest src/llm_agent/test_decision_engine.py

# 验证: 自然语言转换正确，LLM生成合理命令
```

### Phase 4-6测试
```bash
# 完整系统测试
uv run python -m src.llm_agent.main --full-mode

# 性能测试
python scripts/performance_test.py

# 验证: 完整流程稳定，KPI指标达标
```

## ⚡ 关键技术决策

### 1. LLM选择
- **主力**: OpenAI GPT-4 (稳定可靠)
- **备选**: Anthropic Claude-3 (推理能力强)
- **降级**: GPT-3.5-turbo (成本控制)

### 2. 依赖管理
```toml
# pyproject.toml 新增依赖
dependencies = [
    # 现有依赖...
    "openai>=1.0.0",
    "anthropic>=0.8.0", 
    "langgraph>=0.0.20",
    "langchain>=0.1.0",
    "tiktoken>=0.5.0",   # token计算
    "tenacity>=8.0.0",   # 重试机制
]
```

### 3. 配置扩展
```python
# config/settings.py 扩展
# LLM配置
LLM_PROVIDER = "openai"  # openai, anthropic, local
LLM_MODEL = "gpt-4"
LLM_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MAX_TOKENS = 1000
LLM_TEMPERATURE = 0.1

# Agent配置  
AGENT_DECISION_INTERVAL = 5.0  # 决策间隔秒
AGENT_CONTEXT_LENGTH = 30      # 保留事件数
AGENT_DAILY_BUDGET = 50.0      # 每日API预算美元
```

## 🎯 成功指标

### 技术指标
- [ ] 系统稳定性 >99%
- [ ] 决策响应时间 <3秒  
- [ ] LLM API成功率 >95%
- [ ] 命令执行成功率 >90%

### 业务指标
- [ ] KPI总分 >80分
- [ ] 订单完成率 >85%
- [ ] AGV主动充电率 >80%
- [ ] 设备利用率 >70%

### 成本指标
- [ ] 每日API成本 <$30
- [ ] 每次决策成本 <$0.05
- [ ] token使用效率 >80%

## 🚀 实施进度

### ✅ Phase 1: 基础框架搭建 (已完成)

#### ✅ Step 1.1: LLM Agent基础类 (已完成)
- ✅ 创建 `src/llm_agent/base_agent.py`
- ✅ 实现 MQTT连接和监听
- ✅ 实现基础状态管理
- ✅ 实现简单命令发送

#### ✅ Step 1.2: 状态收集器 (已完成) 
- ✅ 创建 `src/llm_agent/state_collector.py`
- ✅ 订阅所有相关MQTT topics
- ✅ 维护完整的工厂状态快照
- ✅ 实现基础事件过滤

#### ✅ Step 1.3: 系统集成 (已完成)
- ✅ 修改 `run_multi_line_simulation.py`，支持启动LLM Agent
- ✅ 添加 `--enable-llm-agent` 命令行参数
- ✅ 确保与现有MultiLineCommandHandler兼容
- ✅ 更新依赖配置 (`pyproject.toml`, `config/settings.py`)

#### ✅ Phase 1 测试材料
- ✅ 创建 `test_llm_agent.py` 测试脚本
- ✅ 创建 `PHASE1_TEST_GUIDE.md` 详细测试指南
- ✅ 提供完整的故障排除指南

### 📋 当前状态
**Phase 1 开发完成！** 基础LLM Agent框架已就绪，可以进行测试验证。

### 🔄 下一步行动

**立即行动**: 按照 [`PHASE1_TEST_GUIDE.md`](./PHASE1_TEST_GUIDE.md) 进行完整测试

**测试命令**:
```bash
# 1. 启动仿真环境
export TOPIC_ROOT="NLDF_MACOS_TEST"  
uv run run_multi_line_simulation.py --menu --no-fault

# 2. 测试LLM Agent（新终端）
export TOPIC_ROOT="NLDF_MACOS_TEST"
uv run test_llm_agent.py

# 3. 集成测试（替换步骤1）
uv run run_multi_line_simulation.py --menu --no-fault --enable-llm-agent
```

**成功标准**: 
- ✅ LLM Agent能连接MQTT并接收状态
- ✅ 能发送简单AGV控制命令  
- ✅ 与现有系统无冲突运行
- ✅ 系统稳定性和性能符合要求

**测试通过后开始**: **Phase 2: Preprocess层实现** 