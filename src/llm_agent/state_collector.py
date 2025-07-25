"""
状态收集器 - Phase 2 增强版

负责收集、存储和管理来自MQTT的各种设备状态信息
新增功能：
- 智能事件过滤和重要性评分
- 自然语言事件描述
- 上下文管理和压缩
"""

import time
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from src.utils.topic_manager import TopicManager


class EventImportance(Enum):
    """事件重要性级别"""
    CRITICAL = 4    # 紧急情况，需要立即处理
    HIGH = 3        # 高优先级，需要关注
    MEDIUM = 2      # 中等优先级
    LOW = 1         # 低优先级，可延后处理
    NOISE = 0       # 噪音事件，可忽略


@dataclass
class EventMetadata:
    """事件元数据"""
    importance: EventImportance
    category: str  # 'agv', 'station', 'conveyor', 'system'
    dedupe_key: str  # 用于去重的键
    nl_description: str  # 自然语言描述
    context_tags: List[str] = field(default_factory=list)  # 上下文标签
    trend_indicator: Optional[str] = None  # 趋势指示器 'improving', 'degrading', 'stable'


@dataclass
class DeviceState:
    """设备状态基类"""
    device_id: str
    timestamp: float
    status: str
    last_updated: float = field(default_factory=time.time)


@dataclass  
class AGVState(DeviceState):
    """AGV状态"""
    current_point: str = "unknown"
    target_point: Optional[str] = None
    battery_level: float = 0.0
    payload: List[str] = field(default_factory=list)
    line_id: str = "unknown"


@dataclass
class StationState(DeviceState):
    """工站状态"""
    buffer: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    line_id: str = "unknown"


@dataclass
class ConveyorState(DeviceState):
    """传送带状态"""
    buffer: List[str] = field(default_factory=list)
    upper_buffer: Optional[List[str]] = None
    lower_buffer: Optional[List[str]] = None
    line_id: str = "unknown"


@dataclass
class WarehouseState(DeviceState):
    """仓库状态"""
    buffer: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


