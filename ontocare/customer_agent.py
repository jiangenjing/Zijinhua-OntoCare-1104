"""Bounded customer agent: source facts, unverified claims and session state."""
import json
from datetime import date
from pathlib import Path
import re
import time
import uuid

import jsonschema

from .data import ROOT, connect, digest, load_json, rows
from .ontology import active
from .ontology_cache import OntologyCache
from .provider import ModelUnavailable, Provider
from .customer_retrieval import Retriever
from .prompting import contract, validate_sections

ACTIONS = {
    "roller_inspect": {"terms": ["roller", "滚刷", "滚筒", "滚轮", "拖布"], "completed": [r"(?:checked|cleaned|removed|inspected|cleared).{0,60}(?:roller|debris|hair|obstruction)", r"(?:roller|debris|hair).{0,60}(?:checked|cleaned|removed|cleared|done)", r"(?:已经|已).{0,25}(?:检查|清理|清洁|清除|拆).{0,20}(?:滚|异物|毛发)", r"(?:滚刷|滚筒|滚轮|拖布).{0,20}(?:已检查|已清理|清理过|检查过)"]},
    "restart": {"terms": ["restart", "reboot", "重启"], "completed": [r"(?:already|have).{0,20}(?:restarted|rebooted)", r"(?:已经|已).{0,10}重启"]},
}


def observed_actions(text):
    return [key for key, action in ACTIONS.items() if any(re.search(pattern, text, re.I) for pattern in action["completed"]) and not re.search(r"(?:haven't|have not|not yet|还没|尚未|没有).{0,15}(?:clean|check|restart|清理|检查|重启)", text, re.I)]


def intent(text):
    if re.search(r"refund|warranty|return\b|replacement|质保|保修|退款|退货|换货", text, re.I):
        return "aftersales"
    if re.search(r"shipping|tracking|delivery|shipment|order status|order amount|物流|快递|运单|发货|包裹|订单.*(?:到|状态|金额)|金额|多少钱", text, re.I):
        return "shipping"
    if re.search(r"dealer|seller|经销商|销售方|卖家|购买渠道|授权", text, re.I):
        return "aftersales"
    return "troubleshooting"


