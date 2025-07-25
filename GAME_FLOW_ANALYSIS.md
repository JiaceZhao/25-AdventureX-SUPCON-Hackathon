# SUPCON智能工厂仿真系统 - 详细游戏流程分析

## 1. 系统概览

### 1.1 项目背景
- **项目名称**: SUPCON NLDF (Natural Language Driven Factory) Simulator
- **目标**: 构建通过自然语言决策的智能体系统，实现工厂自适应、自组织、自优化
- **核心理念**: 机器通过语言对话进行协作："我这边快满了，暂停投料。""收到，我先缓一轮。"

### 1.2 系统架构
```
AI Agent (选手代码) ←→ MQTT Broker ←→ Factory Simulation (SimPy) ←→ Unity Frontend
```

## 2. 工厂布局与设备

### 2.1 生产线配置
- **3条并行生产线**: line1, line2, line3
- **每条线设备配置**:
  - StationA (工站A) - 初加工
  - StationB (工站B) - 中间加工  
  - StationC (工站C) - 精加工
  - QualityCheck (质检站) - 质量检测
  - 3条传送带: Conveyor_AB, Conveyor_BC, Conveyor_CQ
  - 2台AGV: AGV_1, AGV_2

### 2.2 公共设施
- **RawMaterial**: 原料仓库（所有生产线共享）
- **Warehouse**: 成品仓库（所有生产线共享）

### 2.3 AGV路径系统
每个AGV有独立路径点系统：
- **P0**: RawMaterial (原料仓库)
- **P1**: StationA 
- **P2**: Conveyor_AB (传送带AB)
- **P3**: StationB
- **P4**: Conveyor_BC (传送带BC) 
- **P5**: StationC
- **P6**: Conveyor_CQ (传送带CQ，三缓冲区)
- **P7**: QualityCheck input buffer
- **P8**: QualityCheck output buffer
- **P9**: Warehouse (成品仓库)
- **P10**: 充电点

## 3. 产品工艺流程

### 3.1 产品类型
- **P1产品** (60%概率): 标准流程
- **P2产品** (30%概率): 标准流程
- **P3产品** (10%概率): 特殊返工流程

### 3.2 工艺路线

#### 标准流程 (P1, P2):
```
RawMaterial → [AGV取货] → StationA → Conveyor_AB → StationB → Conveyor_BC → StationC → Conveyor_CQ → QualityCheck → [AGV取货] → Warehouse
```

#### P3特殊流程:
```
RawMaterial → [AGV取货] → StationA → Conveyor_AB → StationB → Conveyor_BC → StationC → Conveyor_CQ[缓冲区] → [AGV取货] → StationB → Conveyor_BC → StationC → Conveyor_CQ → QualityCheck → [AGV取货] → Warehouse
```

### 3.3 质检流程
- **通过**: 直接进入成品仓库
- **返工**: 回到上一个加工工站（最多一次返工）
- **报废**: 产品废弃

## 4. AGV操作详解

### 4.1 AGV能力
- **载货能力**: 2个产品
- **电池管理**: 50%初始电量，低于10%自动充电
- **移动速度**: 2.0 m/s
- **充电速度**: 3.33%/秒（约30秒充满）

### 4.2 电池消耗
- **移动消耗**: 0.1%/米 或 0.5%/米（不同AGV配置不同）
- **操作消耗**: 0.5%/次（装卸货）

### 4.3 AGV操作权限矩阵
```
路径点 | AGV_1可操作设备 | AGV_2可操作设备 | 允许操作
-----|-------------|-------------|-------
P0   | RawMaterial | RawMaterial | load
P1   | StationA    | StationA    | unload, load
P2   | Conveyor_AB | Conveyor_AB | load
P3   | StationB    | StationB    | unload, load
P4   | Conveyor_BC | Conveyor_BC | load
P5   | StationC    | StationC    | unload, load
P6   | Conveyor_CQ | Conveyor_CQ | load (upper/lower buffer)
P7   | QualityCheck| QualityCheck| unload (input buffer)
P8   | QualityCheck| QualityCheck| load (output buffer)
P9   | Warehouse   | Warehouse   | unload
P10  | -           | -           | charge
```

## 5. 订单生成与管理

### 5.1 订单生成规律
- **生成间隔**: 10-10秒（配置为固定10秒）
- **订单数量分布**:
  - 1个产品: 40%
  - 2个产品: 30%
  - 3个产品: 20%
  - 4个产品: 7%
  - 5个产品: 3%

### 5.2 优先级分布
- **低优先级**: 70% (deadline = 理论时间 × 3.0)
- **中优先级**: 25% (deadline = 理论时间 × 2.0)  
- **高优先级**: 5% (deadline = 理论时间 × 1.5)

