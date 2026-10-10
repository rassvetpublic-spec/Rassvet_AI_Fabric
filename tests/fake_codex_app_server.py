"""Безопасный локальный фальшсервер для unit-тестов реального транспорта."""
import json, os, sys, time
scenario=sys.argv[1] if len(sys.argv)>1 else 'success'

def read():
 s=sys.stdin.readline()
 return json.loads(s) if s else {}
def send(v):
 sys.stdout.write(json.dumps(v)+'\n')
 sys.stdout.flush()

if scenario=='eof':sys.exit(0)
if scenario=='timeout':time.sleep(3);sys.exit(0)
hello=read()
if os.environ.get('RAIF_ASSERT_NO_AUTH')=='1':
 assert not any(x in os.environ for x in ('OPENAI_API_KEY','ACCESS_TOKEN','GEMINI_API_KEY','RAI_LEASE_TOKEN'))
if scenario=='wrong_id': send({'id':9,'result':{}});sys.exit(0)
if scenario=='bool_id': send({'id':True,'result':{}});sys.exit(0)
if scenario=='bad_json': sys.stdout.write('{broken\n');sys.stdout.flush();sys.exit(0)
if scenario=='duplicate':sys.stdout.write('{"id":1,"id":1,"result":{}}\n');sys.stdout.flush();sys.exit(0)
if scenario=='oversize':sys.stdout.write('X'*262150+'\n');sys.stdout.flush();sys.exit(0)
if scenario=='rpc_error':send({'id':1,'error':{'code':-32603,'message':'sensitive diagnostic'}});sys.exit(0)
send({'id':1,'result':{'userAgent':'test','platformFamily':'windows'}})
nextmsg=read()
assert nextmsg.get('method')=='initialized'
if scenario=='approval':send({'id': 99,'method':'item/commandExecution/requestApproval','params':{}});sys.exit(0)
if scenario=='init_only':sys.exit(0)
thread=read()
if scenario=='missing_thread':send({'id':2,'result':{'thread':{}}});sys.exit(0)
assert thread.get('method')=='thread/start'
assert thread['params']['sandbox']=='read-only'
assert thread['params']['approvalPolicy']=='never'
assert thread['params']['ephemeral'] is True
assert thread['params']['model'] is None
if scenario=='thread_rpc_error':send({'id':2,'error':{'code':-32602,'message':'sensitive token example'}});sys.exit(0)
send({'id':2,'result':{'thread':{'id':'fake-thread-123'}}})
# If turn/start is accidentally sent, fail.  The client must instead close stdin.
try:
 leftover=sys.stdin.readline()
 assert not leftover, 'unexpected additional RPC!'
except KeyboardInterrupt:
 pass
