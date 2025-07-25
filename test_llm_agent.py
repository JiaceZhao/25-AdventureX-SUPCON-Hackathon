#!/usr/bin/env python3
"""
LLM Agent 测试脚本

用于验证LLM Agent的基础功能：
1. 连接MQTT
2. 接收状态消息
3. 发送简单命令
"""

import asyncio
import logging
import os
import time
from src.llm_agent import LLMFactoryAgent

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_llm_agent():
    """测试LLM Agent基础功能"""
    
    # 从环境变量获取配置
    topic_root = os.getenv("TOPIC_ROOT", "NLDF_TEST")
    mqtt_host = "supos-ce-instance4.supos.app"
    mqtt_port = 1883
    
    logger.info("🧪 开始测试LLM Agent...")
    logger.info(f"配置: Topic Root={topic_root}, MQTT={mqtt_host}:{mqtt_port}")
    
    # 创建LLM Agent
    agent = LLMFactoryAgent(
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port, 
        topic_root=topic_root,
        decision_interval=10.0  # 测试时使用较长间隔
    )
    
    try:
        logger.info("🚀 启动LLM Agent...")
        
        # 启动agent（会阻塞运行）
        # 我们需要在后台运行一段时间来收集状态
        start_time = time.time()
        test_duration = 60  # 测试60秒
        
        # 创建一个任务来运行agent
        agent_task = asyncio.create_task(agent.start())
        
        # 等待一段时间让agent收集状态
        await asyncio.sleep(5)
        
        logger.info("📊 等待agent收集状态数据...")
        
        # 每10秒检查一次状态
        while time.time() - start_time < test_duration:
            await asyncio.sleep(10)
            
            # 获取状态摘要
            status = agent.get_status_summary()
            logger.info(f"Agent状态: {status}")
            
            # 检查状态收集器
            agv_states = agent.state_collector.get_agv_states()
            station_states = agent.state_collector.get_station_states()
            
            logger.info(f"收集到的AGV状态数: {len(agv_states)}")
            logger.info(f"收集到的工站状态数: {len(station_states)}")
            
            # 显示最近事件
            recent_events = agent.state.recent_events[-5:]  # 最近5条事件
            if recent_events:
                logger.info("最近事件:")
                for event in recent_events:
                    logger.info(f"  - {event}")
            
            # 检查工厂概览
            overview = agent.state_collector.get_factory_overview()
            logger.info(f"工厂概览: {overview}")
        
        logger.info("✅ 测试完成，停止agent...")
        
        # 取消agent任务
        agent_task.cancel()
        
        try:
            await agent_task
        except asyncio.CancelledError:
            logger.info("Agent任务已取消")
        
        # 停止agent
        await agent.stop()
        
        logger.info("🎉 LLM Agent测试成功完成！")
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)
        try:
            await agent.stop()
        except:
            pass


def test_state_collector():
    """测试状态收集器的基础功能"""
    logger.info("🧪 测试状态收集器...")
    
    from src.utils.topic_manager import TopicManager
    from src.llm_agent.state_collector import StateCollector
    
    topic_manager = TopicManager("NLDF_TEST") 
    collector = StateCollector(topic_manager)
    
    # 模拟AGV状态更新
    agv_data = {
        "source_id": "AGV_1",
        "timestamp": time.time(),
        "status": "idle",
        "current_point": "P1",
        "battery_level": 85.0,
        "payload": []
    }
    
    collector.update_agv_status(agv_data)
    
    # 获取状态
    agv_states = collector.get_agv_states()
    logger.info(f"AGV状态: {agv_states}")
    
    # 模拟工站状态更新
    station_data = {
        "source_id": "StationA",
        "timestamp": time.time(),
        "status": "processing",
        "buffer": ["prod_123", "prod_456"],
        "stats": {}
    }
    
    collector.update_station_status(station_data)
    
    # 获取工厂概览
    overview = collector.get_factory_overview()
    logger.info(f"工厂概览: {overview}")
    
    logger.info("✅ 状态收集器测试完成")


async def main():
    """主测试函数"""
    logger.info("🧪 开始LLM Agent完整测试")
    
    # 首先测试状态收集器
    test_state_collector()
    
    print("\n" + "="*50)
    
    # 然后测试完整的LLM Agent
    await test_llm_agent()
    
    logger.info("🎉 所有测试完成！")


if __name__ == "__main__":
    # 设置环境变量（如果需要）
    if not os.getenv("TOPIC_ROOT"):
        os.environ["TOPIC_ROOT"] = "NLDF_MACOS_TEST"
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("测试被用户中断")
    except Exception as e:
        logger.error(f"测试异常: {e}", exc_info=True) 