"""HTTPS CONNECT relay for explicitly approved public document hosts only."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import socket,select,ipaddress
ALLOWED={'arxiv.org','export.arxiv.org'}
class Handler(BaseHTTPRequestHandler):
 timeout=120
 def log_message(self,*args):pass
 def do_CONNECT(self):
  try:
   host,port=self.path.rsplit(':',1)
   if host.lower() not in ALLOWED or port!='443':return self.send_error(403,'Document host not approved')
   addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
   if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):return self.send_error(403,'Non-public destination denied')
   upstream=None
   for family,typ,proto,_,address in addresses:
    try:
     upstream=socket.socket(family,typ,proto);upstream.settimeout(15);upstream.connect(address);break
    except OSError:
     if upstream:upstream.close()
     upstream=None
   if upstream is None:return self.send_error(502,'Document host unavailable')
   with upstream:
    self.send_response(200,'Connection established');self.end_headers()
    peers=[self.connection,upstream]
    while True:
     ready,_,_=select.select(peers,[],[],120)
     if not ready:break
     for source in ready:
      data=source.recv(65536)
      if not data:return
      (upstream if source is self.connection else self.connection).sendall(data)
  except (OSError,ValueError):pass
  finally:self.close_connection=True
if __name__=='__main__':
 server=ThreadingHTTPServer(('0.0.0.0',3128),Handler);server.daemon_threads=True;server.serve_forever()