class StateCollector:
    """
    状态收集器 - Phase 2 增强版
    
    负责：
    1. 智能事件过滤和重要性评分
    2. 自然语言事件描述生成
    3. 上下文管理和压缩
    4. 提供状态查询接口
    """
    
    def __init__(self, topic_manager: TopicManager):
        self.topic_manager = topic_manager
        
        # 状态存储
        self.agv_states: Dict[str, AGVState] = {}
        self.station_states: Dict[str, StationState] = {}
        self.conveyor_states: Dict[str, ConveyorState] = {}
        self.warehouse_states: Dict[str, WarehouseState] = {}
        
        # 增强的事件管理
        self.filtered_events: List[Dict[str, Any]] = []
        self.event_dedup_cache: Dict[str, float] = {}  # 去重缓存：key -> last_timestamp
        self.max_events = 200  # 增加事件容量
        self.max_context_window = 50  # LLM上下文窗口大小
        
        # 事件过滤配置
        self.dedup_window = 30  # 去重时间窗口（秒）
        self.battery_threshold = 10.0  # 电量变化阈值
        self.rate_limit_window = 5  # 相似事件频率限制（秒）
        
        # 状态历史（用于趋势分析）
        self.state_history: Dict[str, List[Dict]] = {}
        self.max_history_per_device = 10
    
    def update_agv_status(self, data: Dict[str, Any]):
        """更新AGV状态"""
        try:
            agv_id = data.get("source_id", "unknown")
            line_id = self._extract_line_id_from_agv(agv_id)
            
            # 创建状态对象
            agv_state = AGVState(
                device_id=agv_id,
                timestamp=data.get("timestamp", time.time()),
                status=data.get("status", "unknown"),
                current_point=data.get("current_point", "unknown"),
                target_point=data.get("target_point"),
                battery_level=data.get("battery_level", 0.0),
                payload=data.get("payload", []),
                line_id=line_id
            )
            
            # 检查状态变化并生成智能事件
            key = f"{line_id}_{agv_id}"
            old_state = self.agv_states.get(key)
            
            self._process_agv_state_change(old_state, agv_state, key)
            
            # 存储状态
            self.agv_states[key] = agv_state
            
            # 更新历史
            self._update_device_history(key, {
                "timestamp": agv_state.timestamp,
                "battery_level": agv_state.battery_level,
                "status": agv_state.status,
                "current_point": agv_state.current_point
            })
            
        except Exception as e:
            print(f"Error updating AGV status: {e}")
    
    def update_station_status(self, data: Dict[str, Any]):
        """更新工站状态"""
        try:
            station_id = data.get("source_id", "unknown")
            line_id = self._extract_line_id_from_station(station_id)
            
            station_state = StationState(
                device_id=station_id,
                timestamp=data.get("timestamp", time.time()),
                status=data.get("status", "unknown"),
                buffer=data.get("buffer", []),
                stats=data.get("stats", {}),
                line_id=line_id
            )
            
            # 检查缓冲区变化
            key = f"{line_id}_{station_id}"
            old_state = self.station_states.get(key)
            
            if old_state and len(station_state.buffer) != len(old_state.buffer):
                buffer_change = len(station_state.buffer) - len(old_state.buffer)
                self._add_filtered_event(
                    event_type="station_buffer_change",
                    device_id=station_id,
                    data={
                        "station_id": station_id,
                        "line_id": line_id,
                        "old_count": len(old_state.buffer),
                        "new_count": len(station_state.buffer),
                        "change": buffer_change,
                        "status": station_state.status
                    },
                    importance=EventImportance.MEDIUM if abs(buffer_change) > 0 else EventImportance.LOW,
                    nl_description=f"工站 {station_id} 缓冲区从 {len(old_state.buffer)} 个产品变为 {len(station_state.buffer)} 个产品"
                )
            
            self.station_states[key] = station_state
            
        except Exception as e:
            print(f"Error updating station status: {e}")
    
    def update_conveyor_status(self, data: Dict[str, Any]):
        """更新传送带状态"""
        try:
            conveyor_id = data.get("source_id", "unknown")
            line_id = self._extract_line_id_from_conveyor(conveyor_id)
            
            conveyor_state = ConveyorState(
                device_id=conveyor_id,
                timestamp=data.get("timestamp", time.time()),
                status=data.get("status", "unknown"),
                buffer=data.get("buffer", []),
                upper_buffer=data.get("upper_buffer"),
                lower_buffer=data.get("lower_buffer"),
                line_id=line_id
            )
            
            # 检查阻塞状态
            key = f"{line_id}_{conveyor_id}"
            old_state = self.conveyor_states.get(key)
            
            if conveyor_state.status == "blocked" and (not old_state or old_state.status != "blocked"):
                self._add_filtered_event(
                    event_type="conveyor_blocked",
                    device_id=conveyor_id,
                    data={
                        "conveyor_id": conveyor_id,
                        "line_id": line_id,
                        "buffer_count": len(conveyor_state.buffer)
                    },
                    importance=EventImportance.HIGH,
                    nl_description=f"传送带 {conveyor_id} 被阻塞，当前缓冲区有 {len(conveyor_state.buffer)} 个产品"
                )
            elif conveyor_state.status != "blocked" and old_state and old_state.status == "blocked":
                self._add_filtered_event(
                    event_type="conveyor_unblocked",
                    device_id=conveyor_id,
                    data={
                        "conveyor_id": conveyor_id,
                        "line_id": line_id,
                        "buffer_count": len(conveyor_state.buffer)
                    },
                    importance=EventImportance.MEDIUM,
                    nl_description=f"传送带 {conveyor_id} 阻塞解除，当前缓冲区有 {len(conveyor_state.buffer)} 个产品"
                )
            
            self.conveyor_states[key] = conveyor_state
            
        except Exception as e:
            print(f"Error updating conveyor status: {e}")
    
    def update_warehouse_status(self, data: Dict[str, Any]):
        """更新仓库状态"""
        try:
            warehouse_id = data.get("source_id", "unknown")
            
            warehouse_state = WarehouseState(
                device_id=warehouse_id,
                timestamp=data.get("timestamp", time.time()),
                status="active",  # 仓库通常总是活跃的
                buffer=data.get("buffer", []),
                stats=data.get("stats", {})
            )
            
            self.warehouse_states[warehouse_id] = warehouse_state
            
        except Exception as e:
            print(f"Error updating warehouse status: {e}")
    
    def _extract_line_id_from_agv(self, agv_id: str) -> str:
        """从AGV ID推断生产线ID"""
        # 假设AGV命名格式：AGV_1, AGV_2等，需要从topic或其他方式获取line_id
        # 这里简化处理，后续可以从topic解析
        return "unknown"
    
    def _extract_line_id_from_station(self, station_id: str) -> str:
        """从工站ID推断生产线ID"""
        return "unknown"
    
    def _extract_line_id_from_conveyor(self, conveyor_id: str) -> str:
        """从传送带ID推断生产线ID"""
        return "unknown"
    
    def _process_agv_state_change(self, old_state: Optional[AGVState], new_state: AGVState, device_key: str):
        """处理AGV状态变化，生成智能过滤的事件"""
        current_time = time.time()
        
        # 1. 状态变化事件
        if not old_state or old_state.status != new_state.status:
            self._add_filtered_event(
                event_type="agv_status_change",
                device_id=new_state.device_id,
                data={
                    "agv_id": new_state.device_id,
                    "line_id": new_state.line_id,
                    "old_status": old_state.status if old_state else None,
                    "new_status": new_state.status,
                    "position": new_state.current_point
                },
                importance=self._evaluate_status_change_importance(old_state, new_state),
                nl_description=self._generate_agv_status_nl(old_state, new_state)
            )
        
        # 2. 位置变化事件
        if not old_state or old_state.current_point != new_state.current_point:
            self._add_filtered_event(
                event_type="agv_position_change",
                device_id=new_state.device_id,
                data={
                    "agv_id": new_state.device_id,
                    "line_id": new_state.line_id,
                    "from_point": old_state.current_point if old_state else "unknown",
                    "to_point": new_state.current_point,
                    "target_point": new_state.target_point
                },
                importance=EventImportance.LOW,
                nl_description=f"AGV {new_state.device_id} 从 {old_state.current_point if old_state else '未知位置'} 移动到 {new_state.current_point}"
            )
        
        # 3. 电量变化事件（智能过滤）
        if old_state and abs(old_state.battery_level - new_state.battery_level) >= self.battery_threshold:
            battery_trend = self._analyze_battery_trend(device_key, new_state.battery_level)
            self._add_filtered_event(
                event_type="agv_battery_change",
                device_id=new_state.device_id,
                data={
                    "agv_id": new_state.device_id,
                    "line_id": new_state.line_id,
                    "old_level": old_state.battery_level,
                    "new_level": new_state.battery_level,
                    "change": new_state.battery_level - old_state.battery_level,
                    "trend": battery_trend
                },
                importance=self._evaluate_battery_importance(new_state.battery_level, battery_trend),
                nl_description=self._generate_battery_change_nl(new_state, old_state, battery_trend)
            )
        
        # 4. 载货变化事件
        if not old_state or len(old_state.payload) != len(new_state.payload):
            payload_change = len(new_state.payload) - (len(old_state.payload) if old_state else 0)
            self._add_filtered_event(
                event_type="agv_payload_change",
                device_id=new_state.device_id,
                data={
                    "agv_id": new_state.device_id,
                    "line_id": new_state.line_id,
                    "old_count": len(old_state.payload) if old_state else 0,
                    "new_count": len(new_state.payload),
                    "change": payload_change,
                    "payload_items": new_state.payload
                },
                importance=EventImportance.MEDIUM if payload_change != 0 else EventImportance.LOW,
                nl_description=self._generate_payload_change_nl(new_state, payload_change)
            )

    def _add_filtered_event(self, event_type: str, device_id: str, data: Dict[str, Any], 
                           importance: EventImportance, nl_description: str):
        """添加经过智能过滤的事件"""
        current_time = time.time()
        
        # 生成去重键
        dedupe_key = self._generate_dedupe_key(event_type, device_id, data)
        
        # 检查去重和频率限制
        if self._should_filter_event(dedupe_key, importance, current_time):
            return
        
        # 创建事件元数据
        metadata = EventMetadata(
            importance=importance,
            category=self._get_event_category(event_type),
            dedupe_key=dedupe_key,
            nl_description=nl_description,
            context_tags=self._generate_context_tags(event_type, data),
            trend_indicator=data.get("trend")
        )
        
        # 添加事件
        event = {
            "type": event_type,
            "timestamp": current_time,
            "device_id": device_id,
            "data": data,
            "metadata": metadata,
            "importance": importance.value,
            "nl_description": nl_description
        }
        
        self.filtered_events.append(event)
        self.event_dedup_cache[dedupe_key] = current_time
        
        # 维护事件数量限制
        self._maintain_event_limits()
    
    def _should_filter_event(self, dedupe_key: str, importance: EventImportance, current_time: float) -> bool:
        """判断是否应该过滤掉这个事件"""
        # 噪音事件直接过滤
        if importance == EventImportance.NOISE:
            return True
        
        # 紧急事件不过滤
        if importance == EventImportance.CRITICAL:
            return False
        
        # 检查去重缓存
        last_time = self.event_dedup_cache.get(dedupe_key)
        if last_time:
            time_diff = current_time - last_time
            
            # 根据重要性调整过滤时间窗口
            filter_window = {
                EventImportance.HIGH: self.rate_limit_window,
                EventImportance.MEDIUM: self.rate_limit_window * 2,
                EventImportance.LOW: self.rate_limit_window * 4
            }.get(importance, self.dedup_window)
            
            if time_diff < filter_window:
                return True
        
        return False
    
    def _generate_dedupe_key(self, event_type: str, device_id: str, data: Dict[str, Any]) -> str:
        """生成事件去重键"""
        # 根据事件类型生成不同的去重策略
        if event_type == "agv_battery_change":
            # 电量事件按设备和大致电量级别去重
            battery_level = data.get("new_level", 0)
            battery_range = int(battery_level // 10) * 10  # 按10%分档
            key_data = f"{event_type}:{device_id}:{battery_range}"
        elif event_type == "agv_position_change":
            # 位置变化按起点和终点去重
            from_point = data.get("from_point", "")
            to_point = data.get("to_point", "")
            key_data = f"{event_type}:{device_id}:{from_point}->{to_point}"
        else:
            # 默认按事件类型和设备去重
            key_data = f"{event_type}:{device_id}"
        
        return hashlib.md5(key_data.encode()).hexdigest()[:16]
    
    def _evaluate_status_change_importance(self, old_state: Optional[AGVState], new_state: AGVState) -> EventImportance:
        """评估状态变化的重要性"""
        if not old_state:
            return EventImportance.MEDIUM
        
        # 故障状态变化为紧急
        if new_state.status in ["error", "fault", "stuck"]:
            return EventImportance.CRITICAL
        
        # 从故障恢复为高优先级
        if old_state.status in ["error", "fault", "stuck"] and new_state.status in ["idle", "moving"]:
            return EventImportance.HIGH
        
        # 其他状态变化为中等优先级
        return EventImportance.MEDIUM
    
    def _evaluate_battery_importance(self, battery_level: float, trend: str) -> EventImportance:
        """评估电量变化的重要性"""
        if battery_level <= 5:
            return EventImportance.CRITICAL
        elif battery_level <= 15 and trend == "degrading":
            return EventImportance.HIGH
        elif battery_level <= 30 and trend == "degrading":
            return EventImportance.MEDIUM
        elif trend == "improving" and battery_level > 80:
            return EventImportance.LOW
        else:
            return EventImportance.MEDIUM
    
    def _generate_agv_status_nl(self, old_state: Optional[AGVState], new_state: AGVState) -> str:
        """生成AGV状态变化的自然语言描述"""
        if not old_state:
            return f"AGV {new_state.device_id} 初始状态为 {new_state.status}，位于 {new_state.current_point}"
        
        status_desc = {
            "idle": "空闲",
            "moving": "移动中",
            "loading": "装载中",
            "unloading": "卸载中",
            "charging": "充电中",
            "error": "故障",
            "fault": "异常",
            "stuck": "卡住"
        }
        
        old_desc = status_desc.get(old_state.status, old_state.status)
        new_desc = status_desc.get(new_state.status, new_state.status)
        
        base_msg = f"AGV {new_state.device_id} 从 {old_desc} 转为 {new_desc}"
        
        # 添加位置信息
        if new_state.current_point != old_state.current_point:
            base_msg += f"，位置从 {old_state.current_point} 变为 {new_state.current_point}"
        
        # 添加电量信息
        if new_state.battery_level <= 15:
            base_msg += f"，当前电量 {new_state.battery_level:.1f}% (低电量警告)"
        
        return base_msg
    
    def _generate_battery_change_nl(self, new_state: AGVState, old_state: AGVState, trend: str) -> str:
        """生成电量变化的自然语言描述"""
        change = new_state.battery_level - old_state.battery_level
        
        trend_desc = {
            "improving": "持续回升",
            "degrading": "持续下降",
            "stable": "相对稳定"
        }
        
        base_msg = f"AGV {new_state.device_id} 电量从 {old_state.battery_level:.1f}% 变为 {new_state.battery_level:.1f}%"
        
        if abs(change) >= 20:
            change_desc = "大幅上升" if change > 0 else "大幅下降"
            base_msg += f" ({change_desc} {abs(change):.1f}%)"
        
        if trend in trend_desc:
            base_msg += f"，趋势：{trend_desc[trend]}"
        
        if new_state.battery_level <= 5:
            base_msg += " ⚠️ 紧急电量警告！立即充电"
        elif new_state.battery_level <= 10:
            base_msg += " ⚠️ 紧急充电建议"
        elif new_state.battery_level <= 20:
            base_msg += " ⚡ 建议尽快充电"
        
        return base_msg
    
    def _generate_payload_change_nl(self, new_state: AGVState, payload_change: int) -> str:
        """生成载货变化的自然语言描述"""
        if payload_change > 0:
            return f"AGV {new_state.device_id} 装载了 {payload_change} 个产品，当前载货 {len(new_state.payload)} 个"
        elif payload_change < 0:
            return f"AGV {new_state.device_id} 卸载了 {abs(payload_change)} 个产品，当前载货 {len(new_state.payload)} 个"
        else:
            return f"AGV {new_state.device_id} 载货状态无变化，维持 {len(new_state.payload)} 个产品"
    
    def _get_event_category(self, event_type: str) -> str:
        """根据事件类型返回类别"""
        if event_type.startswith("agv_"):
            return "agv"
        elif event_type.startswith("station_"):
            return "station"
        elif event_type.startswith("conveyor_"):
            return "conveyor"
        else:
            return "system"
    
    def _generate_context_tags(self, event_type: str, data: Dict[str, Any]) -> List[str]:
        """生成上下文标签"""
        tags = []
        if event_type.startswith("agv_"):
            tags.append("AGV")
            tags.append(data.get("agv_id", "unknown"))
            if data.get("line_id"):
                tags.append(data["line_id"])
        elif event_type.startswith("station_"):
            tags.append("Station")
            tags.append(data.get("station_id", "unknown"))
            if data.get("line_id"):
                tags.append(data["line_id"])
        elif event_type.startswith("conveyor_"):
            tags.append("Conveyor")
            tags.append(data.get("conveyor_id", "unknown"))
            if data.get("line_id"):
                tags.append(data["line_id"])
        
        return tags
    
    def _analyze_battery_trend(self, device_key: str, current_level: float) -> str:
        """分析电量趋势"""
        history = self.state_history.get(device_key, [])
        if len(history) < 2:
            return "stable"
        
        # 获取最近几次电量变化
        recent_levels = [h["battery_level"] for h in history[-3:]]
        recent_levels.append(current_level)
        
        # 计算趋势
        if len(recent_levels) >= 3:
            trend_sum = 0
            for i in range(1, len(recent_levels)):
                trend_sum += recent_levels[i] - recent_levels[i-1]
            
            avg_change = trend_sum / (len(recent_levels) - 1)
            
            if avg_change > 2:
                return "improving"
            elif avg_change < -2:
                return "degrading"
            else:
                return "stable"
        
        return "stable"
    
    def _update_device_history(self, device_key: str, new_state_data: Dict[str, Any]):
        """更新设备状态历史"""
        if device_key not in self.state_history:
            self.state_history[device_key] = []
        
        history = self.state_history[device_key]
        history.append(new_state_data)
        
        # 保持历史数量限制
        if len(history) > self.max_history_per_device:
            self.state_history[device_key] = history[-self.max_history_per_device:]
    
    def _maintain_event_limits(self):
        """维护事件数量限制"""
        if len(self.filtered_events) > self.max_events:
            # 按重要性保留事件，优先保留高重要性事件
            critical_events = [e for e in self.filtered_events if e["importance"] >= EventImportance.CRITICAL.value]
            high_events = [e for e in self.filtered_events if e["importance"] == EventImportance.HIGH.value]
            medium_events = [e for e in self.filtered_events if e["importance"] == EventImportance.MEDIUM.value]
            low_events = [e for e in self.filtered_events if e["importance"] == EventImportance.LOW.value]
            
            # 保留最新的事件，但确保高重要性事件不被丢弃
            keep_events = []
            keep_events.extend(critical_events[-20:])  # 保留最近20个紧急事件
            keep_events.extend(high_events[-30:])      # 保留最近30个高优先级事件
            keep_events.extend(medium_events[-50:])    # 保留最近50个中等优先级事件
            keep_events.extend(low_events[-100:])      # 保留最近100个低优先级事件
            
            # 按时间戳排序并限制总数
            keep_events.sort(key=lambda x: x["timestamp"])
            self.filtered_events = keep_events[-self.max_events:]
        
        # 清理过期的去重缓存
        current_time = time.time()
        expired_keys = [
            key for key, timestamp in self.event_dedup_cache.items()
            if current_time - timestamp > self.dedup_window * 2
        ]
        for key in expired_keys:
            del self.event_dedup_cache[key]
    
    # 基础状态查询方法
    
    def get_agv_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有AGV状态"""
        result = {}
        for key, state in self.agv_states.items():
            result[key] = {
                "device_id": state.device_id,
                "status": state.status,
                "current_point": state.current_point,
                "target_point": state.target_point,
                "battery_level": state.battery_level,
                "payload": state.payload,
                "line_id": state.line_id,
                "last_updated": state.last_updated
            }
        return result
    
    def get_station_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有工站状态"""
        result = {}
        for key, state in self.station_states.items():
            result[key] = {
                "device_id": state.device_id,
                "status": state.status,
                "buffer": state.buffer,
                "buffer_count": len(state.buffer),
                "stats": state.stats,
                "line_id": state.line_id,
                "last_updated": state.last_updated
            }
        return result
    
    def get_conveyor_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有传送带状态"""
        result = {}
        for key, state in self.conveyor_states.items():
            result[key] = {
                "device_id": state.device_id,
                "status": state.status,
                "buffer": state.buffer,
                "buffer_count": len(state.buffer),
                "upper_buffer": state.upper_buffer,
                "lower_buffer": state.lower_buffer,
                "line_id": state.line_id,
                "last_updated": state.last_updated
            }
        return result
    
    def get_warehouse_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有仓库状态"""
        result = {}
        for key, state in self.warehouse_states.items():
            result[key] = {
                "device_id": state.device_id,
                "buffer": state.buffer,
                "buffer_count": len(state.buffer),
                "stats": state.stats,
                "last_updated": state.last_updated
            }
        return result
    
    def get_recent_events(self, count: int = 20) -> List[Dict[str, Any]]:
        """获取最近的事件"""
        return self.filtered_events[-count:]
    
    def get_line_summary(self, line_id: str) -> Dict[str, Any]:
        """获取指定生产线的状态摘要"""
        summary = {
            "line_id": line_id,
            "agvs": {},
            "stations": {},
            "conveyors": {},
            "total_products": 0,
            "urgent_issues": []
        }
        
        # AGV摘要
        for key, state in self.agv_states.items():
            if state.line_id == line_id:
                summary["agvs"][state.device_id] = {
                    "status": state.status,
                    "battery": state.battery_level,
                    "position": state.current_point,
                    "payload_count": len(state.payload)
                }
                
                # 检查紧急情况
                if state.battery_level < 15:
                    summary["urgent_issues"].append(f"{state.device_id} 电量危险低")
        
        # 工站摘要
        for key, state in self.station_states.items():
            if state.line_id == line_id:
                buffer_count = len(state.buffer)
                summary["stations"][state.device_id] = {
                    "status": state.status,
                    "buffer_count": buffer_count
                }
                summary["total_products"] += buffer_count
        
        # 传送带摘要
        for key, state in self.conveyor_states.items():
            if state.line_id == line_id:
                buffer_count = len(state.buffer)
                summary["conveyors"][state.device_id] = {
                    "status": state.status,
                    "buffer_count": buffer_count
                }
                summary["total_products"] += buffer_count
                
                # 检查阻塞
                if state.status == "blocked":
                    summary["urgent_issues"].append(f"{state.device_id} 被阻塞")
        
        return summary
    
    def get_factory_overview(self) -> Dict[str, Any]:
        """获取整个工厂的状态概览"""
        overview = {
            "total_agvs": len(self.agv_states),
            "total_stations": len(self.station_states),
            "total_conveyors": len(self.conveyor_states),
            "total_warehouses": len(self.warehouse_states),
            "urgent_issues": [],
            "lines": {}
        }
        
        # 按生产线汇总
        for line_id in ["line1", "line2", "line3"]:
            overview["lines"][line_id] = self.get_line_summary(line_id)
            overview["urgent_issues"].extend(overview["lines"][line_id]["urgent_issues"])
        
        return overview
    
    # Phase 2 新增接口方法
    
    def get_filtered_events(self, count: int = 20, min_importance: EventImportance = EventImportance.LOW) -> List[Dict[str, Any]]:
        """获取过滤后的事件，可按重要性筛选"""
        filtered = [
            event for event in self.filtered_events 
            if event["importance"] >= min_importance.value
        ]
        return filtered[-count:]
    
    def get_natural_language_summary(self, time_window: int = 300) -> str:
        """获取自然语言格式的工厂状态摘要"""
        current_time = time.time()
        recent_events = [
            event for event in self.filtered_events
            if current_time - event["timestamp"] <= time_window
        ]
        
        if not recent_events:
            return "工厂运行平稳，无特殊事件。"
        
        # 按重要性分组
        critical_events = [e for e in recent_events if e["importance"] >= EventImportance.CRITICAL.value]
        high_events = [e for e in recent_events if e["importance"] == EventImportance.HIGH.value]
        medium_events = [e for e in recent_events if e["importance"] == EventImportance.MEDIUM.value]
        
        summary_parts = []
        
        if critical_events:
            summary_parts.append(f"🚨 紧急情况 ({len(critical_events)} 项):")
            for event in critical_events[-3:]:  # 最近3个紧急事件
                summary_parts.append(f"  - {event['nl_description']}")
        
        if high_events:
            summary_parts.append(f"⚠️ 重要事件 ({len(high_events)} 项):")
            for event in high_events[-3:]:  # 最近3个重要事件
                summary_parts.append(f"  - {event['nl_description']}")
        
        if medium_events and not critical_events and not high_events:
            summary_parts.append(f"ℹ️ 常规事件 ({len(medium_events)} 项):")
            for event in medium_events[-3:]:  # 最近3个常规事件
                summary_parts.append(f"  - {event['nl_description']}")
        
        return "\n".join(summary_parts) if summary_parts else "工厂运行平稳，无重要事件。"
    
    def get_context_for_llm(self, max_events: Optional[int] = None) -> Dict[str, Any]:
        """为LLM生成结构化的上下文信息"""
        if max_events is None:
            max_events = self.max_context_window
        
        # 获取最重要的事件
        important_events = self.get_filtered_events(max_events, EventImportance.MEDIUM)
        
        context = {
            "factory_overview": self.get_factory_overview(),
                            "recent_events": [
                {
                    "type": event["type"],
                    "description": event["nl_description"],
                    "importance": event["importance"],
                    "timestamp": event["timestamp"],
                    "device_id": event["device_id"],
                    "context_tags": event["metadata"].context_tags if hasattr(event.get("metadata", {}), "context_tags") else []
                }
                for event in important_events
            ],
            "summary": self.get_natural_language_summary(),
            "urgent_issues": [],
            "recommendations": []
        }
        
        # 收集紧急问题
        for line_id in ["line1", "line2", "line3"]:
            line_summary = self.get_line_summary(line_id)
            context["urgent_issues"].extend(line_summary.get("urgent_issues", []))
        
        return context 