### 5.3 理论生产时间
- **P1**: 160秒
- **P2**: 200秒
- **P3**: 250秒

## 6. 故障系统

### 6.1 故障类型
- **工站故障**: 设备振动等
- **AGV故障**: AGV卡住
- **传送带故障**: 传送带卡住

### 6.2 故障特征
- **注入间隔**: 120-180秒随机
- **持续时间**: 20-60秒随机
- **自动恢复**: 故障会自动解除

### 6.3 故障影响
- 设备进入FAULT状态，无法操作
- 正在处理的产品会被中断
- AGV故障会在空闲时触发

## 7. MQTT通信协议

### 7.1 Topic结构
```
NLDF_TEST/
├── line1/
│   ├── station/{id}/status
│   ├── agv/{id}/status
│   ├── conveyor/{id}/status
│   └── alerts
├── line2/ (同line1结构)
├── line3/ (同line3结构)
├── warehouse/{id}/status
├── orders/status
├── kpi/status
├── result/status
├── command/{line_id}
└── response/{line_id}
```

### 7.2 Agent命令格式
```json
{
  "command_id": "move_001",
  "action": "move",
  "target": "AGV_1", 
  "params": {
    "target_point": "P1"
  }
}
```

### 7.3 支持的命令
- **move**: AGV移动到指定路径点
- **load**: AGV装载货物（自动识别当前位置可操作设备）
- **unload**: AGV卸载货物（自动识别当前位置可操作设备）
- **charge**: AGV主动充电
- **get_result**: 获取当前KPI得分

## 8. KPI评分系统 (100分制)

### 8.1 生产效率 (40分)
- **订单完成率** (16分): 按时完成订单数/总订单数
- **生产周期效率** (16分): 实际时间/理论时间（含完成率权重）
- **设备利用率** (8分): 设备工作时间/总时间

### 8.2 质量成本 (30分) 
- **一次通过率** (12分): 一次通过质检数/总产品数
- **成本控制** (18分): 基于材料、能源、维修、报废成本

### 8.3 AGV效率 (30分)
- **充电策略** (9分): 主动充电次数/总充电次数
- **能效比** (12分): 完成任务数/总充电时间
- **AGV利用率** (9分): 运输时间/(总时间-故障-充电)

## 9. 游戏流程时序

### 9.1 初始化阶段 (0-10秒)
1. 工厂设备初始化
2. AGV充电至50%
3. MQTT连接建立
4. 开始订单生成

### 9.2 运行阶段 (10秒-∞)
1. **订单生成**: 每10秒生成新订单
2. **原料供应**: 订单生成时原料自动出现在RawMaterial
3. **生产调度**: Agent需要调度AGV执行以下循环：
   - 从RawMaterial取原料
   - 运送到各工站进行加工
   - 处理传送带上的产品流转
   - 质检后运送到仓库
4. **故障处理**: 120-180秒间隔随机故障
5. **电量管理**: AGV电量管理和充电策略
6. **KPI监控**: 实时计算和发布KPI数据

### 9.3 关键决策点
- **AGV任务分配**: 哪个AGV执行哪个任务
- **路径规划**: AGV移动路径优化
- **负载均衡**: 多条生产线间的负载分配
- **库存管理**: 各缓冲区的产品流控制
- **故障应对**: 故障发生时的应急调度
- **充电时机**: AGV的最优充电策略

## 10. 挑战与约束

### 10.1 系统约束
- AGV一次最多载2个产品
- 各设备缓冲区容量有限
- AGV电量限制移动距离
- 质检站输出缓冲区满时会阻塞

### 10.2 优化目标
- 最大化订单按时完成率
- 最小化生产成本
- 最优化AGV利用率
- 提高系统鲁棒性

### 10.3 复杂性来源
- **多目标优化**: KPI三大类需要平衡
- **动态环境**: 订单、故障的随机性
- **资源竞争**: 多AGV、多生产线共享资源
- **时间约束**: 订单deadline压力
- **状态空间庞大**: 6个AGV×10个路径点×多种状态

## 11. 成功策略要素

### 11.1 核心能力需求
1. **实时调度算法**: 动态任务分配和路径规划
2. **预测性维护**: 基于设备状态预测故障
3. **多目标优化**: 平衡效率、质量、成本
4. **协同控制**: 多AGV协调避免冲突
5. **自适应策略**: 根据环境变化调整策略

### 11.2 技术架构建议
1. **分层架构**: 全局调度器 + 局部控制器
2. **事件驱动**: 基于MQTT消息的响应式架构
3. **状态管理**: 完整的系统状态追踪
4. **决策引擎**: 基于规则+机器学习的决策
5. **监控告警**: 异常检测和处理机制

这个系统是一个典型的**多智能体制造执行系统(MES)**，需要解决调度、协调、优化等复杂问题。 