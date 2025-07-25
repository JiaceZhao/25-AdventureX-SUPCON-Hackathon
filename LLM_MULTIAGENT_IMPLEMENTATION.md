# LLM驱动的工厂多智能体系统实现方案

## 1. 架构设计

### 1.1 三层架构详细设计

```
MQTT Events Stream → ┌─────────────────┐ → Natural Language Context
                     │   Preprocess    │   
                     │   (Rules 5%)    │   
                     └─────────────────┘   
                              ↓
                     ┌─────────────────┐ → JSON Commands List
                     │   LLM Brain     │   
                     │   (LLM 90%)     │   
                     └─────────────────┘   
                              ↓
                     ┌─────────────────┐ → Validated Commands
                     │   Post-Guard    │   
                     │   (Rules 5%)    │   
                     └─────────────────┘   
                              ↓
                        MQTT Publish
```

### 1.2 状态管理设计

```python
@dataclass
class FactoryState:
    # 原始状态数据
    mqtt_queue: List[MQTTEvent]
    world_state: Dict[str, Any]  # 完整的工厂状态
    
    # LLM上下文
    nl_context: List[str]  # 自然语言事件描述
    conversation_history: List[Dict]  # LLM对话历史
    
    # 决策状态
    pending_commands: List[Dict]
    last_decision_time: float
    
    # 性能监控
    kpi_summary: Dict[str, float]
    alerts: List[str]
```

## 2. Preprocess层实现

### 2.1 MQTT事件到自然语言转换

```python
class PreprocessNode:
    def __init__(self):
        self.templates = {
            "agv_status": self._agv_status_to_nl,
            "station_status": self._station_status_to_nl,
            "order_new": self._order_to_nl,
            "fault_alert": self._fault_to_nl,
            "kpi_update": self._kpi_to_nl
        }
    
    def _agv_status_to_nl(self, data: dict) -> str:
        agv_id = data["source_id"]
        line_id = data.get("line_id", "unknown")
        status = data["status"]
        battery = data["battery_level"]
        position = data["current_point"]
        payload = data.get("payload", [])
        
        # 电量状态描述
        battery_desc = ""
        if battery < 15:
            battery_desc = "🔋 电量危险低"
        elif battery < 30:
            battery_desc = "⚡ 电量较低"
        
        # 负载状态描述
        load_desc = ""
        if payload:
            load_desc = f"携带产品{len(payload)}个: {', '.join(payload)}"
        else:
            load_desc = "空载"
        
        # 状态描述
        status_desc = {
            "idle": "空闲中",
            "moving": f"移动中→{data.get('target_point', '?')}",
            "charging": "充电中",
            "interacting": "装卸货中",
            "fault": "⚠️ 故障"
        }.get(status, status)
        
        return f"[{line_id}] {agv_id} 在{position} {status_desc} {load_desc} {battery_desc}({battery:.0f}%)"
    
    def _station_status_to_nl(self, data: dict) -> str:
        station_id = data["source_id"]
        line_id = data.get("line_id", "unknown")
        status = data["status"]
        buffer = data.get("buffer", [])
        
        status_desc = {
            "idle": "空闲",
            "processing": "生产中",
            "blocked": "🚫 被阻塞",
            "fault": "⚠️ 故障"
        }.get(status, status)
        
        buffer_desc = f"缓冲区{len(buffer)}个产品" if buffer else "缓冲区空"
        
        return f"[{line_id}] {station_id} {status_desc} {buffer_desc}"
    
    def _order_to_nl(self, data: dict) -> str:
        order_id = data["order_id"]
        items = data["items"]
        priority = data["priority"]
        deadline = data["deadline"]
        current_time = data.get("created_at", 0)
        
        items_desc = ", ".join([f"{item['quantity']}个{item['product_type']}" for item in items])
        time_left = deadline - current_time
        priority_desc = {"high": "🔥高优先级", "medium": "⚡中优先级", "low": "普通"}.get(priority, priority)
        
        return f"📋 新订单{order_id}: {items_desc} {priority_desc} 剩余{time_left:.0f}秒"
    
    def _fault_to_nl(self, data: dict) -> str:
        device_id = data["device_id"]
        line_id = data.get("line_id", "unknown")
        alert_type = data["alert_type"]
        symptom = data.get("symptom", "未知故障")
        
        if alert_type == "fault_recovered":
            return f"✅ [{line_id}] {device_id} 故障已恢复"
        else:
            return f"🚨 [{line_id}] {device_id} 发生故障: {symptom}"
    
    def _kpi_to_nl(self, data: dict) -> str:
        order_rate = data.get("order_completion_rate", 0)
        cycle_eff = data.get("average_production_cycle", 0)
        device_util = data.get("device_utilization", 0)
        
        # 只在KPI显著变化时生成描述
        if abs(order_rate - self.last_kpi.get("order_rate", 0)) > 5:
            return f"📊 订单完成率: {order_rate:.1f}%, 生产周期: {cycle_eff:.2f}, 设备利用率: {device_util:.1f}%"
        
        return None

    def process(self, state: FactoryState) -> FactoryState:
        """处理MQTT事件队列，转换为自然语言描述"""
        new_events = []
        
        while state.mqtt_queue:
            event = state.mqtt_queue.pop(0)
            
            # 根据事件类型转换为自然语言
            topic_parts = event.topic.split('/')
            event_type = self._classify_event(topic_parts, event.payload)
            
            if event_type in self.templates:
                nl_desc = self.templates[event_type](event.payload)
                if nl_desc:  # 过滤掉None
                    new_events.append(nl_desc)
        
        # 更新状态
        state.nl_context.extend(new_events)
        
        # 保持上下文长度合理（最近30条事件）
        if len(state.nl_context) > 30:
            state.nl_context = state.nl_context[-30:]
        
        return state
```

