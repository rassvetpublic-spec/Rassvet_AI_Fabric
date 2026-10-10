"""Синтетический App Server: никогда не обращается к модели/сети."""
import json
import sys
import time

scenario=sys.argv[1] if len(sys.argv)>1 else "success"
def rec():
    x=sys.stdin.readline()
    if not x: sys.exit(0)
    return json.loads(x)
def out(m):
    sys.stdout.write(json.dumps(m,ensure_ascii=False,separators=(",", ":"))+"\n")
    sys.stdout.flush()
hello=rec();assert hello["method"]=="initialize"
out({"id":1,"result":{"userAgent":"fake"}})
assert rec()["method"]=="initialized"
thr=rec();assert thr["method"]=="thread/start"
assert thr["params"]["sandbox"]=="read-only"
assert thr["params"]["approvalPolicy"]=="on-request"
out({"id":2,"result":{"thread":{"id":"thr-01"}}})
turn=rec();assert turn["method"]=="turn/start"
assert turn["params"]["threadId"]=="thr-01"
assert len(turn["params"]["input"])==1
if scenario=="turn_rpc_error":
    out({"id":3,"error":{"code":-32001,"message":"Bearer secret must stay hidden"}})
    sys.exit(0)
out({"id":3,"result":{"turn":{"id":"turn-01","status":"inProgress"}}})
if scenario=="server_request":
    out({"method":"item/commandExecution/requestApproval","id":88,"params":{"command":"bad"}})
    time.sleep(.2);sys.exit(0)
if scenario=="tool_started":
    out({"method":"item/started","params":{"threadId":"thr-01","turnId":"turn-01","item":{"type":"commandExecution"}}})
    time.sleep(.2);sys.exit(0)
if scenario=="hang":
    time.sleep(8);sys.exit(0)
if scenario=="wrong_turn":
    out({"method":"turn/completed","params":{"threadId":"thr-01","turn":{"id":"wrong","status":"completed"}}})
    sys.exit(0)
if scenario=="failed":
    out({"method":"turn/completed","params":{"threadId":"thr-01","turn":{"id":"turn-01","status":"failed"}}})
    sys.exit(0)
if scenario=="bad_reply":
    response='{"source":"import os\\n"}'
else:
    response='{"source":"def add(a, b):\\n    return a + b\\n"}'
out({"method":"item/agentMessage/delta","params":{"threadId":"thr-01","turnId":"turn-01","delta":response}})
out({"method":"turn/completed","params":{"threadId":"thr-01","turn":{"id":"turn-01","status":"completed"}}})
# Next command is forbidden except turn/interrupt for cancellation, so do not wait indefinitely.
