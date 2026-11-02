"""Fixed-origin Ollama adapter: no cloud/model management, no silent truncation.

Open Notebook 1.15 / Esperanto 2.28 do not expose think/truncate controls.
This adapter leaves upstream source untouched and logs metrics, never prompts.
"""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx,json,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ALIASES={'research-qwen35:abliterated','research-qwen35:standard'}
EMBEDDINGS={'qwen3-embedding:4b','qwen3-embedding:0.6b'}
ALLOWED=ALIASES|EMBEDDINGS
UPSTREAM='http://127.0.0.1:11436'
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def error(self,status,message):
  body=json.dumps({'error':message}).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):self.handle_request()
 def do_POST(self):self.handle_request()
 def handle_request(self):
  path=self.path
  if path.startswith('/deepseek/'):
   from deepseek_adapter import handle_deepseek
   return handle_deepseek(self)
  if self.command=='POST' and path=='/v1/audio/transcriptions':
   from stt_adapter import transcribe_request
   return transcribe_request(self)
  if (self.command,path) not in {('GET','/api/tags'),('GET','/api/version'),('POST','/api/show'),('POST','/api/chat'),('POST','/api/embed'),('POST','/api/embeddings')}:
   return self.error(404,'Endpoint not exposed by local research adapter')
  payload=None;model=None
  if self.command=='POST':
   try:
    length=int(self.headers.get('Content-Length','0'))
    if length<=0 or length>4*1024*1024:return self.error(413,'JSON body must be between 1 byte and 4 MiB')
    payload=json.loads(self.rfile.read(length))
    if not isinstance(payload,dict):raise ValueError('Expected JSON object')
   except (ValueError,UnicodeDecodeError):return self.error(400,'Invalid JSON body')
   model=payload.get('model')
   if not isinstance(model,str) or model not in ALLOWED:return self.error(403,'Model is not in the local research allowlist')
   if path=='/api/chat':
    if model not in ALIASES:return self.error(400,'Chat requires a language model')
    payload['think']=False
    payload['truncate']=False
    payload['shift']=False
    opts=payload.setdefault('options',{})
    if not isinstance(opts,dict):return self.error(400,'options must be an object')
    opts.update(num_ctx=65536,num_batch=256)
    opts['num_predict']=4096
    payload['keep_alive']='2m'
   elif path in ['/api/embed','/api/embeddings']:
    if model not in EMBEDDINGS:return self.error(400,'Embedding endpoint requires an embedding model')
    payload['truncate']=False
    if not isinstance(payload.get('options',{}),dict):return self.error(400,'options must be an object')
    payload['options']={**payload.get('options',{}),'num_ctx':4096,'num_batch':256}
    payload['keep_alive']='2m'
  t=time.perf_counter();first=None;last=None;started=False
  try:
   with httpx.Client(timeout=540,trust_env=False) as client:
    with client.stream(self.command,UPSTREAM+path,json=payload) as r:
     self.send_response(r.status_code);self.send_header('Content-Type',r.headers.get('content-type','application/json'));self.send_header('Connection','close');self.end_headers();started=True
     if path=='/api/tags' and r.status_code==200:
      data=json.loads(r.read());data['models']=[m for m in data.get('models',[]) if m['name'] in ALLOWED];self.wfile.write(json.dumps(data).encode())
     else:
      buf=b''
      for chunk in r.iter_bytes():
       self.wfile.write(chunk);self.wfile.flush()
       if path=='/api/chat':
        buf+=chunk
        while b'\n' in buf:
         line,buf=buf.split(b'\n',1)
         try:
          obj=json.loads(line)
          if obj.get('message',{}).get('content') and first is None:first=time.perf_counter()-t
          if obj.get('done'):last={k:obj.get(k) for k in ['done_reason','total_duration','load_duration','prompt_eval_count','prompt_eval_duration','eval_count','eval_duration']}
         except ValueError:pass
     status=r.status_code
  except (BrokenPipeError,ConnectionResetError):status=499
  except Exception as e:
   status=502
   if not started:self.error(502,type(e).__name__+' contacting local Ollama')
  finally:
   self.close_connection=True
   if path in ['/api/chat','/api/embed','/api/embeddings']:
    rec={'time':time.time(),'path':path,'model':model,'status':status,'wall_s':time.perf_counter()-t,'ttft_s':first,'timings':last}
    with (ROOT/'logs/inference-metrics.jsonl').open('a') as f:f.write(json.dumps(rec)+'\n')
if __name__=='__main__':
 server=ThreadingHTTPServer(('127.0.0.1',11437),Handler);server.daemon_threads=True;server.serve_forever()