class Agent:
    def __init__(self, root=ROOT, retriever=None, ontology_cache=True):
        self.root = Path(root)
        self.ontology_cache = OntologyCache(self.root, enabled=ontology_cache)
        self.products = load_json(self.root / "data/products.json")
        self.retriever = retriever or Retriever(self.root)
        self.name_aliases = {}
        for alias, model in [("E25", "T2353"), ("E28", "T2352"), ("X10 Pro", "T2351"), ("S1 Pro", "T2080"), ("S1 Pro", "T8D04"), ("C20", "T2280"), ("C10", "T2292"), ("SoloCam S340", "T8170")]:
            proof = [d["id"] for d in self.retriever.docs if model in d["pns"] and alias.lower() in d["title"].lower()]
            if proof:
                self.name_aliases.setdefault(alias, {})[model] = proof[:2]
        with connect(self.root) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS faq_cache (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS conversation_session ON conversations(session_id,id)")

    def identify(self, text):
        found = set(re.findall(r"(?<![A-Z0-9])T[0-9][A-Z0-9]{3}(?![A-Z0-9])", text.upper()))
        for p in self.products:
            for alias in p["aliases"]:
                if re.search(r"(?<![A-Z0-9])" + re.escape(alias) + r"(?![A-Z0-9])", text.upper()):
                    found.add(p["pn"])
        if not found:
            for alias, models in self.name_aliases.items():
                if re.search(r"(?<![A-Z0-9])" + re.escape(alias.upper()) + r"(?![A-Z0-9])", text.upper()):
                    if alias == "S1 Pro" and re.search(r"breast|pump|吸奶", text, re.I):
                        found.update(p for p in models if p == "T8D04")
                    elif alias == "S1 Pro" and re.search(r"vacuum|robot|扫地|清洁机器人", text, re.I):
                        found.update(p for p in models if p == "T2080")
                    else:
                        found.update(models)
        known={p['pn'] for p in self.products}
        main=found&known
        if len(main)==1 and re.search(r'solar\s*panel|太阳能板',text,re.I):
            pn=next(iter(main))
            # A source-listed solar-panel code is an accessory reference, not another robot/camera.
            for code in found-known:
                if any(pn in d['pns'] and code in d['title'].upper() and re.search(r'solar\s*panel',d['title'],re.I) for d in self.retriever.docs):
                    found.remove(code)
        return sorted(found)

    def run(self, payload):
        started = time.perf_counter()
        text = payload["message"]
        version = payload.get("version") or active(self.root)
        variant = payload.get("variant", "full")
        if variant not in {"full", "plain_rag", "no_ontology", "no_skill"}:
            raise ValueError("Unknown variant")
        ontology_started = time.perf_counter()
        snapshot, snapshot_hit = self.ontology_cache.snapshot(version)
        b = snapshot["bundle"]
        ontology_ms = (time.perf_counter() - ontology_started) * 1000
        cache_stats = {"enabled": self.ontology_cache.enabled, "snapshot_hit": snapshot_hit, "resolve_hits": 0, "resolve_misses": 0, "graph_hits": 0, "graph_misses": 0}
        session_id = payload.get("session_id") or uuid.uuid4().hex
        trace_id = uuid.uuid4().hex
        with connect(self.root) as conn:
            old = conn.execute("SELECT payload FROM sessions WHERE id=?", (session_id,)).fetchone()
            history = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT 3", (session_id,))][::-1]
        state = json.loads(old[0]) if old else {"pn": None, "error_code": None, "completed_actions": [], "claims": {}, "verified": {}}
        metadata = payload.get("context", {})
        pns = self.identify(text + " " + str(metadata.get("sku", "")))
        known = {p["pn"] for p in self.products}
        ambiguous = len(pns) > 1 or any(p not in known for p in pns)
        if len(pns) == 1 and pns[0] in known:
            if state["pn"] and state["pn"] != pns[0]:
                state = {"pn": None, "error_code": None, "completed_actions": [], "claims": {}, "verified": {}}
                history = []
            state["pn"] = pns[0]
        codes = re.findall(r"(?:error|code|错误码?|故障码?|报错)\s*[:：#-]?\s*(\d{3,5})|(?<![A-Za-z0-9])(\d{3,5})\s*(?:error|错误|故障|报警)", text, re.I)
        if codes:
            state["error_code"] = next(x for x in codes[-1] if x)
        state["completed_actions"] = sorted(set(state["completed_actions"]) | set(observed_actions(text)))
        for action in observed_actions(text):
            state["claims"][action] = "user_reported; not tool-verified"
        if variant not in {"plain_rag", "no_skill"}:
            for action, patterns in b["skills"]["troubleshooting"].get("completion_patterns", {}).items():
                if any(re.search(pattern, text, re.I) for pattern in patterns):
                    state["completed_actions"] = sorted(set(state["completed_actions"]) | {action})
                    state["claims"][action] = "user_reported; not tool-verified"
        jsonschema.validate(state, b["domain_schema"])
        skill = intent(text)
        if history and skill == "troubleshooting" and not re.search(r"error|fault|broken|not work|报错|错误|故障|不工作|卡住", text, re.I):
            skill = history[-1]["skill"]
        retrieval_query = "\n".join([h["user"][-2000:] for h in history[-2:]] + [text])
        tools, docs = [], []
        retrieval_calls = []
        graph_ms = retrieval_ms = 0.0
        use_ontology = variant not in {"plain_rag", "no_ontology"}
        use_skill = variant not in {"plain_rag", "no_skill"}
        def tool(name, args, result):
            if len(tools) >= 6:
                raise ValueError("Tool budget exceeded")
            tools.append({"name": name, "arguments": args, "result": result})
            return result
        def semantic_query(family, *args):
            nonlocal ontology_ms, graph_ms
            query_started = time.perf_counter()
            result, hit = getattr(self.ontology_cache, family)(snapshot, *args)
            elapsed = (time.perf_counter() - query_started) * 1000
            ontology_ms += elapsed
            if family == 'graph':
                graph_ms += elapsed
            cache_stats[family + ("_hits" if hit else "_misses")] += 1
            return result, hit
        def resolve(mentions, context):
            result, hit = semantic_query("resolve", mentions, context)
            tool("resolve_semantics", {"mentions": mentions}, result)
            tools[-1]["cache_hit"] = hit
            return result
        checks = []
        decision, next_action = "answer", None
        zh, en = "", ""
        business_context = {}
        from .business import check_seller, order_detail, record_dealer_check
        business_claims = state['claims'].setdefault('purchase_context', {})
        for name in ['order_number', 'country', 'seller']:
            if metadata.get(name):business_claims[name] = metadata[name].strip()
        order_matches = re.findall(r'\bAnker\d{3}\b', text, re.I)
        if len(set(m.casefold() for m in order_matches)) == 1:
            business_claims['order_number'] = order_matches[0].capitalize()
        elif len(set(m.casefold() for m in order_matches)) > 1:
            business_claims.pop('order_number', None)
        country_match = re.search(r'(?:购买国家|下单国家|country)\s*[:：]\s*([A-Za-z]{2,3})\b', text, re.I)
        seller_match = re.search(r'(?:经销商|销售方|卖家|seller)\s*[:：]\s*([^，。;；\n?？]{1,100})', text, re.I)
        if country_match:business_claims['country'] = country_match[1].upper()
        if seller_match:business_claims['seller'] = seller_match[1].strip()
        if business_claims.get('country') or business_claims.get('seller'):
            dealer = tool('check_dealer', {k: business_claims.get(k, '') for k in ['country', 'seller']}, check_seller(business_claims.get('country', ''), business_claims.get('seller', ''), self.root))
            business_context['dealer_check'] = dealer
            business_context['dealer_check_id'] = record_dealer_check(dealer, business_claims.get('country', ''), business_claims.get('seller', ''), session_id, business_claims.get('order_number', ''), self.root)
        if business_claims.get('order_number') and skill == 'aftersales':
            business_context['order'] = tool('lookup_order', {'order_number': business_claims['order_number']}, order_detail(business_claims['order_number'], self.root))
        dealer_only = skill == 'aftersales' and bool(re.search(r'dealer|seller|经销商|销售方|卖家|购买渠道|授权', text, re.I)) and not re.search(r'故障|报错|error|fault', text, re.I)
        if skill == "shipping":
            query = text if len(set(m.casefold() for m in order_matches)) > 1 else str(business_claims.get('order_number', ''))
            zh, en, decision, order = self.shipping(query)
            tool("lookup_order", {"order_number": "redacted"}, order)
            business_context['order'] = order
            state['verified']['order_snapshot'] = order
        elif dealer_only:
            dealer = business_context.get('dealer_check') or tool('check_dealer', {'country': '', 'seller': ''}, check_seller('', '', self.root))
            business_context['dealer_check'] = dealer
            decision = 'collect_purchase_evidence'
            if dealer.get('competition_authorization') == 'MATCHED_BY_BRIEF_RULE':
                zh, en = '该购买国家和销售方按赛题名单匹配规则命中。此结果不等于售后资格已通过；请提供购买凭证、准确商品及需要的服务，以核实适用政策。', 'The purchase country and seller match the competition directory rule. This does not establish after-sales eligibility. Please provide proof of purchase, the exact item and requested service for policy verification.'
            else:
                zh, en = '销售方尚未得到唯一可靠匹配。请确认购买国家、凭证上的销售方完整名称与购买日期，结果保留待核查，不直接据此拒绝或批准售后。', 'The seller has not been matched reliably and uniquely. Please confirm the purchase country, full seller name on the receipt and purchase date. The result remains pending review and does not approve or reject a remedy.'
        elif ambiguous or not state["pn"]:
            decision = "clarify_product"
            zh, en = "请确认设备的准确型号／PN；目前无法唯一确定适用资料。", "Please confirm the exact model/PN so I can select applicable information."
        else:
            pn = state["pn"]
            allowed_knowledge = None
            if use_ontology:
                resolved = resolve(["pn:" + pn], text)
                allowed_knowledge = {r["target"].removeprefix("knowledge:") for item in resolved.get("results", []) for r in item.get("relations", []) if r["source"] == "pn:" + pn and r["target"].startswith("knowledge:")}
            if use_skill:
                tool("skill_state", {"skill": skill}, {"completed_actions": state["completed_actions"], "steps": b["skills"][skill]["steps"], "track_completed": b["skills"][skill].get("track_completed", False)})
            # Cache contains reviewed FAQ only; changing any bound field invalidates the entry.
            key = digest([pn, text.strip().casefold(), "zh-en", b["data_sha256"], b["bundle_sha256"]])
            cached = None
            if skill == "troubleshooting" and not state["completed_actions"] and not state["error_code"] and text.strip().casefold() in b["approved_faq"]:
                with connect(self.root) as conn:
                    hit = conn.execute("SELECT payload FROM faq_cache WHERE id=?", (key,)).fetchone()
                    cached = json.loads(hit[0]) if hit else None
            retrieval_started = time.perf_counter()
            live_search = payload.get('mode') == 'live'
            retrieval = self.retriever.search(retrieval_query, pn, state["error_code"], use_scope=use_ontology, allow_rewrite=live_search, ranking_profile='title_focused' if live_search else None) if cached is None else cached
            retrieval_ms += (time.perf_counter() - retrieval_started) * 1000
            retrieval_calls.extend({**c, 'phase': 'query_rewrite'} for c in retrieval.get('query_rewrite', {}).get('model_calls', []))
            docs = retrieval["documents"]
            if allowed_knowledge is not None:
                docs = [d for d in docs if d["id"] in allowed_knowledge]
            tool("search_evidence", {"pn": pn, "error_code": state["error_code"]}, {"mode": retrieval["mode"], "ids": [d["id"] for d in docs], "cache_hit": cached is not None, 'query_rewrite': retrieval.get('query_rewrite'), 'ranking_contract': retrieval.get('ranking_contract')})
            if cached is None and skill == "troubleshooting" and text.strip().casefold() in b["approved_faq"]:
                with connect(self.root) as conn:
                    conn.execute("INSERT OR REPLACE INTO faq_cache VALUES (?,?)", (key, json.dumps(retrieval, ensure_ascii=False)))
            if skill == "shipping":
                zh, en, decision, order = self.shipping(text + " " + str(metadata.get("order_number", "")))
                tool("lookup_order", {"order_number": "redacted"}, order)
                state["verified"]["order_snapshot"] = order
                docs = []
            elif skill == "aftersales":
                policies = [p for p in b["policies"] if p["pn"] == pn] if use_ontology else []
                zh, en, decision, selected = self.aftersales(retrieval_query, policies)
                if selected:
                    # Reply policy evidence must be part of returned citations even if retrieval ranked it lower.
                    ids = {p["source_id"] for p in selected}
                    docs = [d for d in self.retriever.docs if d["id"] in ids]
            elif not docs:
                decision = "insufficient_evidence"
                zh, en = "没有找到与该型号及错误码相符的资料，请核对错误码或提供更多信息，必要时请人工核查。", "I could not find evidence for this model and error code. Please verify the code or provide more details; manual review may be needed."
            else:
                supported_actions = [a for a, spec in ACTIONS.items() if any(t.lower() in docs[0]["content"].lower() for t in spec["terms"])]
                if use_ontology:
                    resolved_topic = resolve(["knowledge:" + docs[0]["id"]], text)
                    action_refs = {r["target"].rsplit(":", 1)[-1] for item in resolved_topic.get("results", []) for r in item.get("relations", []) if r["source"] == "knowledge:" + docs[0]["id"] and r["target"].startswith("action:")}
                    supported_actions = [a for a in ACTIONS if a in action_refs]
                track = use_skill and b["skills"]["troubleshooting"].get("track_completed", False)
                remaining = [a for a in supported_actions if not track or a not in state["completed_actions"]]
                if supported_actions and not remaining:
                    decision = "manual_review"
                    zh, en = "已记录你完成了资料中的检查。现有证据没有支持新的排障动作，请提交检查结果与错误画面，供人工进一步核查。", "Your completed checks are recorded. The available evidence does not support another troubleshooting action. Please provide the results and error screen for manual review."
                else:
                    next_action = remaining[0] if remaining else "read_source"
                    if next_action == "roller_inspect":
                        zh, en = "请按适用资料检查滚筒是否缠绕异物，并清理后确认能正常转动。操作以所附原始资料为准。", "Following the applicable source, check the roller for tangled objects, remove debris and confirm it rotates properly. Follow the cited source instructions."
                    elif next_action == "restart":
                        zh, en = "资料包含重启检查，请按照下面的原始说明操作。", "The source includes a restart check. Please follow the original instructions below."
                    else:
                        zh, en = "找到以下适用资料；英文原文见引用区。离线模式未对完整原文做模型翻译。", "Applicable information is available in the cited original source below. Offline mode has not translated the full source."
                    if text.strip().casefold() in b["approved_faq"]:
                        en = docs[0]["content"]
                        zh = "适用知识原文（英文）：" + docs[0]["content"]
        if skill in {'shipping', 'aftersales'} and not dealer_only and len(tools) < 6:
            from .decisions import evaluate
            from .business import date_value
            facts = {'intent': 'shipping' if skill == 'shipping' else 'refund' if re.search('refund|退款|退货', text, re.I) else 'fault'}
            order_context = business_context.get('order', {})
            if facts['intent'] == 'shipping':
                # A package's delivery does not establish that all order items arrived.
                # Keep the decision unknown until the relevant package and live status are verified.
                facts['delivery_status'] = 'UNKNOWN'
            elif facts['intent'] == 'fault':
                dates = {date_value(n['properties'].get('warranty_end')) for n in order_context.get('items', [])}
                if len(dates) == 1 and None not in dates:facts['warranty_end'] = next(iter(dates))
            service_decision = evaluate(facts, self.root)
            if facts['intent'] == 'shipping' and len(order_context.get('items', [])) > 1:
                service_decision['subject_scope'] = 'MULTIPLE_ITEMS_REQUIRE_TARGET_SELECTION'
                service_decision['next_step'] = '先确认客户问的是哪个商品或包裹，再核对收货情况；不能按一个包裹推断整单已送达。'
            business_context['service_decision'] = tool('evaluate_service_decision', facts, service_decision)
        graph_context = None
        if use_ontology and docs and state["pn"] and len(tools) < 6:
            graph_context, graph_hit = semantic_query("graph", docs, state["pn"], state["error_code"])
            tool("graph_search", {"pn": state["pn"], "max_hops": 2}, graph_context)
            tools[-1]["cache_hit"] = graph_hit
        response_contract = contract("disambiguation" if decision == "clarify_product" else skill, self.root)
        offline = {"zh": zh, "en": en, "citation_ids": [d["id"] for d in docs], "decision": decision, "next_action": next_action}
        response, model_status, model_calls = offline.copy(), "offline_not_requested", []
        model_validation = None
        response_validation_retries = 0
        if payload.get("mode", "offline") == "live":
            provider = Provider()
            def invoke(name, query):
                nonlocal retrieval_ms
                if name == "resolve_semantics":
                    if not use_ontology or not state["pn"]:
                        raise ValueError("Ontology tool is not available for this request")
                    result, _ = semantic_query("resolve", ["pn:" + state["pn"]], query)
                else:
                    retrieval_started = time.perf_counter()
                    result = self.retriever.search(query, state["pn"], state["error_code"], allow_rewrite=True, ranking_profile='title_focused')
                    retrieval_ms += (time.perf_counter() - retrieval_started) * 1000
                    retrieval_calls.extend({**c, 'phase': 'query_rewrite'} for c in result.get('query_rewrite', {}).get('model_calls', []))
                    if allowed_knowledge is not None:
                        result["documents"] = [d for d in result["documents"] if d["id"] in allowed_knowledge]
                    if graph_context is not None:
                        result["documents"] = [d for d in result["documents"] if d["id"] in graph_context["evidence_ids"]]
                    existing = {d["id"] for d in docs}
                    docs.extend(d for d in result["documents"] if d["id"] not in existing)
                return tool(name, {"query": query}, result)
            validation_feedback = None
            for attempt in range(2):
                try:
                    generated = provider.generate({"user_message": text, "history": history, "state": state, "binding_decision": offline, "skill_contract": b["skills"][skill] if use_skill else None, "ontology_context": graph_context, "business_context": business_context, "current_date": date.today().isoformat(), "evidence": docs, "response_contract": response_contract, "validation_feedback": validation_feedback}, invoke, (6 - len(tools)) if state["pn"] and use_ontology and not business_context else 0)
                    allowed = {d["id"] for d in docs}
                    if not set(generated["citation_ids"]) <= allowed or (docs and not generated["citation_ids"]):
                        raise ModelUnavailable("invalid_citations")
                    combined = generated["zh"] + "\n" + generated["en"] + "\n" + json.dumps(generated.get("sections", {}), ensure_ascii=False)
                    claim_text = re.sub(r"\b(?:cannot|can't|do not|don't|not|never|no)\s+(?:(?:be|a|any)\s+)?guarantee(?:d|s)?\b|(?:不能|无法|不)保证", "", combined, flags=re.I)
                    claim_text = re.sub(r"\b(?:refunds?|replacements?)\s+(?:(?:(?:has|is|have)\s+)?not\s+(?:been\s+)?|(?:cannot|can't|may not|will not|must not)\s+(?:be\s+)?)(?:approved|processed|completed)\b", "", claim_text, flags=re.I)
                    # A denied implication is not an assertion; stop at sentence boundaries or contrast words.
                    claim_text = re.sub(r"(?:\b(?:does not|do not|doesn't|don't)\s+(?:mean|constitute|imply|prove)\b|不代表|不等于|不意味着|不能说明)(?:(?!\bbut\b|\bhowever\b|但是|不过|但)[^。.!?;；\n\"\]}])*", "", claim_text, flags=re.I)
                    if re.search(r"(?:refund|replacement|退款|换货).{0,12}(?:processed|completed|approved|已完成|已批准)|guarantee|保证符合|已为您.*(?:转接|退款|换货)", claim_text, re.I):
                        raise ModelUnavailable("unsafe_business_claim")
                    if provider.key and provider.key in combined:
                        raise ModelUnavailable("secret_in_answer")
                    other_pns = set(self.identify(combined)) - {state["pn"]}
                    if other_pns and skill != 'shipping':
                        model_validation = {"reason": "cross_product_answer", "selected_pn": state["pn"], "unexpected_pns": sorted(other_pns)}
                        raise ModelUnavailable("cross_product_answer")
                    # The model may phrase an answer, never overwrite the code-side action boundary.
                    response.update({key: generated[key] for key in ["zh", "en", "citation_ids"]})
                    if validate_sections(generated.get("sections")):
                        response["sections"] = generated["sections"]
                    model_status = "completed"
                    break
                except ModelUnavailable as exc:
                    model_status = str(exc)
                    if attempt == 0 and model_status in {"unsafe_business_claim", "cross_product_answer", "invalid_citations"}:
                        validation_feedback = {"rejected_reason": model_status, "selected_pn": state["pn"], "instruction": "Rewrite from supplied evidence. Mention only selected PN. State only supported facts. Do not claim refunds, replacements or transfers are approved or executed. Do not add irrelevant business disclaimers to usage FAQs. Use supplied citation IDs."}
                        response_validation_retries += 1
                        continue
                    break
            model_calls = provider.calls
        visible_ids = set(response["citation_ids"])
        citations = [{"id": d["id"], "title": d["title"], "pns": d["pns"], "source": d["source"], "quote": d["content"], "content_hash": d["content_hash"]} for d in docs if d["id"] in visible_ids]
        checks.append({"name": "citation_scope", "passed": all(state["pn"] in d["pns"] for d in citations), "reason": "Every citation must explicitly apply to the selected PN."})
        checks.append({"name": "source_integrity", "passed": all(digest(d["quote"]) == d["content_hash"] for d in citations), "reason": "Quoted content hash must match the imported source cell."})
        checks.append({"name": "tool_budget", "passed": len(tools) <= 6, "reason": "At most six bounded tool invocations per request."})
        # A scope violation is never returned as a customer answer, including in ablations.
        if not all(c["passed"] for c in checks):
            response = {"zh": "检索结果未通过型号／来源校验，请人工核查。", "en": "Retrieved evidence failed product/source validation. Please request manual review.", "decision": "blocked_by_validator", "next_action": None, "citation_ids": []}
            citations = []
        result = {**response, "session_id": session_id, "trace_id": trace_id, "version": version, "bundle_sha256": b["bundle_sha256"], "variant": variant, "mode": "live" if model_status == "completed" else "offline", "model_status": model_status, "model_validation": model_validation, "citations": citations, "state": state, "tools": tools, "checks": checks, "model_calls": model_calls, "retrieval": graph_context, "prompt": {k: response_contract[k] for k in ["id", "skill", "system_sha256", "skill_sha256"]}, "latency_ms": round((time.perf_counter() - started) * 1000, 2), "answer_ttft_ms": None, "latency_boundary": "agent request start to complete response; excludes browser/network"}
        result["ontology_cache"] = cache_stats
        result['business_context'] = business_context
        result['response_validation_retries'] = response_validation_retries
        result['retrieval_model_calls'] = retrieval_calls
        result["timings"] = {"ontology_ms": round(ontology_ms, 3), 'graph_ms': round(graph_ms, 3), 'retrieval_ms': round(retrieval_ms, 3), 'rewrite_ms': round(sum(c.get('elapsed_ms', 0) for c in retrieval_calls), 3), "model_ms": round(sum(c.get("elapsed_ms", 0) for c in model_calls), 3)}
        with connect(self.root) as conn:
            conn.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)", (session_id, json.dumps(state, ensure_ascii=False)))
            conn.execute("INSERT INTO traces VALUES (?,?)", (trace_id, json.dumps(result, ensure_ascii=False)))
            conn.execute("INSERT INTO conversations(session_id,payload) VALUES (?,?)", (session_id, json.dumps({"user": text, "assistant": {"zh": response["zh"], "en": response["en"]}, "skill": skill, "pn": state["pn"]}, ensure_ascii=False)))
        return result

    def shipping(self, text):
        if (self.root / 'local/business.sqlite').exists():
            from .business import order_detail
            matches = sorted(set(m.capitalize() for m in re.findall(r'\bAnker\d{3}\b', text, re.I)))
            if len(matches) != 1:
                return '请一次提供一个准确订单号，以便逐商品和包裹核对。', 'Please provide one exact order number to check its items and packages.', 'collect_order', {'status': 'NEED_UNIQUE_ORDER'}
            detail = order_detail(matches[0], self.root)
            if detail['status'] != 'FOUND_LOCAL_SNAPSHOT':
                return '该订单不在本地资料快照，请核对订单号并提供购买凭证。', 'This order is absent from the local snapshot. Please verify its number and provide proof of purchase.', 'collect_order', detail
            summary = {'order': matches[0], 'status': detail['order']['properties']['status'],
                       'items': [{k: n['properties'][k] for k in ['sku', 'quantity', 'fulfillment_status', 'shipping_status', 'amount_raw']} for n in detail['items']],
                       'shipments': [{k: n['properties'][k] for k in ['tracking_number', 'carrier', 'status']} for n in detail['shipments']]}
            return '以下为本地快照，非实时查询。金额按源商品行展示，币种代码及金额粒度待核实，不自动相加；包裹内商品和数量尚未核实：' + json.dumps(summary, ensure_ascii=False), 'Local snapshot, not live tracking. Amounts are shown as source-row values; currency and amount grain need verification, so they are not summed. Package contents and quantities are unverified: ' + json.dumps(summary, ensure_ascii=False), 'report_snapshot', detail
        orders = rows("orders", self.root)
        matches = [o for o in orders if o["order_number"] and o["order_number"].casefold() in text.casefold()]
        if len(matches) != 1:
            return "请提供准确订单号，用于查询本地比赛资料快照；目前没有查询到唯一订单。", "Please provide the exact order number to query the local competition snapshot; no unique order was found.", "collect_order", {"found": False, "snapshot": True}
        order = matches[0]
        items = [i for i in rows("order_items", self.root) if i["order_number"] == order["order_number"]]
        summary = [{k: i[k] for k in ["sku", "quantity", "shipping_status", "ship_date", "carrier"]} for i in items]
        return "本地资料快照中的商品物流记录如下，不能代表当前实时状态：" + json.dumps(summary, ensure_ascii=False), "The following item shipping records come from a local source snapshot and are not live tracking: " + json.dumps(summary, ensure_ascii=False), "report_snapshot", {"found": True, "snapshot": True, "items": summary}

    def aftersales(self, text, policies):
        refund = bool(re.search(r"refund|return\b|退款|退货", text, re.I))
        selected = [p for p in policies if p["kind"] == ("refund" if refund else "warranty")]
        if not selected:
            return "该型号缺少可核实的适用售后政策，不能判断资格，请补充购买凭证并交人工核查。", "No verified applicable after-sales policy is available for this model. Please provide proof of purchase for manual review.", "policy_gap", []
        if refund:
            zh = "资料要求：购买后 30 天内、全新未拆封、封条完好、未使用且保留原包装。请逐项确认并提供购买凭证；满足描述仍不等于已核验或已批准退款。"
            en = "The source requires a request within 30 days of purchase, a new unopened item, intact seals, an unused condition and original packaging. Please confirm each condition and provide proof of purchase. Customer confirmation does not constitute verified eligibility or refund approval."
            return zh, en, "collect_policy_conditions", selected
        return "请确认是主机还是可清洗配件。资料分别规定主机 1 年、可清洗配件 3 个月；还需核实购买日期、适用地区及凭证，不能直接承诺保修资格。", "Please confirm whether the issue concerns the pump hub or washable parts. The source states 1 year for the hub and 3 months for washable parts. Purchase date, applicable region and proof still need verification; eligibility is not guaranteed.", "collect_component", selected
