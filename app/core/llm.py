"""LLM clients. The LLM only ever PROPOSES tool calls; guardrails decide what runs.

GroqLLM talks to Groq's OpenAI-compatible chat API with native tool calling. Any problem (no key,
timeout, rate limit, retired model, malformed tool call) raises LLMUnavailable, and the agent falls
back to its rules, so the store never stops."""
import asyncio
import json
import os
import time

import httpx

CHARTER = (
    "You are one of four AI agents that jointly run SyncStore, the operating system of a quick-commerce dark store "
    "(MUM-114, Andheri East, Mumbai) during the evening peak. The agents are Ledger (inventory truth), Captain "
    "(shift-lead copilot), Relay (rider-first release) and Promise (customer swap choices). You coordinate only "
    "through a shared store state: you read the JSON view you are given and act ONLY by calling your tools. "
    "Conflict rules, in order: 1 safety and compliance (cold chain, labour limits); 2 the customer promise (the "
    "10-minute promise is never extended); 3 completeness (full basket, or the swap the customer chose); "
    "4 efficiency. Hard limits are enforced in code and any tool call that breaks them is rejected. Use only ids "
    "that appear in the input. Call every tool this event needs in one response. Every 'reason' is one "
    "plain-English sentence of at most 25 words that a shift lead can read aloud. Do not reply with prose; reply "
    "with tool calls.")


def tool(name, description, props, required=None):
    props = dict(props)
    props["reason"] = {"type": "string", "description": "One sentence a shift lead can read aloud."}
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": list(required or []) + ["reason"]}}}


class LLMUnavailable(Exception):
    pass


class NoLLM:
    provider = "none"

    def __init__(self):
        self.models = {"smart": "—", "fast": "—"}

    @property
    def configured(self):
        return False

    def health(self):
        return {"configured": False, "provider": "none", "models": self.models, "calls": 0, "errors": 0,
                "last_error": None, "rpm_used": 0, "rpm_limit": 0, "rpd_used": 0, "rpd_limit": 0, "cooling": 0,
                "last_ok": None, "tokens": 0}

    async def decide(self, *a, **k):
        raise LLMUnavailable("no LLM configured")

    async def complete_json(self, *a, **k):
        raise LLMUnavailable("no LLM configured")


def _chain(env_name, defaults):
    first = os.environ.get(env_name, "").strip()
    out = [first] if first else []
    for m in defaults:
        if m not in out:
            out.append(m)
    return out


