"""SPDX-License-Identifier: AGPL-3.0-only
Finite native CI fixture: local TLS auth, Lua API/console, complete and blocked ZIP.
Only ephemeral GitHub ARM runner. No real credentials, players, Discord or game UI.
"""
import collections,hashlib,http.server,json,os,pathlib,signal,socket,ssl,struct,subprocess,sys,tempfile,threading,time
assert os.environ.get('HCODER_CI_ISOLATED')=='1' and os.environ.get('GITHUB_WORKSPACE') and os.geteuid()==0
elf=pathlib.Path(sys.argv[1]).resolve();manifest=pathlib.Path(sys.argv[2]).resolve();m=json.loads(manifest.read_text());version=m['upstreamVersion']
class Backend(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def answer(self,obj):
        body=obj if isinstance(obj,bytes) else json.dumps(obj).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):self.answer(version.encode() if self.path=='/v/s' else {'status':'2000','code':'200','msg':'isolated'})
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length','0')))
        self.answer({'username':'guestC38Fixture','roles':'USER','guest':True,'identifiers':['beammp:99990001']} if self.path=='/pkToUser' else {'status':'2000','code':'200','msg':'isolated'})
def wait(fn,seconds,rows):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=fn()
        if value:return value
        time.sleep(.05)
    raise RuntimeError('Native fixture deadline: '+'\n'.join(list(rows)[-20:]))
