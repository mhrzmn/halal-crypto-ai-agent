"""
AI Decision Engine.
Combines quantitative indicators with AI reasoning to make disciplined spot trading decisions.
Supports algorithmic reasoning (offline/zero-cost) and LLM reasoning (Gemini/OpenAI).
"""

import json
from typing import Dict, Any, Optional
from dataclasses import dataclass
from config.settings import settings
from strategy.signals import TradeSignal, SignalGenerator

@dataclass
class AIAssessment:
    action: str  # 'BUY', 'SELL', 'HOLD'
    confidence: float
    recommended_stop_loss: float
    recommended_take_profit: float
    rationale: str
    risk_assessment: str
    provider: str

class AIAgent:
    def __init__(self, provider: Optional[str] = None):
        self.provider = (provider or settings.AI_PROVIDER).lower().strip()

    def analyze(
        self,
        symbol: str,
        snapshot: Dict[str, Any],
        has_open_position: bool = False,
        entry_price: Optional[float] = None
    ) -> AIAssessment:
        """
        Analyze the market data and produce an AI-guided decision.
        """
        # Step 1: Base quantitative analysis
        base_signal = SignalGenerator.generate_signal(
            symbol=symbol,
            snapshot=snapshot,
            has_open_position=has_open_position,
            entry_price=entry_price
        )

        # If provider is algorithmic or no API key is provided, use high-precision quantitative intelligence
        if self.provider == "algorithmic" or (
            self.provider == "openai" and not settings.OPENAI_API_KEY
        ) or (
            self.provider == "gemini" and not settings.GEMINI_API_KEY
        ):
            return self._algorithmic_assessment(base_signal, snapshot)

        # Step 2: If LLM is configured, query LLM for synthesis
        if self.provider == "openai" and settings.OPENAI_API_KEY:
            try:
                return self._query_openai(symbol, snapshot, base_signal)
            except Exception as e:
                # Fallback to algorithmic gracefully
                assessment = self._algorithmic_assessment(base_signal, snapshot)
                assessment.rationale += f" (LLM query failed: {str(e)[:50]}, fell back to quantitative model)"
                return assessment

        if self.provider == "gemini" and settings.GEMINI_API_KEY:
            try:
                return self._query_gemini(symbol, snapshot, base_signal)
            except Exception as e:
                assessment = self._algorithmic_assessment(base_signal, snapshot)
                assessment.rationale += f" (Gemini query failed: {str(e)[:50]}, fell back to quantitative model)"
                return assessment

        return self._algorithmic_assessment(base_signal, snapshot)

    def _algorithmic_assessment(self, signal: TradeSignal, snapshot: Dict[str, Any]) -> AIAssessment:
        """Rule-based intelligent quantitative model."""
        risk_level = "LOW" if snapshot["regime"] == "STRONG_BULLISH" else "MODERATE"
        if snapshot["rsi_14"] > 70 or snapshot["regime"] == "STRONG_BEARISH":
            risk_level = "HIGH"

        return AIAssessment(
            action=signal.action,
            confidence=signal.confidence,
            recommended_stop_loss=signal.stop_loss,
            recommended_take_profit=signal.take_profit,
            rationale=signal.rationale,
            risk_assessment=f"Regime: {snapshot['regime']}, Risk Level: {risk_level}, Volatility (ATR): {snapshot['atr_14']:.2f}",
            provider="Algorithmic AI Engine"
        )

    def _query_openai(self, symbol: str, snapshot: Dict[str, Any], signal: TradeSignal) -> AIAssessment:
        """Query OpenAI API for market analysis."""
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        prompt = f"""
You are an expert Islamic/Halal spot cryptocurrency trading analyst.
Analyze the following technical setup for {symbol} on Binance Spot (100% unleveraged cash, long-only):
Current Price: {snapshot['close']}
20 EMA: {snapshot['ema_20']}
50 EMA: {snapshot['ema_50']}
200 EMA: {snapshot['ema_200']}
RSI (14): {snapshot['rsi_14']:.1f}
ATR (14): {snapshot['atr_14']:.2f}
Volume Ratio: {snapshot['vol_ratio']:.2f}
Market Regime: {snapshot['regime']}
Quantitative Baseline Recommendation: {signal.action} (Confidence: {signal.confidence})

Respond strictly with valid JSON with these keys:
"action": "BUY" | "SELL" | "HOLD"
"confidence": float between 0.0 and 1.0
"stop_loss": float price
"take_profit": float price
"rationale": concise explanation (1-2 sentences)
"risk_level": "LOW" | "MODERATE" | "HIGH"
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a disciplined quantitative spot trading risk manager."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        content = json.loads(response.choices[0].message.content)
        return AIAssessment(
            action=content.get("action", signal.action),
            confidence=float(content.get("confidence", signal.confidence)),
            recommended_stop_loss=float(content.get("stop_loss", signal.stop_loss)),
            recommended_take_profit=float(content.get("take_profit", signal.take_profit)),
            rationale=content.get("rationale", signal.rationale),
            risk_assessment=f"AI Risk Rating: {content.get('risk_level', 'MODERATE')}",
            provider="OpenAI LLM"
        )

    def _query_gemini(self, symbol: str, snapshot: Dict[str, Any], signal: TradeSignal) -> AIAssessment:
        """Query Gemini API via REST for market analysis."""
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"Evaluate spot trade for {symbol}: Price={snapshot['close']}, RSI={snapshot['rsi_14']:.1f}, "
                            f"Regime={snapshot['regime']}, ATR={snapshot['atr_14']}. Base={signal.action}. "
                            f"Respond strictly in JSON with action ('BUY'/'SELL'/'HOLD'), confidence (0-1), stop_loss, take_profit, rationale."
                }]
            }],
            "generationConfig": {"response_mime_type": "application/json"}
        }
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw_text)

        return AIAssessment(
            action=parsed.get("action", signal.action),
            confidence=float(parsed.get("confidence", signal.confidence)),
            recommended_stop_loss=float(parsed.get("stop_loss", signal.stop_loss)),
            recommended_take_profit=float(parsed.get("take_profit", signal.take_profit)),
            rationale=parsed.get("rationale", signal.rationale),
            risk_assessment="Gemini LLM Risk Evaluated",
            provider="Gemini LLM"
        )
