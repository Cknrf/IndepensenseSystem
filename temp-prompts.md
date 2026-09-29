*
Things that I want to add: 
- There should be some sort of message that would be played in the initialization part, this is for the good UX. For the blind user to enable to know that the system
is already starting and initializng, for the user to not just awkwardly wait. Since, without this, during the initialization part, it would be all quiet, and it can take up 2-3 minutes which is pretty slow.
So the least we can do about here, is to have some sort of the message, or even just a waiting sound/effects.
- Let's have now the service for the app.py, what I mean by this, is to automatically start the program without manually running it.
- Let's have an intent for shutdown of the PI, but since this is critical, there would be verification/confirmation message first, if the user confirmed or agreed or say yes, then proceed to shutdown. And let's have a goodbye message as well for this to be played


upon running the command: 
(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python - <<'PY'
import requests
from indepensense.config import NLU_PROMPT_PATH, NLU_MODEL, OLLAMA_URL
d = requests.post(f"{OLLAMA_URL}/api/generate", json={
    "model": NLU_MODEL,
    "system": NLU_PROMPT_PATH.read_text(),
    "prompt": "take me to SM Seaside",
    "stream": False, "format": "json", "think": False, "keep_alive": -1,
    "options": {"temperature": 0.0, "num_predict": 128},
}, timeout=180).json()
ns = 1e9
print("prompt tokens :", d.get("prompt_eval_count"), " (context window is 4096)")
print("output tokens :", d.get("eval_count"))
print(f"prompt eval   : {d.get('prompt_eval_duration',0)/ns:.2f}s")
print(f"generation    : {d.get('eval_duration',0)/ns:.2f}s")
print(f"total         : {d.get('total_duration',0)/ns:.2f}s")
print("response      :", d.get("response"))
PY
prompt tokens : 2050  (context window is 4096)
output tokens : 24
prompt eval   : 38.56s
generation    : 5.89s
total         : 45.01s
response      : {"intent": "navigation.start", "parameters": {"location": "SM Seaside", "nearest": false}}