### 2.2 智能事件过滤

```python
class EventFilter:
    def __init__(self):
        self.last_states = {}
        self.significance_threshold = {
            "battery_change": 10,  # 电量变化>10%才报告
            "position_change": True,  # 位置变化总是重要
            "status_change": True,   # 状态变化总是重要
            "buffer_change": True    # 缓冲区变化总是重要
        }
    
    def is_significant(self, event_type: str, old_value, new_value) -> bool:
        """判断事件是否值得报告给LLM"""
        if event_type == "battery_change":
            return abs(new_value - old_value) >= self.significance_threshold[event_type]
        return self.significance_threshold.get(event_type, True)
```

## 3. LLM Brain层实现

### 3.1 核心Prompt设计

```python
SYSTEM_PROMPT = """
你是SUPCON智能工厂的中央调度AI，负责协调3条生产线(line1/line2/line3)的运营。

## 工厂布局
- 3条并行生产线，每条有：StationA→StationB→StationC→QualityCheck，及2台AGV
- 共享设施：RawMaterial(原料仓库)、Warehouse(成品仓库)  
- AGV路径点：P0(原料)→P1(StationA)→P2(传送带AB)→P3(StationB)→P4(传送带BC)→P5(StationC)→P6(传送带CQ)→P7(质检输入)→P8(质检输出)→P9(仓库)→P10(充电)

## 产品工艺流程
- P1/P2标准流程：RawMaterial→StationA→StationB→StationC→QualityCheck→Warehouse
- P3特殊流程：需要在StationB/StationC间额外循环一次

## KPI优化目标 (权重)
1. 生产效率 (40%): 订单按时完成率、生产周期效率、设备利用率
2. 质量成本 (30%): 一次通过率、成本控制  
3. AGV效率 (30%): 主动充电策略、能效比、利用率

## 可用指令
- move: AGV移动到指定路径点
- load: AGV在当前位置装货
- unload: AGV在当前位置卸货  
- charge: AGV主动充电到指定电量

## 决策原则
1. 优先处理高优先级订单和即将超期的订单
2. 保持各生产线负载均衡
3. AGV电量<30%时考虑主动充电
4. 故障发生时快速重新分配任务
5. 最大化设备利用率，避免缓冲区溢出

## 响应格式
返回JSON数组，每个指令包含action/target/params字段。同时在reasoning字段简述决策逻辑。

示例：
{
  "commands": [
    {"action": "move", "target": "AGV_1", "params": {"target_point": "P0"}},
    {"action": "load", "target": "AGV_1", "params": {}},
    {"action": "charge", "target": "AGV_2", "params": {"target_level": 80}}
  ],
  "reasoning": "AGV_1去取新订单原料，AGV_2电量低先充电避免任务中断"
}
"""

class LLMBrain:
    def __init__(self, provider="openai", model="gpt-4"):
        self.provider = provider
        self.model = model
        self.client = self._init_client()
        
    def _build_context_prompt(self, state: FactoryState) -> str:
        """构建当前状态的上下文prompt"""
        
        # 最新状态摘要
        current_status = self._summarize_current_state(state.world_state)
        
        # 最近事件
        recent_events = "\n".join(state.nl_context[-10:]) if state.nl_context else "无新事件"
        
        # KPI状态
        kpi_summary = self._summarize_kpi(state.kpi_summary)
        
        # 紧急情况提醒
        urgent_alerts = self._check_urgent_situations(state)
        
        context = f"""
## 当前工厂状态
{current_status}

## 最近事件 
{recent_events}

## KPI状态
{kpi_summary}

## 紧急情况
{urgent_alerts if urgent_alerts else "无紧急情况"}

基于上述信息，制定下一步行动计划。优先处理紧急情况，然后优化整体KPI。
"""
        return context
    
    def _summarize_current_state(self, world_state: dict) -> str:
        """将复杂的世界状态总结为易读格式"""
        summary = []
        
        # AGV状态摘要
        for line_id in ["line1", "line2", "line3"]:
            line_data = world_state.get(line_id, {})
            agv_status = []
            for agv_id in ["AGV_1", "AGV_2"]:
                agv = line_data.get("agvs", {}).get(agv_id, {})
                if agv:
                    pos = agv.get("current_point", "?")
                    battery = agv.get("battery_level", 0)
                    status = agv.get("status", "unknown")
                    payload = len(agv.get("payload", []))
                    agv_status.append(f"{agv_id}@{pos}({battery:.0f}%,载{payload})")
            
            summary.append(f"{line_id}: {', '.join(agv_status)}")
        
        # 订单队列状态
        orders = world_state.get("orders", {})
        active_orders = len(orders.get("active", []))
        pending_orders = len(orders.get("pending", []))
        summary.append(f"订单: 活跃{active_orders}个, 待处理{pending_orders}个")
        
        return "\n".join(summary)
    
    def _check_urgent_situations(self, state: FactoryState) -> str:
        """检查需要立即处理的紧急情况"""
        alerts = []
        
        # 检查低电量AGV
        for line_data in state.world_state.values():
            if isinstance(line_data, dict) and "agvs" in line_data:
                for agv_id, agv_data in line_data["agvs"].items():
                    battery = agv_data.get("battery_level", 100)
                    if battery < 15:
                        alerts.append(f"🔋 {agv_id} 电量危险({battery:.0f}%), 需要立即充电")
        
        # 检查故障设备
        for alert in state.alerts:
            if "故障" in alert:
                alerts.append(f"⚠️ {alert}")
        
        # 检查即将超期的订单
        current_time = state.world_state.get("current_time", 0)
        for order in state.world_state.get("orders", {}).get("active", []):
            deadline = order.get("deadline", float('inf'))
            if deadline - current_time < 60:  # 1分钟内到期
                alerts.append(f"⏰ 订单{order.get('order_id')} 即将超期")
        
        return "\n".join(alerts)
    
    async def process(self, state: FactoryState) -> FactoryState:
        """LLM决策处理"""
        context_prompt = self._build_context_prompt(state)
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context_prompt}
        ]
        
        # 添加对话历史（保持最近3轮）
        if state.conversation_history:
            messages.extend(state.conversation_history[-6:])  # 3轮对话 = 6条消息
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,  # 低温度确保稳定性
                max_tokens=1000
            )
            
            # 解析响应
            content = response.choices[0].message.content
            decision = json.loads(content)
            
            # 更新状态
            state.pending_commands = decision.get("commands", [])
            state.conversation_history.extend([
                {"role": "user", "content": context_prompt},
                {"role": "assistant", "content": content}
            ])
            
            # 记录决策reasoning用于调试
            if "reasoning" in decision:
                state.nl_context.append(f"🤖 AI决策: {decision['reasoning']}")
            
        except Exception as e:
            print(f"LLM处理错误: {e}")
            # 降级处理：生成安全的默认指令
            state.pending_commands = self._generate_safe_fallback_commands(state)
        
        return state
```

