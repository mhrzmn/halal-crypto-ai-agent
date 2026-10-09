"""
Pure AI Market Predictor & Autonomous Strategy Forecaster.
Leverages LLMs (Gemini, OpenAI, DeepSeek) to analyze candlestick structure,
forecast directional trajectory, set dynamic entries/exits,
and dictate adaptive strategic sleep intervals (next_recheck_minutes) to prioritize token efficiency.
"""

import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import requests
import pandas as pd

from config.settings import settings

@dataclass
class AIPredictionResult:
    symbol: str
    action: str  # 'BUY', 'SELL', 'HOLD'
    predicted_direction: str  # e.g., 'BULLISH_EXPANSION', 'MEAN_REVERSION_BOUNCE', etc.
    confidence: float  # 0.0 to 1.0
    current_price: float
    target_price: float
    invalidation_price: float  # Stop-loss
    next_recheck_minutes: int  # Adaptive wait time
    thesis: str
    model_used: str

class AIPredictor:
    def __init__(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        custom_base_url: Optional[str] = None,
        custom_model_name: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ):
        self.provider = (provider or settings.AI_PROVIDER).lower().strip()
        self.custom_base_url = (custom_base_url or settings.CUSTOM_BASE_URL or "").strip()
        self.custom_model_name = (custom_model_name or settings.CUSTOM_MODEL_NAME or "").strip()
        self.custom_api_key = (custom_api_key or settings.CUSTOM_API_KEY or "").strip()

        self.model_name = self.custom_model_name or model_name or ("gemini-1.5-flash" if self.provider == "gemini" else "gpt-4o-mini")
        self.gemini_key = (gemini_api_key or settings.GEMINI_API_KEY or "").strip()
        self.openai_key = (openai_api_key or settings.OPENAI_API_KEY or "").strip()

    def predict_market_movement(
        self,
        symbol: str,
        df_candles: pd.DataFrame,
        snapshot: Dict[str, Any],
        has_open_position: bool = False,
        entry_price: Optional[float] = None
    ) -> AIPredictionResult:
        """
        Produce a full market prediction and actionable trading thesis.
        """
        curr_price = float(snapshot["close"])

        # Format recent 15 candles for the LLM prompt
        recent_bars = []
        for dt, row in df_candles.tail(15).iterrows():
            time_str = dt.strftime("%H:%M") if hasattr(dt, "strftime") else str(dt)[-5:]
            recent_bars.append({
                "time": time_str,
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": round(float(row["volume"]), 1)
            })

        # 1. Custom OpenAI-compatible Endpoint (OpenRouter, DeepSeek, Groq, Ollama, LM Studio, etc.)
        if self.custom_base_url or self.provider == "custom":
            try:
                return self._call_custom_endpoint(symbol, curr_price, snapshot, recent_bars, has_open_position, entry_price)
            except Exception as e:
                print(f"[Custom Endpoint Error]: {e}")

        # 2. Query Gemini if configured
        if (self.provider == "gemini" or self.gemini_key) and self.gemini_key:
            try:
                return self._call_gemini(symbol, curr_price, snapshot, recent_bars, has_open_position, entry_price)
            except Exception as e:
                pass

        # 3. Query OpenAI if configured
        if (self.provider in ["openai", "deepseek"] or self.openai_key) and self.openai_key:
            try:
                return self._call_openai(symbol, curr_price, snapshot, recent_bars, has_open_position, entry_price)
            except Exception as e:
                pass

        # 4. Fallback: Quantitative Forecasting Engine
        return self._quantitative_forecast(symbol, curr_price, snapshot, has_open_position, entry_price)

    def _call_custom_endpoint(
        self,
        symbol: str,
        current_price: float,
        snapshot: Dict[str, Any],
        recent_bars: List[Dict[str, Any]],
        has_open_position: bool,
        entry_price: Optional[float]
    ) -> AIPredictionResult:
        """Call any custom OpenAI-compatible endpoint (OpenRouter, DeepSeek, Groq, Ollama, LM Studio)."""
        from openai import OpenAI
        base_url = self.custom_base_url or settings.CUSTOM_BASE_URL
        api_key = self.custom_api_key or settings.CUSTOM_API_KEY or self.openai_key or "not-needed"
        model = self.custom_model_name or settings.CUSTOM_MODEL_NAME or self.model_name or "default"

        client = OpenAI(api_key=api_key, base_url=base_url)
        prompt = self._build_prompt(symbol, current_price, snapshot, recent_bars, has_open_position, entry_price)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a world-class quantitative crypto analyst and market forecaster."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.2
            )
            raw_content = response.choices[0].message.content
        except Exception:
            # Fallback for local engines that don't support response_format parameter
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a world-class quantitative crypto analyst. Output strictly valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )
            raw_content = response.choices[0].message.content

        content = self._extract_json(raw_content)
        return self._parse_llm_json(content, symbol, current_price, model)

    def _extract_json(self, raw_text: str) -> Dict[str, Any]:
        """Robust JSON extractor that handles markdown blocks, <think> tags, and preamble."""
        import re
        text = str(raw_text).strip()
        # Remove reasoning / thought blocks (DeepSeek R1, QwQ, etc.)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        # Strip markdown fences if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        # Locate outer JSON curly braces
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end+1]

        return json.loads(text)

    def _call_gemini(
        self,
        symbol: str,
        current_price: float,
        snapshot: Dict[str, Any],
        recent_bars: List[Dict[str, Any]],
        has_open_position: bool,
        entry_price: Optional[float]
    ) -> AIPredictionResult:
        """Call Google Gemini API for deep market forecasting."""
        model = self.model_name or "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_key}"

        prompt = self._build_prompt(symbol, current_price, snapshot, recent_bars, has_open_position, entry_price)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2
            }
        }

        resp = requests.post(url, json=payload, timeout=12)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API returned status {resp.status_code}: {resp.text}")

        res_json = resp.json()
        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
        data = self._extract_json(raw_text)

        return self._parse_llm_json(data, symbol, current_price, model)

    def _call_openai(
        self,
        symbol: str,
        current_price: float,
        snapshot: Dict[str, Any],
        recent_bars: List[Dict[str, Any]],
        has_open_position: bool,
        entry_price: Optional[float]
    ) -> AIPredictionResult:
        """Call OpenAI API for market forecasting."""
        from openai import OpenAI
        client = OpenAI(api_key=self.openai_key)
        model = self.model_name or "gpt-4o-mini"

        prompt = self._build_prompt(symbol, current_price, snapshot, recent_bars, has_open_position, entry_price)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a world-class quantitative crypto analyst and market forecaster."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        content = self._extract_json(response.choices[0].message.content)
        return self._parse_llm_json(content, symbol, current_price, model)

    def _build_prompt(
        self,
        symbol: str,
        current_price: float,
        snapshot: Dict[str, Any],
        recent_bars: List[Dict[str, Any]],
        has_open_position: bool,
        entry_price: Optional[float]
    ) -> str:
        return f"""
You are the Lead Portfolio Manager and Market Forecaster for an unleveraged Shariah-compliant Spot crypto fund.
Analyze this technical market structure for {symbol} on Binance Spot:

Current Spot Price: {current_price}
20 EMA: {snapshot['ema_20']}
50 EMA: {snapshot['ema_50']}
200 EMA: {snapshot['ema_200']}
RSI (14): {snapshot['rsi_14']:.1f}
ATR (14 Volatility): {snapshot['atr_14']:.2f}
Volume Ratio: {snapshot['vol_ratio']:.2f}x average
Market Regime: {snapshot['regime']}
Currently Holding Asset: {has_open_position} (Entry: {entry_price if entry_price else 'N/A'})

Recent 15-Minute Candlestick Sequence:
{json.dumps(recent_bars, indent=2)}

TASK:
1. Predict the directional price trajectory for {symbol} over the next 1-4 hours.
2. Determine action: "BUY" (only if high-conviction spot entry), "SELL" (only if holding and exiting), or "HOLD".
3. Calculate strategic Stop-Loss (invalidation level) and Take-Profit (target price).
4. Specify "next_recheck_minutes": HOW LONG the system should sleep before calling you again (e.g. 10 to 45 minutes). Prioritize token conservation during consolidations, and use shorter times (e.g. 5-10m) only when near critical breakouts.

Respond strictly in valid JSON with these keys:
{{
  "predicted_direction": "BULLISH_EXPANSION" | "BEARISH_CONTINUATION" | "MEAN_REVERSION_BOUNCE" | "CHOPPY_CONSOLIDATION",
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": float between 0.0 and 1.0,
  "target_price": float,
  "invalidation_price": float,
  "next_recheck_minutes": integer between 5 and 60,
  "thesis": "Concise natural language explanation of your prediction and market structure reasoning (2-3 sentences)"
}}
"""

    def _parse_llm_json(self, data: Dict[str, Any], symbol: str, current_price: float, model: str) -> AIPredictionResult:
        """Parse validated JSON response from LLM."""
        action = str(data.get("action", "HOLD")).upper().strip()
        if action not in ["BUY", "SELL", "HOLD"]:
            action = "HOLD"

        target_p = float(data.get("target_price", round(current_price * 1.03, 2)))
        sl_p = float(data.get("invalidation_price", round(current_price * 0.98, 2)))
        confidence = float(data.get("confidence", 0.50))
        recheck_min = int(data.get("next_recheck_minutes", 15))
        recheck_min = max(5, min(60, recheck_min))

        return AIPredictionResult(
            symbol=symbol,
            action=action,
            predicted_direction=str(data.get("predicted_direction", "CONSOLIDATION")),
            confidence=round(confidence, 2),
            current_price=current_price,
            target_price=target_p,
            invalidation_price=sl_p,
            next_recheck_minutes=recheck_min,
            thesis=str(data.get("thesis", "Market prediction generated by LLM.")),
            model_used=model
        )

    def _quantitative_forecast(
        self,
        symbol: str,
        current_price: float,
        snapshot: Dict[str, Any],
        has_open_position: bool,
        entry_price: Optional[float]
    ) -> AIPredictionResult:
        """Intelligent offline quantitative forecasting fallback."""
        rsi = snapshot["rsi_14"]
        regime = snapshot["regime"]
        atr = snapshot["atr_14"]
        vol_ratio = snapshot["vol_ratio"]
        macd_hist = snapshot["macd_hist"]

        # If holding:
        if has_open_position and entry_price:
            if rsi > 75:
                return AIPredictionResult(
                    symbol=symbol,
                    action="SELL",
                    predicted_direction="LOCAL_TOP_REVERSAL",
                    confidence=0.85,
                    current_price=current_price,
                    target_price=current_price,
                    invalidation_price=round(current_price - atr, 2),
                    next_recheck_minutes=20,
                    thesis=f"RSI reached extreme overbought ({rsi:.1f}). Taking profit before exhaustion pullback.",
                    model_used="Quantitative AI Forecaster"
                )
            return AIPredictionResult(
                symbol=symbol,
                action="HOLD",
                predicted_direction="DEVELOPING_SWING",
                confidence=0.55,
                current_price=current_price,
                target_price=round(entry_price + (2.5 * atr), 2),
                invalidation_price=round(entry_price - (1.5 * atr), 2),
                next_recheck_minutes=15,
                thesis="Active position trending inside target bounds. Holding to let profit develop.",
                model_used="Quantitative AI Forecaster"
            )

        # Evaluates potential entries
        if regime in ["STRONG_BULLISH", "MODERATE_BULLISH"] and 45 <= rsi <= 62 and vol_ratio > 1.1:
            tp = round(current_price + (3.0 * atr), 2)
            sl = round(current_price - (1.6 * atr), 2)
            return AIPredictionResult(
                symbol=symbol,
                action="BUY",
                predicted_direction="BULLISH_EXPANSION",
                confidence=0.75,
                current_price=current_price,
                target_price=tp,
                invalidation_price=sl,
                next_recheck_minutes=15,
                thesis=f"Confirmed bullish structure with healthy accumulation RSI ({rsi:.1f}) and expanding volume. Predicting expansion toward ${tp:,.2f}.",
                model_used="Quantitative AI Forecaster"
            )

        if rsi < 25 and macd_hist > snapshot.get("prev_macd_hist", -999):
            tp = round(current_price + (2.5 * atr), 2)
            sl = round(current_price - (1.5 * atr), 2)
            return AIPredictionResult(
                symbol=symbol,
                action="BUY",
                predicted_direction="MEAN_REVERSION_BOUNCE",
                confidence=0.70,
                current_price=current_price,
                target_price=tp,
                invalidation_price=sl,
                next_recheck_minutes=15,
                thesis=f"Deep oversold capitulation (RSI {rsi:.1f}) with upward momentum divergence. Predicting mean-reversion bounce toward ${tp:,.2f}.",
                model_used="Quantitative AI Forecaster"
            )

        # Default: Consolidation, sleep longer to conserve tokens
        next_wait = 25 if regime == "RANGING" else 15
        return AIPredictionResult(
            symbol=symbol,
            action="HOLD",
            predicted_direction="CHOPPY_CONSOLIDATION",
            confidence=0.30,
            current_price=current_price,
            target_price=round(current_price + (2 * atr), 2),
            invalidation_price=round(current_price - (2 * atr), 2),
            next_recheck_minutes=next_wait,
            thesis=f"Market consolidating ({regime}, RSI {rsi:.1f}). No clear edge detected. Conserving tokens; next scan in {next_wait} minutes.",
            model_used="Quantitative AI Forecaster"
        )
