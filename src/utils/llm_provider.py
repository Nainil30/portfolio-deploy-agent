# src/utils/llm_provider.py
"""
LLM provider factory — swap between Groq, Gemini, Ollama via config.

WHY THIS EXISTS:
Your agent logic should not care WHICH LLM it uses.
Write agent code once, switch providers by changing one line in YAML.
This is called the "adapter pattern" — a production best practice.

COST:
  Groq:   Free tier, 30 req/min, fastest inference
  Gemini: Free tier, 15 req/min
  Ollama: Fully free, runs locally, needs 8GB+ RAM
"""

import os
from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel

load_dotenv()


def get_llm(provider: str = "groq", model: str = "llama-3.1-8b-instant") -> BaseChatModel:
    """
    Return the right LLM client based on provider name.
    All providers are configured for low temperature (consistent outputs).
    """
    if provider == "groq":
        from langchain_groq import ChatGroq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY not found. Add it to your .env file. "
                "Get a free key at console.groq.com"
            )
        return ChatGroq(
            model=model,
            api_key=api_key,
            temperature=0.1,
        )

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=0.1,
        )

    elif provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model, temperature=0.1)

    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'groq', 'gemini', or 'ollama'.")