### 3.2 Few-Shot示例增强

```python
FEW_SHOT_EXAMPLES = """
## 决策示例

### 场景1: 新订单处理
状态: line1 AGV_1@P10(50%,载0), AGV_2@P1(80%,载0), 新订单order_123包含2个P1产品
决策:
{
  "commands": [
    {"action": "move", "target": "AGV_1", "params": {"target_point": "P0"}},
    {"action": "load", "target": "AGV_1", "params": {}},
    {"action": "move", "target": "AGV_1", "params": {"target_point": "P1"}},
    {"action": "unload", "target": "AGV_1", "params": {}}
  ],
  "reasoning": "AGV_1电量充足，派去取新订单原料送到StationA开始生产"
}

### 场景2: 电量管理
状态: line2 AGV_1@P3(25%,载1), 需要继续完成运输任务但电量不足
决策:
{
  "commands": [
    {"action": "move", "target": "AGV_1", "params": {"target_point": "P5"}},
    {"action": "unload", "target": "AGV_1", "params": {}},
    {"action": "move", "target": "AGV_1", "params": {"target_point": "P10"}},
    {"action": "charge", "target": "AGV_1", "params": {"target_level": 70}}
  ],
  "reasoning": "先完成当前运输任务，然后立即充电避免后续任务中断"
}

### 场景3: 故障应对
状态: line1 StationB故障，AGV_1@P3(60%,载1)准备卸货到故障工站
决策:
{
  "commands": [
    {"action": "move", "target": "AGV_1", "params": {"target_point": "P0"}},
    {"action": "unload", "target": "AGV_1", "params": {}},
    {"action": "move", "target": "AGV_1", "params": {"target_point": "P1"}},
    {"action": "load", "target": "AGV_1", "params": {}},
    {"action": "move", "target": "AGV_1", "params": {"target_point": "P3"}},
    {"action": "unload", "target": "AGV_1", "params": {}}
  ],
  "reasoning": "line2的StationB故障，将产品转移到line2的StationB继续生产"
}
"""
```

