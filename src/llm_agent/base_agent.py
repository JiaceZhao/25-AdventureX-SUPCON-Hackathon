"""
LLM Factory Agent 基础类

提供MQTT通信、状态管理和简单决策能力
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from src.utils.mqtt_client import MQTTClient
from src.utils.topic_manager import TopicManager
from config.schemas import AgentCommand
from .state_collector import StateCollector

logger = logging.getLogger(__name__)

@dataclass
class AgentState:
    """智能体状态管理"""
    current_time: float = 0.0
    factory_state: Dict[str, Any] = field(default_factory=dict)
    recent_events: List[str] = field(default_factory=list)
    last_decision_time: float = 0.0
    decision_interval: float = 5.0  # 决策间隔秒数
    
    def add_event(self, event: str):
        """添加新事件，保持最近30条"""
        self.recent_events.append(f"[{self.current_time:.1f}] {event}")
        if len(self.recent_events) > 30:
            self.recent_events = self.recent_events[-30:]

class LLMFactoryAgent:
    """
    LLM工厂智能体基础类
    
    负责：
    1. MQTT通信管理
    2. 工厂状态监控  
    3. 简单决策逻辑
    4. 命令发送
    """
    
    def __init__(
        self,
        mqtt_host: str = "supos-ce-instance4.supos.app",
        mqtt_port: int = 1883,
        topic_root: str = "NLDF_TEST",
        decision_interval: float = 5.0
    ):
        # MQTT设置
        self.mqtt_client = MQTTClient(mqtt_host, mqtt_port, f"{topic_root}_LLM_AGENT")
        self.topic_manager = TopicManager(topic_root)
        
        # 状态管理
        self.state = AgentState(decision_interval=decision_interval)
        self.state_collector = StateCollector(self.topic_manager)
        
        # 运行控制
        self.running = False
        self.tasks = []
        
        logger.info(f"LLM Factory Agent initialized with topic root: {topic_root}")
    
    async def start(self):
        """启动智能体"""
        logger.info("Starting LLM Factory Agent...")
        
        # 连接MQTT
        self.mqtt_client.connect()
        await self._wait_for_mqtt_connection()
        
        # 订阅所有相关topics
        self._subscribe_topics()
        
        # 启动后台任务
        self.running = True
        self.tasks = [
            asyncio.create_task(self._decision_loop()),
            asyncio.create_task(self._state_update_loop())
        ]
        
        logger.info("LLM Factory Agent started successfully")
        
        # 等待任务完成
        try:
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            logger.info("Agent tasks cancelled")
    
    async def stop(self):
        """停止智能体"""
        logger.info("Stopping LLM Factory Agent...")
        self.running = False
        
        # 取消所有任务
        for task in self.tasks:
            task.cancel()
        
        # 断开MQTT连接
        if self.mqtt_client:
            self.mqtt_client.disconnect()
        
        logger.info("LLM Factory Agent stopped")
    
    async def _wait_for_mqtt_connection(self, timeout: float = 10.0):
        """等待MQTT连接建立"""
        start_time = time.time()
        while not self.mqtt_client.is_connected():
            if time.time() - start_time > timeout:
                raise ConnectionError("MQTT connection timeout")
            await asyncio.sleep(0.1)
        logger.info("MQTT connection established")
    
    def _subscribe_topics(self):
        """订阅所有相关MQTT topics"""
        # 订阅所有生产线状态
        for line_id in ["line1", "line2", "line3"]:
            # AGV状态
            for agv_id in ["AGV_1", "AGV_2"]:
                topic = self.topic_manager.get_agv_status_topic(line_id, agv_id)
                self.mqtt_client.subscribe(topic, self._handle_agv_status)
            
            # 工站状态
            for station_id in ["StationA", "StationB", "StationC", "QualityCheck"]:
                topic = self.topic_manager.get_station_status_topic(line_id, station_id)
                self.mqtt_client.subscribe(topic, self._handle_station_status)
            
            # 传送带状态
            for conveyor_id in ["Conveyor_AB", "Conveyor_BC", "Conveyor_CQ"]:
                topic = self.topic_manager.get_conveyor_status_topic(line_id, conveyor_id)
                self.mqtt_client.subscribe(topic, self._handle_conveyor_status)
            
            # 故障告警
            topic = self.topic_manager.get_fault_alert_topic(line_id)
            self.mqtt_client.subscribe(topic, self._handle_fault_alert)
        
        # 订阅全局状态
        self.mqtt_client.subscribe(self.topic_manager.get_order_topic(), self._handle_order_status)
        self.mqtt_client.subscribe(self.topic_manager.get_kpi_topic(), self._handle_kpi_status)
        
        # 订阅仓库状态
        for warehouse_id in ["RawMaterial", "Warehouse"]:
            topic = self.topic_manager.get_warehouse_status_topic(warehouse_id)
            self.mqtt_client.subscribe(topic, self._handle_warehouse_status)
        
        logger.info("Subscribed to all factory status topics")
    
    def _handle_agv_status(self, topic: str, payload: bytes):
        """处理AGV状态更新"""
        try:
            data = json.loads(payload.decode('utf-8'))
            self.state_collector.update_agv_status(data)
            
            # 生成简单的事件描述
            agv_id = data.get("source_id", "unknown")
            battery = data.get("battery_level", 0)
            position = data.get("current_point", "unknown")
            status = data.get("status", "unknown")
            payload_count = len(data.get("payload", []))
            
            event = f"{agv_id} 在{position} {status} 电量{battery:.0f}% 载货{payload_count}个"
            self.state.add_event(event)
            
            # 检查是否需要紧急处理
            if battery < 15:
                self.state.add_event(f"⚠️ {agv_id} 电量危险低！")
                
        except Exception as e:
            logger.error(f"Error handling AGV status: {e}")
    
    def _handle_station_status(self, topic: str, payload: bytes):
        """处理工站状态更新"""
        try:
            data = json.loads(payload.decode('utf-8'))
            self.state_collector.update_station_status(data)
            
            station_id = data.get("source_id", "unknown")
            status = data.get("status", "unknown")
            buffer_count = len(data.get("buffer", []))
            
            event = f"{station_id} {status} 缓冲区{buffer_count}个产品"
            self.state.add_event(event)
            
        except Exception as e:
            logger.error(f"Error handling station status: {e}")
    
    def _handle_conveyor_status(self, topic: str, payload: bytes):
        """处理传送带状态更新"""
        try:
            data = json.loads(payload.decode('utf-8'))
            self.state_collector.update_conveyor_status(data)
            
            conveyor_id = data.get("source_id", "unknown")
            status = data.get("status", "unknown")
            buffer_count = len(data.get("buffer", []))
            
            if status == "blocked":
                event = f"🚫 {conveyor_id} 被阻塞！缓冲区{buffer_count}个产品"
                self.state.add_event(event)
                
        except Exception as e:
            logger.error(f"Error handling conveyor status: {e}")
    
    def _handle_fault_alert(self, topic: str, payload: bytes):
        """处理故障告警"""
        try:
            data = json.loads(payload.decode('utf-8'))
            device_id = data.get("device_id", "unknown")
            alert_type = data.get("alert_type", "unknown")
            
            if alert_type == "fault_recovered":
                event = f"✅ {device_id} 故障已恢复"
            else:
                event = f"🚨 {device_id} 发生故障"
            
            self.state.add_event(event)
            
        except Exception as e:
            logger.error(f"Error handling fault alert: {e}")
    
    def _handle_order_status(self, topic: str, payload: bytes):
        """处理订单状态更新"""
        try:
            data = json.loads(payload.decode('utf-8'))
            order_id = data.get("order_id", "unknown")
            items = data.get("items", [])
            priority = data.get("priority", "low")
            
            items_desc = ", ".join([f"{item.get('quantity', 0)}个{item.get('product_type', '?')}" for item in items])
            event = f"📋 新订单{order_id}: {items_desc} ({priority}优先级)"
            self.state.add_event(event)
            
        except Exception as e:
            logger.error(f"Error handling order status: {e}")
    
    def _handle_kpi_status(self, topic: str, payload: bytes):
        """处理KPI状态更新"""
        try:
            data = json.loads(payload.decode('utf-8'))
            order_rate = data.get("order_completion_rate", 0)
            
            # 只在KPI显著变化时记录
            if abs(order_rate - self.state.factory_state.get("last_order_rate", 0)) > 5:
                event = f"📊 订单完成率: {order_rate:.1f}%"
                self.state.add_event(event)
                self.state.factory_state["last_order_rate"] = order_rate
                
        except Exception as e:
            logger.error(f"Error handling KPI status: {e}")
    
    def _handle_warehouse_status(self, topic: str, payload: bytes):
        """处理仓库状态更新"""
        try:
            data = json.loads(payload.decode('utf-8'))
            warehouse_id = data.get("source_id", "unknown")
            buffer_count = len(data.get("buffer", []))
            
            # 记录仓库状态到factory_state，但不生成事件（太频繁）
            self.state.factory_state[f"{warehouse_id}_buffer_count"] = buffer_count
            
        except Exception as e:
            logger.error(f"Error handling warehouse status: {e}")
    
    async def _state_update_loop(self):
        """状态更新循环"""
        while self.running:
            self.state.current_time = time.time()
            await asyncio.sleep(1.0)  # 每秒更新一次时间
    
    async def _decision_loop(self):
        """决策循环"""
        while self.running:
            current_time = time.time()
            
            # 检查是否到达决策间隔
            if current_time - self.state.last_decision_time >= self.state.decision_interval:
                await self._make_decision()
                self.state.last_decision_time = current_time
            
            await asyncio.sleep(1.0)  # 每秒检查一次
    
    async def _make_decision(self):
        """制定决策（当前是简单规则，后续会替换为LLM）"""
        try:
            logger.info("Making decision...")
            
            # 当前使用简单规则，后续会替换为LLM决策
            commands = self._generate_simple_commands()
            
            if commands:
                for command in commands:
                    await self._send_command(command)
                    
                logger.info(f"Sent {len(commands)} commands")
            
        except Exception as e:
            logger.error(f"Error in decision making: {e}")
    
    def _generate_simple_commands(self) -> List[Dict]:
        """生成简单命令（临时实现，后续会用LLM替换）"""
        commands = []
        
        # 简单策略：找到空闲的AGV让它去取原料
        agv_states = self.state_collector.get_agv_states()
        
        for line_id in ["line1", "line2", "line3"]:
            for agv_id in ["AGV_1", "AGV_2"]:
                agv_key = f"{line_id}_{agv_id}"
                agv_data = agv_states.get(agv_key)
                
                if agv_data and self._should_send_agv_to_pickup(agv_data):
                    # 发送AGV去原料仓库
                    command = {
                        "command_id": f"simple_{int(time.time())}",
                        "action": "move",
                        "target": agv_id,
                        "params": {"target_point": "P0"}
                    }
                    commands.append((line_id, command))
                    break  # 每条线只派一个AGV
        
        return commands[:2]  # 限制同时命令数量
    
    def _should_send_agv_to_pickup(self, agv_data: Dict) -> bool:
        """判断是否应该派AGV去取货"""
        status = agv_data.get("status", "unknown")
        battery = agv_data.get("battery_level", 0)
        position = agv_data.get("current_point", "unknown")
        payload_count = len(agv_data.get("payload", []))
        
        # 条件：空闲、电量足够、没有载货、不在原料仓库
        return (
            status == "idle" and
            battery > 30 and
            payload_count == 0 and
            position != "P0"
        )
    
    async def _send_command(self, command_data):
        """发送命令到指定生产线"""
        try:
            line_id, command = command_data
            
            # 验证命令格式
            validated_command = AgentCommand.model_validate(command)
            
            # 发送到对应生产线的命令topic
            topic = self.topic_manager.get_agent_command_topic(line_id)
            payload = validated_command.model_dump_json()
            
            self.mqtt_client.publish(topic, payload)
            
            logger.info(f"Sent command to {line_id}: {command['action']} {command['target']}")
            
        except Exception as e:
            logger.error(f"Error sending command: {e}")
    
    def get_status_summary(self) -> Dict:
        """获取智能体状态摘要"""
        return {
            "running": self.running,
            "mqtt_connected": self.mqtt_client.is_connected(),
            "recent_events_count": len(self.state.recent_events),
            "last_decision_time": self.state.last_decision_time,
            "factory_state_keys": list(self.state.factory_state.keys())
        }


# 用于测试的简单运行函数
async def main():
    """测试运行函数"""
    import os
    import signal
    
    # 从环境变量获取配置
    topic_root = os.getenv("TOPIC_ROOT", "NLDF_TEST")
    
    agent = LLMFactoryAgent(topic_root=topic_root)
    
    # 设置信号处理
    def signal_handler(signum, frame):
        print("\nReceived interrupt signal, stopping agent...")
        asyncio.create_task(agent.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await agent.start()
    except KeyboardInterrupt:
        print("Agent stopped by user")
    except Exception as e:
        logger.error(f"Agent error: {e}")
    finally:
        await agent.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main()) 