"""Local stdio MCP JSON-RPC endpoint for the native read-only semantic tools."""
import json
import sys
import copy
import jsonschema

from .ontology import layer


def handle(message):
    method = message.get("method")
    semantic = layer()
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "ontocare-semantics", "version": "0.1.0"}}
    if method == "tools/list":
        from evoontology.runtime.tools import TOOLS
        tools = copy.deepcopy(TOOLS)
        for tool in tools:
            tool["inputSchema"]["properties"].pop("workspace", None)
        return {"tools": tools}
    if method == "tools/call":
        params = message["params"]
        args = params.get("arguments", {})
        registry = {tool["name"]: tool for tool in handle({"method": "tools/list"})["tools"]}
        if params["name"] not in registry:
            raise ValueError("Unknown tool")
        jsonschema.validate(args, registry[params["name"]]["inputSchema"])
        semantic = layer(args.get("version"))
        if params["name"] == "browse_semantics":
            result = semantic.browse(args.get("query", ""), args.get("kind", "term"), min(int(args.get("limit", 6)), 6))
        elif params["name"] == "resolve_semantics":
            result = semantic.resolve(args.get("mentions", [])[:5], args.get("context", ""))
        else:
            raise ValueError("Unknown tool")
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
    if method == "notifications/initialized":
        return None
    raise ValueError("Unknown method")


def main():
    for line in sys.stdin:
        message = {}
        try:
            message = json.loads(line)
            result = handle(message)
            if "id" in message:
                print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
        except (ValueError, KeyError, TypeError, jsonschema.ValidationError) as exc:
            if "id" in message:
                print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32602, "message": str(exc)}}), flush=True)


if __name__ == "__main__":
    main()