## 4. Post-Guard层实现

### 4.1 安全规则校验

```python
class PostGuard:
    def __init__(self):
        self.safety_rules = [
            self._validate_schema,
            self._check_battery_safety,
            self._validate_agv_position,
            self._check_payload_capacity,
            self._validate_device_availability,
            self._prevent_conflicting_commands
        ]
    
    def _validate_schema(self, commands: List[dict]) -> Tuple[List[dict], List[str]]:
        """JSON schema校验"""
        valid_commands = []
        errors = []
        
        for cmd in commands:
            try:
                # 使用pydantic校验
                validated_cmd = AgentCommand.model_validate(cmd)
                valid_commands.append(validated_cmd.model_dump())
            except Exception as e:
                errors.append(f"Schema错误: {cmd} - {e}")
        
        return valid_commands, errors
    
    def _check_battery_safety(self, commands: List[dict]) -> Tuple[List[dict], List[str]]:
        """电量安全检查"""
        safe_commands = []
        errors = []
        
        for cmd in commands:
            if cmd["action"] == "move":
                agv_id = cmd["target"]
                target_point = cmd["params"]["target_point"]
                
                # 检查电量是否足够移动
                current_battery = self._get_agv_battery(agv_id)
                if current_battery < 10:  # 危险电量阈值
                    # 强制充电
                    charge_cmd = {
                        "action": "charge",
                        "target": agv_id,
                        "params": {"target_level": 80}
                    }
                    safe_commands.append(charge_cmd)
                    errors.append(f"⚠️ {agv_id}电量过低({current_battery}%)，强制充电")
                    continue
            
            safe_commands.append(cmd)
        
        return safe_commands, errors
    
    def _validate_agv_position(self, commands: List[dict]) -> Tuple[List[dict], List[str]]:
        """AGV位置合法性检查"""
        safe_commands = []
        errors = []
        
        for cmd in commands:
            if cmd["action"] == "move":
                agv_id = cmd["target"]
                current_pos = self._get_agv_position(agv_id)
                target_pos = cmd["params"]["target_point"]
                
                # 检查路径是否存在
                if not self._is_path_valid(current_pos, target_pos):
                    errors.append(f"❌ {agv_id}无法从{current_pos}到达{target_pos}")
                    continue
            
            elif cmd["action"] in ["load", "unload"]:
                agv_id = cmd["target"]
                current_pos = self._get_agv_position(agv_id)
                
                # 检查当前位置是否可以执行该操作
                if not self._can_perform_operation(agv_id, current_pos, cmd["action"]):
                    errors.append(f"❌ {agv_id}在{current_pos}无法执行{cmd['action']}")
                    continue
            
            safe_commands.append(cmd)
        
        return safe_commands, errors
    
    def _prevent_conflicting_commands(self, commands: List[dict]) -> Tuple[List[dict], List[str]]:
        """防止命令冲突"""
        safe_commands = []
        errors = []
        agv_commands = {}
        
        for cmd in commands:
            agv_id = cmd["target"]
            
            # 每个AGV同一时间只能执行一个命令
            if agv_id in agv_commands:
                errors.append(f"⚠️ {agv_id}有冲突命令，保留第一个: {agv_commands[agv_id]['action']}")
                continue
            
            agv_commands[agv_id] = cmd
            safe_commands.append(cmd)
        
        return safe_commands, errors
    
    def process(self, state: FactoryState) -> FactoryState:
        """安全校验处理"""
        commands = state.pending_commands
        all_errors = []
        
        # 依次通过所有安全规则
        for rule in self.safety_rules:
            commands, errors = rule(commands)
            all_errors.extend(errors)
        
        # 记录被拒绝的命令用于学习
        if all_errors:
            error_summary = "; ".join(all_errors)
            state.nl_context.append(f"🛡️ 安全检查: {error_summary}")
        
        # 更新最终执行的命令
        state.pending_commands = commands
        
        return state
```

