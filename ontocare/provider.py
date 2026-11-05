"""Optional OpenAI-compatible provider. Never serialize keys or provider bodies."""
import json
import http.client
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .prompting import contract, validate_sections


class ModelUnavailable(Exception):
    pass


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        if urlparse(request.full_url).hostname != urlparse(new_url).hostname or urlparse(new_url).scheme != "https":
            raise ModelUnavailable("unsafe_provider_redirect")
        return super().redirect_request(request, fp, code, message, headers, new_url)


class Provider:
    def __init__(self, judge=False, config_path=None):
        prefix = "ONTOCARE_JUDGE_" if judge else "ONTOCARE_LLM_"
        config_path = os.environ.get(prefix + "CONFIG") or config_path
        config = json.loads(Path(config_path).read_text()) if config_path and Path(config_path).is_file() else {}
        self.base = os.environ.get(prefix + "BASE_URL", config.get("base_url", ""))
        self.key = os.environ.get(prefix + "API_KEY", config.get("api_key", ""))
        self.model = os.environ.get(prefix + "MODEL", config.get("text_model", config.get("model", "")))
        self.calls = []

    def public_status(self):
        return {"configured": bool(self.base and self.key and self.model), "model": self.model or None, "host": urlparse(self.base).hostname}

    def chat(self, messages, tools=None):
        if not all([self.base, self.key, self.model]):
            raise ModelUnavailable("not_configured")
        if not self.base.startswith("https://") and not self.base.startswith("http://127.0.0.1:"):
            raise ModelUnavailable("invalid_provider_url")
        body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": 2300}
        if "deepseek" in self.model.lower():
            body["thinking"] = {"type": "disabled"}
        if tools:
            body["tools"] = tools
            body["parallel_tool_calls"] = False
        request = urllib.request.Request(self.base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        started = time.perf_counter()
        attempt = {"model": self.model, "status": "started", "answer_ttft_ms": None, "streaming": False}
        try:
            with urllib.request.build_opener(SafeRedirect()).open(request, timeout=90) as response:
                payload = json.load(response)
            message = payload["choices"][0]["message"]
            attempt.update(model=payload.get("model", self.model), status="completed", elapsed_ms=round((time.perf_counter() - started) * 1000, 2), usage=payload.get("usage"), finish_reason=payload["choices"][0].get("finish_reason"))
            self.calls.append(attempt)
            return message
        except urllib.error.HTTPError as exc:
            self.calls.append({**attempt, "status": "failed", "reason": f"http_{exc.code}", "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
            raise ModelUnavailable(f"http_{exc.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, KeyError, ValueError):
            self.calls.append({**attempt, "status": "failed", "reason": "connection_or_response_error", "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
            raise ModelUnavailable("connection_or_response_error") from None

    def generate(self, context, invoke, budget):
        """A bounded model tool loop; all tools are revalidated by the caller."""
        schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}
        tools = [{"type": "function", "function": {"name": name, "description": description, "parameters": schema}} for name, description in [("search_evidence", "Search only within the already identified product and error code."), ("resolve_semantics", "Resolve ontology concepts for the current product.")]]
        response_contract = context.get("response_contract") or contract("troubleshooting")
        messages = [{"role": "system", "content": response_contract["system"] + "\n\n" + response_contract["skill_text"]}, {"role": "user", "content": json.dumps({k: v for k, v in context.items() if k != "response_contract"}, ensure_ascii=False)}]
        for turn in range(budget + 1):
            message = self.chat(messages, tools if turn < budget else None)
            calls = message.get("tool_calls", [])
            if not calls:
                content = (message.get("content") or "").strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                try:
                    result = json.loads(content)
                    if not isinstance(result.get("zh"), str) or not isinstance(result.get("en"), str) or not isinstance(result.get("citation_ids"), list):
                        raise ValueError
                    if any(not isinstance(i, str) for i in result["citation_ids"]):
                        raise ValueError
                    if "sections" in result and not validate_sections(result["sections"]):
                        raise ValueError
                    return result
                except (ValueError, AttributeError):
                    raise ModelUnavailable("invalid_structured_answer") from None
            if len(calls) != 1 or turn >= budget:
                raise ModelUnavailable("tool_budget_exceeded")
            call = calls[0]
            try:
                args = json.loads(call["function"]["arguments"])
                name = call["function"]["name"]
                if name not in {"search_evidence", "resolve_semantics"} or set(args) != {"query"} or not isinstance(args["query"], str):
                    raise ValueError
                result = invoke(name, args["query"])
            except (ValueError, KeyError, TypeError):
                raise ModelUnavailable("invalid_tool_call") from None
            messages.extend([message, {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)}])
        raise ModelUnavailable("tool_budget_exceeded")
