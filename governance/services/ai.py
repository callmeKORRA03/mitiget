import json
import os
import urllib.request

class SummaryProvider:
    name="local"
    def summarize(self, changes):
        counts={}
        for item in changes: counts[item.action]=counts.get(item.action,0)+1
        parts=[f"{count} {action}(s)" for action,count in sorted(counts.items())]
        return "Access review covers " + ", ".join(parts) + ". Review the individual entries for affected users, modules, permissions and scope."

class OpenAISummaryProvider(SummaryProvider):
    name="openai"
    def summarize(self, changes):
        key=os.getenv("AI_API_KEY", "")
        rows=[{"action":c.action,"user":c.target_email,"module":c.module,"permission":c.permission,"scope":c.scope_name} for c in changes]
        payload={"model":os.getenv("AI_MODEL","gpt-4o-mini"),"messages":[{"role":"system","content":"Summarize access governance changes accurately and concisely. Do not make authorization decisions or recommendations. State only facts present in the data."},{"role":"user","content":json.dumps(rows)}],"temperature":0.2}
        req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=12) as response: data=json.loads(response.read())
        return data["choices"][0]["message"]["content"]

def summarize_access_change(changes):
    provider=os.getenv("AI_PROVIDER", "").lower()
    if provider=="openai" and os.getenv("AI_API_KEY"):
        try: return OpenAISummaryProvider().summarize(changes), "openai"
        except Exception: pass
    return SummaryProvider().summarize(changes), "local"
