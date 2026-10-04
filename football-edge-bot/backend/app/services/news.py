from __future__ import annotations
import json
import httpx
from ..config import get_settings

settings = get_settings()


async def analyze_text_with_ollama(text: str) -> dict:
    if not settings.ollama_enabled:
        return {"enabled": False, "impact": 0.0, "items": []}
    prompt = f"""
You are a sports-data extractor. Do not pick a bet. Extract only structured signals.
Return JSON with: injury_impact (-1..1), lineup_impact (-1..1), motivation (-1..1),
uncertainty (0..1), items [{type, subject, impact, confidence}].
Text:\n{text[:12000]}
"""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{settings.ollama_url}/api/generate", json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"})
        r.raise_for_status()
        data = r.json()
        try:
            return json.loads(data.get("response", "{}"))
        except json.JSONDecodeError:
            return {"enabled": True, "raw": data.get("response", ""), "items": []}
