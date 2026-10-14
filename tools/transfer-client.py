"""Small native protocol probe. ONLY isolated fixtures, never production users.

SPDX-License-Identifier: AGPL-3.0-only
Hugo-Romm, 2026. No private integration, credentials or fixture data included.
"""
import argparse,hashlib,json,socket,struct,time
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--port',type=int,default=30814)
p.add_argument('--fixture-key',default='isolated-client-key',help='Must match the isolated authentication backend; not a real credential')
p.add_argument('--asset',required=True);p.add_argument('--size',type=int,required=True)
p.add_argument('--sha256',required=True);p.add_argument('--stall',action='store_true')
p.add_argument('--timeout',type=int,default=30);a=p.parse_args()
assert a.size>=65536 and len(a.sha256)==64 and a.timeout<=120
with socket.socket() as s:
 s.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4096);s.settimeout(a.timeout)
 s.connect(('127.0.0.1',a.port))
 def send(data):s.sendall(struct.pack('<i',len(data))+data)
 def exact(n):
  data=bytearray()
  while len(data)<n:
   block=s.recv(n-len(data))
   if not block:raise EOFError('native socket closed')
   data.extend(block)
  return bytes(data)
 def packet():
  n=struct.unpack('<i',exact(4))[0];assert 0<n<1024*1024
  return exact(n)
 s.sendall(b'C');send(b'VC2.7');assert packet()==b'A'
 send(a.fixture_key.encode());assert packet().startswith(b'P')
 send(b'f'+a.asset.encode());assert packet()==b'AG'
 first=exact(65536)
 if a.stall:
  print(json.dumps({'mode':'stalled','read_bytes':len(first),'fixture_only':True}),flush=True)
  # Do not drain the raw file: invoke stop/restart/kick in a separate fixture console.
  time.sleep(a.timeout)
 else:
  digest=hashlib.sha256(first);remaining=a.size-len(first)
  while remaining:
   block=s.recv(min(65536,remaining));assert block,'unexpected EOF'
   digest.update(block);remaining-=len(block)
  assert digest.hexdigest()==a.sha256
  send(b'Done');assert packet().startswith(b'U');assert packet().startswith(b'M');send(b'H')
  print(json.dumps({'mode':'normal','read_bytes':a.size,'sha256_confirmed':True,'fixture_only':True}),flush=True)
  time.sleep(a.timeout)
