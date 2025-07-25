# config/settings.py
import os

# MQTT Broker Configuration
# As specified in the user request.
MQTT_BROKER_HOST = "supos-ce-instance4.supos.app"
MQTT_BROKER_PORT = 1883

# Simulation Settings
SIMULATION_SPEED = 1  # 1 = real-time, 10 = 10x speed
LOG_LEVEL = "INFO"

# LLM Agent Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai, anthropic, local
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1000"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

# Agent Configuration  
AGENT_DECISION_INTERVAL = float(os.getenv("AGENT_DECISION_INTERVAL", "5.0"))  # 决策间隔秒
AGENT_CONTEXT_LENGTH = int(os.getenv("AGENT_CONTEXT_LENGTH", "30"))      # 保留事件数
AGENT_DAILY_BUDGET = float(os.getenv("AGENT_DAILY_BUDGET", "50.0"))      # 每日API预算美元

# Path to factory layout and game rules configurations
FACTORY_LAYOUT_PATH = "config/factory_layout.yml"
GAME_RULES_PATH = "config/game_rules.yml" 