### 4.2 智能降级策略

```python
class FallbackStrategy:
    """当LLM失败或产生不安全指令时的降级策略"""
    
    def generate_safe_commands(self, state: FactoryState) -> List[dict]:
        """生成安全的降级命令"""
        safe_commands = []
        
        # 1. 优先处理电量危险的AGV
        for line_data in state.world_state.values():
            if isinstance(line_data, dict) and "agvs" in line_data:
                for agv_id, agv_data in line_data["agvs"].items():
                    battery = agv_data.get("battery_level", 100)
                    if battery < 15:
                        safe_commands.append({
                            "action": "charge",
                            "target": agv_id,
                            "params": {"target_level": 80}
                        })
        
        # 2. 处理简单的取货任务
        if not safe_commands:  # 只有在没有紧急充电需求时
            safe_commands.extend(self._generate_basic_transport_tasks(state))
        
        return safe_commands[:3]  # 限制命令数量
    
    def _generate_basic_transport_tasks(self, state: FactoryState) -> List[dict]:
        """生成基础运输任务"""
        tasks = []
        
        # 检查是否有空闲AGV可以去取原料
        for line_id in ["line1", "line2", "line3"]:
            line_data = state.world_state.get(line_id, {})
            for agv_id in ["AGV_1", "AGV_2"]:
                agv = line_data.get("agvs", {}).get(agv_id, {})
                if (agv.get("status") == "idle" and 
                    agv.get("battery_level", 0) > 30 and
                    len(agv.get("payload", [])) == 0):
                    
                    # 简单任务：去原料仓库取货
                    tasks.append({
                        "action": "move",
                        "target": agv_id,
                        "params": {"target_point": "P0"}
                    })
                    break  # 每条线只分配一个任务
        
        return tasks
```

## 5. 性能优化策略

### 5.1 上下文管理优化

```python
class ContextManager:
    def __init__(self, max_context_length=30):
        self.max_context_length = max_context_length
        self.importance_weights = {
            "fault": 1.0,      # 故障最重要
            "order": 0.8,      # 订单信息很重要  
            "battery_low": 0.9, # 低电量警告重要
            "status": 0.3      # 一般状态更新不太重要
        }
    
    def optimize_context(self, nl_context: List[str]) -> List[str]:
        """智能压缩上下文，保留最重要的信息"""
        if len(nl_context) <= self.max_context_length:
            return nl_context
        
        # 给每条消息评分
        scored_context = []
        for msg in nl_context:
            score = self._calculate_importance(msg)
            scored_context.append((score, msg))
        
        # 按重要性排序，保留最重要的消息
        scored_context.sort(reverse=True)
        optimized = [msg for score, msg in scored_context[:self.max_context_length]]
        
        # 按时间顺序重新排列
        return optimized
    
    def _calculate_importance(self, message: str) -> float:
        """计算消息重要性分数"""
        base_score = 0.5
        
        # 关键词检测
        for keyword, weight in self.importance_weights.items():
            if keyword in message.lower():
                base_score = max(base_score, weight)
        
        # 时间衰减（越新越重要）
        time_factor = 1.0  # 简化实现，实际可以根据时间戳计算
        
        return base_score * time_factor
```

### 5.2 批量决策优化

