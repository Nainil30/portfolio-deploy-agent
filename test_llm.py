# test_llm.py
"""Test that LLM connection works."""

from src.utils.config_loader import load_config
from src.utils.llm_provider import get_llm
from langchain_core.messages import HumanMessage

config = load_config()
llm_config = config["llm"]

print(f"Connecting to {llm_config['provider']} / {llm_config['model']}...")

llm = get_llm(provider=llm_config["provider"], model=llm_config["model"])

response = llm.invoke([HumanMessage(content="Say 'LLM connection successful' and nothing else.")])

print(f"Response: {response.content}")
print("LLM TEST PASSED")