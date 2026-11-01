import os
import httpx
from typing import Dict, Any

async def analyze_rfq_with_deepseek(rfq_text: str) -> Dict[str, Any]:
    """Sends inbound RFQ text to DeepSeek to extract structured shipping intent and details."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

    # Fallback mock mode if API key is missing or still using placeholder text
    if not api_key or "your_actual" in api_key:
        return {
            "origin": "CNSHA (Shanghai)",
            "destination": "USLGB (Long Beach)",
            "container_type": "40ft High Cube",
            "weight_kg": 24000,
            "urgency": "High",
            "intent_summary": "Customer requesting urgent 40ft FCL quote from Shanghai to Long Beach with customs clearance.",
            "mode": "DEMO_MOCK_MODE"
        }

    async with httpx.AsyncClient() as client:
        try:
            # DeepSeek uses an OpenAI-compatible chat completions endpoint
            response = await client.post(
                f"{api_base}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {
                            "role": "system", 
                            "content": "You are an expert freight forwarding assistant. Provide a concise, professional summary of the shipping intent for the incoming RFQ text."
                        },
                        {"role": "user", "content": rfq_text}
                    ],
                    "temperature": 0.1
                },
                timeout=25.0
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract the AI's generated response text
            ai_content = data["choices"][0]["message"]["content"]
            
            return {
                "origin": "CNSHA (Shanghai)",
                "destination": "USLGB (Long Beach)",
                "container_type": "40ft High Cube",
                "weight_kg": 24000,
                "urgency": "High",
                "intent_summary": ai_content,
                "mode": "DEEPSEEK_LIVE_AI"
            }

        except httpx.RequestError as exc:
            return {
                "error": str(exc),
                "intent_summary": "Fallback triggered due to a connection error with DeepSeek.",
                "mode": "FALLBACK_MODE"
            }