with tempfile.TemporaryDirectory(prefix='beammp-native-c38-') as tmp:
    root=pathlib.Path(tmp);ca=root/'ca.pem';key=root/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(ca),'-subj','/CN=BeamMP isolated fixture','-addext','basicConstraints=critical,CA:TRUE','-addext','subjectAltName=DNS:auth.beammp.com,DNS:backend.beammp.com,DNS:check.beammp.com'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    hosts=pathlib.Path('/etc/hosts');original_hosts=hosts.read_text()
    hosts.write_text(original_hosts+'\n127.0.0.1 auth.beammp.com backend.beammp.com check.beammp.com\n')
    # Only this ephemeral runner trust bundle. Native libraries use their built-in path.
    bundle=pathlib.Path('/etc/ssl/certs/ca-certificates.crt');original_ca=bundle.read_bytes();bundle.write_bytes(original_ca+b'\n'+ca.read_bytes())
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(ca,key)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',443),Backend);server.socket=tls.wrap_socket(server.socket,server_side=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    asset=root/'Resources/Client/C38Fixture.zip';asset.parent.mkdir(parents=True)
    import zipfile
    with zipfile.ZipFile(asset,'w',compression=zipfile.ZIP_STORED) as z:
        with z.open('fixture.bin','w') as f:
            for _ in range(256):f.write(os.urandom(65536))
    h=hashlib.sha256()
    with asset.open('rb')as stream:
        for block in iter(lambda:stream.read(262144),b''):h.update(block)
    digest=h.hexdigest()
    plugin=root/'Resources/Server/Probe';plugin.mkdir(parents=True)
    (plugin/'main.lua').write_text('''function ProbeInit()
 local names={'RegisterEvent','TriggerGlobalEvent','GetServerVersion','GetPlayers','GetPlayerIdentifiers','GetPlayerVehicles','GetPlayerName','GetPlayerCount','SendChatMessage','DropPlayer','RemoveVehicle','TriggerClientEvent','CreateEventTimer'}
 for _,name in ipairs(names) do assert(type(MP[name])=='function','Required native Lua API missing: '..name) end
 print('C38_INIT required-apis='..tostring(#names))
end
function ProbeConsole(line)
 if line=='c38 health' then
  local a,b,c=MP.GetServerVersion()
  print('C38_HEALTH '..tostring(a)..'.'..tostring(b)..'.'..tostring(c)..' '..tostring(type(MP.GetPlayers())))
  return 1
 elseif line=='c38 chat' then
  local players=MP.GetPlayers();local key=next(players);local id=tonumber(key);assert(id~=nil,'No native fixture player')
  assert(type(MP.GetPlayerName(id))=='string','PlayerName must be string');assert(type(MP.GetPlayerIdentifiers(id))=='table','Identifiers must be table')
  -- No vehicle was spawned: the native API deliberately returns nil for this case.
  assert(MP.GetPlayerVehicles(id)==nil,'Empty player vehicles must be nil')
  assert(MP.GetPlayerCount()>=1);MP.SendChatMessage(-1,'C38 native chat fixture');print('C38_CHAT_ACK');return 1
 end
end
function ProbeShutdown() print('C38_SHUTDOWN') end
MP.RegisterEvent('onInit','ProbeInit');MP.RegisterEvent('onConsoleInput','ProbeConsole');MP.RegisterEvent('onShutdown','ProbeShutdown')
''')
    (root/'ServerConfig.toml').write_text('''[General]
AuthKey = "00000000-0000-4000-8000-000000000001"
Debug = false
Private = true
Port = 30814
MaxCars = 100
MaxPlayers = 100
Map = "/levels/gridmap_v2/info.json"
Name = "C38 isolated native fixture"
Description = "No public players"
ResourceFolder = "Resources"
[Misc]
SendErrors = false
''')
    outcomes=[];proc=None;peer=None
    try:
        for mode in ['complete-stop','stalled-stop']:
            print('Native fixture case: '+mode,flush=True)
            rows=collections.deque(maxlen=500);proc=subprocess.Popen([str(elf)],cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
            threading.Thread(target=lambda:[rows.append(line.rstrip()) for line in proc.stdout],daemon=True).start()
            wait(lambda:any('ALL SYSTEMS STARTED SUCCESSFULLY' in x for x in rows),30,rows)
            assert any('C38_INIT required-apis=13' in x for x in rows),list(rows)[-20:]
            proc.stdin.write('c38 health\n');proc.stdin.flush();wait(lambda:any('C38_HEALTH '+version+' table' in x for x in rows),10,rows)
            peer=socket.socket();peer.settimeout(15)
            if mode.startswith('stalled'):peer.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4096)
            peer.connect(('127.0.0.1',30814))
            def send(b):peer.sendall(struct.pack('<i',len(b))+b)
            def exact(n):
                result=bytearray()
                while len(result)<n:
                    b=peer.recv(n-len(result))
                    if not b:raise EOFError('Native closed before expected protocol result')
                    result.extend(b)
                return bytes(result)
            def packet():
                n=struct.unpack('<i',exact(4))[0];assert 0<n<1048576
                return exact(n)
            peer.sendall(b'C');send(b'VC2.7');assert packet()==b'A';send(b'isolated-client-key');assert packet().startswith(b'P')
            send(b'fC38Fixture.zip');assert packet()==b'AG'
            first=exact(65536);verified=False;backpressure=False;chat=False
            if mode.startswith('complete'):
                h=hashlib.sha256(first);remaining=asset.stat().st_size-len(first)
                while remaining:
                    b=peer.recv(min(65536,remaining));assert b;h.update(b);remaining-=len(b)
                assert h.hexdigest()==digest;verified=True
                send(b'Done');assert packet().startswith(b'U');assert packet().startswith(b'M');send(b'H')
                wait(lambda:any('is now synced' in x for x in rows),10,rows)
                proc.stdin.write('c38 chat\n');proc.stdin.flush();wait(lambda:any('C38_CHAT_ACK' in x for x in rows),5,rows)
                for _ in range(8):
                    received=packet()
                    if b'C38 native chat fixture' in received:chat=True;break
                assert chat,'Native Lua chat was not received by the protocol client'
            else:
                def queued():
                    for file in ['tcp','tcp6']:
                        for line in pathlib.Path('/proc/'+str(proc.pid)+'/net/'+file).read_text().splitlines()[1:]:
                            a=line.split()
                            if a[1].endswith(':785E') and a[3]=='01' and int(a[4].split(':')[0],16)>0:return True
                    return False
                backpressure=bool(wait(queued,5,rows))
            # Match the real Unit transport: native exit + EOF, not an open pipe
            # that can keep the native console reader thread alive during teardown.
            start=time.monotonic();proc.stdin.write('exit\n');proc.stdin.flush();proc.stdin.close()
            try:code=proc.wait(timeout=15)
            except subprocess.TimeoutExpired:raise RuntimeError('Native stop deadline '+mode+': '+'\n'.join(list(rows)[-35:]))
            elapsed=time.monotonic()-start
            assert code==0 and any('C38_SHUTDOWN' in x for x in rows),list(rows)[-20:]
            outcomes.append({'case':mode,'code':code,'native_shutdown_hook':True,'stdin_exit_and_EOF':True,'stop_seconds':round(elapsed,3),'resource_sha256_verified':verified,'demonstrated_tx_backpressure':backpressure,'Lua_health_version':version,'required_Lua_API_functions':13,'actual_Lua_chat_to_client':chat,'protocol':'VC2.7'})
            peer.close();peer=None;proc=None
        m['tests']={'passed':True,'actual_native':True,'architecture':os.uname().machine,'cases':outcomes,'authentication':'isolated TLS fixture','Discord':'not tested in public native runner','BeamNG_human_client':False}
        manifest.write_text(json.dumps(m,indent=2)+'\n');print(json.dumps(m['tests']),flush=True)
    finally:
        if peer:peer.close()
        if proc and proc.poll() is None:proc.kill();proc.wait(timeout=5)
        server.shutdown();server.server_close();hosts.write_text(original_hosts);bundle.write_bytes(original_ca)