class GroqLLM:
    """One client shared by every session in the process, so the budgets protect the API key."""
    provider = "groq"
    URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/") + "/chat/completions"

    def __init__(self, api_key=None):
        self.key = (api_key or os.environ.get("GROQ_API_KEY", "")).strip()
        self.chains = {
            "smart": _chain("GROQ_MODEL_SMART", ["llama-3.3-70b-versatile", "openai/gpt-oss-120b",
                                                 "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.1-8b-instant"]),
            "fast": _chain("GROQ_MODEL_FAST", ["llama-3.1-8b-instant", "meta-llama/llama-4-scout-17b-16e-instruct",
                                               "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]),
        }
        self.dead = set()
        self.model_cool = {}   # model -> time it may be used again (Groq rate limits are per model)
        self.rpm = int(os.environ.get("GROQ_RPM", "25"))
        self.rpd = int(os.environ.get("GROQ_RPD", "900"))
        self.timeout = float(os.environ.get("LLM_TIMEOUT_S", "8"))
        self._minute, self._day = [], []
        self._cool, self._err_row = 0.0, 0
        self.calls = self.errors = self.tokens = 0
        self.last_error, self.last_ok = None, None
        self._client = None

    @property
    def configured(self):
        return bool(self.key)

    @property
    def models(self):
        return {tier: self._shown(tier) for tier in self.chains}

    def _model(self, tier, now=None):
        """First model in the tier's chain that is neither retired nor rate-limited right now."""
        now = now or time.time()
        chain = self.chains.get(tier, self.chains["fast"])
        for m in chain:
            if m not in self.dead and self.model_cool.get(m, 0) <= now:
                return m
        return None if now else chain[0]

    def _shown(self, tier):
        return self._model(tier) or next((m for m in self.chains[tier] if m not in self.dead), self.chains[tier][0])

    def _trim(self, now):
        self._minute = [x for x in self._minute if now - x <= 60]
        self._day = [x for x in self._day if now - x <= 86400]

    def health(self):
        now = time.time()
        self._trim(now)
        return {"configured": self.configured, "provider": "groq", "models": self.models, "calls": self.calls,
                "errors": self.errors, "last_error": self.last_error, "rpm_used": len(self._minute),
                "rpm_limit": self.rpm, "rpd_used": len(self._day), "rpd_limit": self.rpd,
                "cooling": max(0, round(self._cool - now), self._tier_wait("fast", now), self._tier_wait("smart", now)),
                "last_ok": self.last_ok, "tokens": self.tokens}

    def _tier_wait(self, tier, now):
        if self._model(tier, now):
            return 0
        waits = [self.model_cool.get(m, 0) - now for m in self.chains[tier] if m not in self.dead]
        return max(0, round(min(waits))) if waits else 0

    def _fail(self, why, cool=None):
        self.errors += 1
        self._err_row += 1
        self.last_error = why
        if cool is None and self._err_row >= 3:
            cool = 30
        if cool:
            self._cool = time.time() + cool
        return LLMUnavailable(why)

    def _gate(self):
        if not self.configured:
            raise LLMUnavailable("no GROQ_API_KEY set")
        now = time.time()
        self._trim(now)
        if now < self._cool:
            raise LLMUnavailable("cooling down after an error")
        if len(self._minute) >= self.rpm:
            raise LLMUnavailable("over the %d calls/min budget" % self.rpm)
        if len(self._day) >= self.rpd:
            raise LLMUnavailable("over the %d calls/day budget" % self.rpd)
        self._minute.append(now)
        self._day.append(now)
        self.calls += 1

    def _http(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=5.0))
        return self._client

    async def _post(self, body, tier, timeout=None):
        """POST with model fallback: a retired model is dropped and a rate-limited one rests until Groq's
        retry-after; either way the next model in the tier's chain is tried at once."""
        timeout = timeout or self.timeout
        for _ in range(len(self.chains.get(tier, self.chains["fast"]))):
            model = self._model(tier)
            if model is None:
                raise self._fail("every %s model is rate limited by Groq" % tier)
            body["model"] = model
            try:
                r = await asyncio.wait_for(self._http().post(
                    self.URL, json=body, headers={"Authorization": "Bearer " + self.key},
                    timeout=httpx.Timeout(timeout, connect=5.0)), timeout + 1)
            except (asyncio.TimeoutError, httpx.TimeoutException):
                raise self._fail("no answer within %g s" % timeout)
            except httpx.HTTPError as e:
                raise self._fail("network error: %s" % type(e).__name__)
            if r.status_code == 200:
                return model, r.json()
            text = r.text[:400]
            if r.status_code == 429:
                try:
                    wait = float(r.headers.get("retry-after", "30"))
                except ValueError:
                    wait = 30
                self.model_cool[model] = time.time() + min(300, max(5, wait))
                self.last_error = "%s rate limited by Groq; trying the next model" % model
                continue
            if r.status_code in (401, 403):
                raise self._fail("Groq rejected the API key (%d)" % r.status_code, 300)
            if r.status_code in (400, 404) and ("model" in text and ("decommission" in text or "not found" in text
                                                                    or "does not exist" in text)):
                self.dead.add(model)
                continue
            if r.status_code == 400 and "tool_use_failed" in text:
                raise self._fail("model produced an invalid tool call")
            raise self._fail("Groq error %d" % r.status_code)
        raise self._fail("no Groq model available right now")

    async def decide(self, system_prompt, view, tools, tier):
        self._gate()
        t0 = time.perf_counter()
        body = {"messages": [{"role": "system", "content": CHARTER + "\n\n" + system_prompt},
                             {"role": "user", "content": "Store view for this event:\n" + json.dumps(view, ensure_ascii=False)}],
                "tools": tools, "tool_choice": "required", "temperature": 0.1, "max_tokens": 900}
        model, data = await self._post(body, tier)
        ms = round((time.perf_counter() - t0) * 1000)
        try:
            msg = data["choices"][0]["message"]
            raw = msg.get("tool_calls") or []
        except (KeyError, IndexError, TypeError):
            raise self._fail("unreadable reply")
        calls = []
        for c in raw:
            fn = (c or {}).get("function") or {}
            name, args = fn.get("name"), fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except ValueError:
                    args = None
            if isinstance(name, str):
                calls.append((name, args if isinstance(args, dict) else {}))
        if not calls:
            raise self._fail("reply had no tool calls")
        self._err_row = 0
        self.tokens += int((data.get("usage") or {}).get("total_tokens") or 0)
        self.last_ok = {"model": model, "ms": ms, "at": time.time()}
        return calls, {"model": model, "ms": ms}

    async def complete_json(self, prompt, tier="smart"):
        """Free-form JSON answer (used by the CEO view's written brief)."""
        self._gate()
        body = {"messages": [{"role": "system", "content": "Reply with one JSON object only."},
                             {"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}, "temperature": 0.3, "max_tokens": 1200}
        model, data = await self._post(body, tier, timeout=25)
        try:
            out = json.loads(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise self._fail("unreadable reply (not JSON)")
        self._err_row = 0
        self.tokens += int((data.get("usage") or {}).get("total_tokens") or 0)
        return out


def make_llm():
    return GroqLLM() if os.environ.get("GROQ_API_KEY", "").strip() else NoLLM()
