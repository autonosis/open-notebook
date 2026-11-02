"""Local OpenAI-compatible STT handler, English tiny.en CPU/int8, offline only."""
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import json,os,tempfile,subprocess,threading,time,gc
ROOT=Path(__file__).resolve().parents[1]
LOCK=threading.Lock()
def transcribe_request(h):
 if not LOCK.acquire(blocking=False):return h.error(429,'One transcription is already running; retry later')
 try:
  length=int(h.headers.get('Content-Length','0'))
  if not 0<length<=50*1024*1024:return h.error(413,'Audio request must be at most 50 MiB')
  mime=BytesParser(policy=default).parsebytes(('Content-Type: '+h.headers.get('Content-Type','')+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+h.rfile.read(length))
  fields={p.get_param('name',header='content-disposition'):p.get_payload(decode=True) for p in mime.iter_parts()}
  if fields.get('model',b'').decode()!='faster-whisper-tiny.en':return h.error(400,'Unknown local speech model')
  if not fields.get('file'):return h.error(400,'Missing audio file')
  if fields.get('language',b'en').decode() not in ('en','english'):return h.error(400,'This installed model supports English only')
  if fields.get('response_format',b'json').decode() not in ('json','verbose_json'):return h.error(400,'Only JSON transcription is supported')
  import numpy as np
  os.environ['HF_HUB_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
  from faster_whisper import WhisperModel
  with tempfile.TemporaryDirectory(prefix='open-notebook-stt-') as tmp:
   audio=Path(tmp)/'input';audio.write_bytes(fields['file']);os.chmod(audio,0o600)
   raw=subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-nostdin','-i',str(audio),'-t','1801','-f','s16le','-ar','16000','-ac','1','-'],capture_output=True,check=True,timeout=60).stdout
  a=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768
  if not len(a) or len(a)>1800*16000:return h.error(413,'Audio must contain 1 sample to 30 minutes')
  model=WhisperModel('tiny.en',device='cpu',compute_type='int8',cpu_threads=4,download_root=str(ROOT/'models/whisper'),local_files_only=True)
  segments,info=model.transcribe(a,beam_size=5,language='en',initial_prompt=fields.get('prompt',b'').decode() or None)
  result=[{'id':s.id,'start':s.start,'end':s.end,'text':s.text} for s in segments]
  body=json.dumps({'text':' '.join(s['text'].strip() for s in result),'language':'en','duration':len(a)/16000,'segments':result}).encode()
  del model;gc.collect()
  h.send_response(200);h.send_header('Content-Type','application/json');h.send_header('Content-Length',str(len(body)));h.end_headers();h.wfile.write(body)
 except (ValueError,UnicodeDecodeError):h.error(400,'Invalid multipart request')
 except (subprocess.SubprocessError,RuntimeError):h.error(422,'Local audio decoding or transcription failed')
 except Exception:h.error(500,'Local transcription failed; check installed model and dependencies')
 finally:LOCK.release()