```python
class BatchDecisionManager:
    def __init__(self, batch_interval=5.0):
        self.batch_interval = batch_interval
        self.pending_events = []
        self.last_decision_time = 0
    
    def should_trigger_decision(self, current_time: float, urgent_events: List[str]) -> bool:
        """判断是否应该触发LLM决策"""
        
        # 有紧急事件时立即触发
        if urgent_events:
            return True
        
        # 达到批处理间隔
        if current_time - self.last_decision_time >= self.batch_interval:
            return True
        
        # 累积事件过多
        if len(self.pending_events) >= 10:
            return True
        
        return False
    
    def is_urgent_event(self, event: str) -> bool:
        """判断是否为紧急事件"""
        urgent_keywords = ["故障", "电量危险", "即将超期", "阻塞"]
        return any(keyword in event for keyword in urgent_keywords)
```

## 6. 监控与调试

### 6.1 决策可解释性

```python
class DecisionLogger:
    def __init__(self):
        self.decision_history = []
    
    def log_decision(self, state: FactoryState, commands: List[dict], reasoning: str):
        """记录决策过程用于调试"""
        decision_record = {
            "timestamp": time.time(),
            "world_state_summary": self._summarize_state(state),
            "context": state.nl_context[-5:],  # 最近5条事件
            "commands": commands,
            "reasoning": reasoning,
            "kpi_before": state.kpi_summary.copy()
        }
        self.decision_history.append(decision_record)
    
    def analyze_decision_effectiveness(self):
        """分析决策效果"""
        if len(self.decision_history) < 2:
            return
        
        current = self.decision_history[-1]
        previous = self.decision_history[-2]
        
        # 比较KPI变化
        kpi_changes = {}
        for key in current["kpi_before"]:
            if key in previous["kpi_before"]:
                change = current["kpi_before"][key] - previous["kpi_before"][key]
                kpi_changes[key] = change
        
        print(f"决策效果分析: {kpi_changes}")
```

### 6.2 A/B测试框架

```python
class ABTestManager:
    def __init__(self):
        self.strategies = {
            "conservative": {"temperature": 0.1, "fallback_threshold": 0.8},
            "aggressive": {"temperature": 0.3, "fallback_threshold": 0.5}
        }
        self.current_strategy = "conservative"
    
    def select_strategy(self, performance_history: List[float]) -> str:
        """根据性能历史选择策略"""
        if len(performance_history) < 10:
            return "conservative"
        
        recent_performance = sum(performance_history[-5:]) / 5
        if recent_performance < 0.7:  # 性能较差时切换到保守策略
            return "conservative"
        else:
            return "aggressive"
```

## 7. 部署与运维

### 7.1 LangGraph实现

```python
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

# 定义工作流
workflow = StateGraph(FactoryState)

# 添加节点
workflow.add_node("preprocess", PreprocessNode().process)
workflow.add_node("llm_brain", LLMBrain().process)  
workflow.add_node("post_guard", PostGuard().process)
workflow.add_node("mqtt_publisher", MQTTPublisher().process)

# 定义边
workflow.add_edge(START, "preprocess")
workflow.add_edge("preprocess", "llm_brain")
workflow.add_edge("llm_brain", "post_guard")
workflow.add_edge("post_guard", "mqtt_publisher")
workflow.add_edge("mqtt_publisher", "preprocess")  # 循环处理

# 编译图
app = workflow.compile()
```

### 7.2 成本控制

```python
class CostManager:
    def __init__(self, daily_budget=50):  # 每日50美元预算
        self.daily_budget = daily_budget
        self.token_costs = {
            "gpt-4": {"input": 0.03/1000, "output": 0.06/1000},
            "gpt-3.5-turbo": {"input": 0.001/1000, "output": 0.002/1000}
        }
        self.daily_usage = 0
    
    def estimate_cost(self, prompt_tokens: int, model: str) -> float:
        """估算调用成本"""
        rates = self.token_costs.get(model, self.token_costs["gpt-3.5-turbo"])
        return prompt_tokens * rates["input"] + 500 * rates["output"]  # 假设输出500 tokens
    
    def should_use_fallback(self) -> bool:
        """是否应该使用降级策略以控制成本"""
        return self.daily_usage > self.daily_budget * 0.8
```

## 8. 预期效果

### 8.1 性能目标
- **响应速度**: <3秒完成决策
- **决策质量**: KPI总分>80分
- **成本控制**: 每日API调用<$30
- **系统稳定性**: 99%时间正常运行

### 8.2 扩展性
- **新设备接入**: 只需修改Preprocess模板
- **新业务规则**: 更新Prompt即可
- **多模型支持**: 轻松切换不同LLM
- **A/B测试**: 支持策略对比验证

这个架构充分发挥了LLM的泛化能力，同时通过规则层确保安全可靠，是一个实用的工业AI解决方案。 