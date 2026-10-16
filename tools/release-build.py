"""SPDX-License-Identifier: AGPL-3.0-only
Finite official-stable ARM64 builder. Only public native source enters releases.
Never called by a schedule; explicitly dispatched by one BeamMP update operation.
"""
import hashlib,http.client,json,os,pathlib,re,shutil,subprocess,sys,tarfile,time,urllib.request,urllib.parse
ROOT=pathlib.Path(__file__).resolve().parent.parent;OUT=ROOT/'out';SRC=ROOT/'upstream'
REPO='Hugo-Romm/BeamMP-Server-Transfer-Fix';OFFICIAL='BeamMP/BeamMP-Server'
def sha(p):
    h=hashlib.sha256()
    with pathlib.Path(p).open('rb') as f:
        for b in iter(lambda:f.read(262144),b''):h.update(b)
    return h.hexdigest()
def api(endpoint,data=None,method=None):
    raw=json.dumps(data).encode() if data is not None else None
    req=urllib.request.Request('https://api.github.com/'+endpoint,raw,method=method,headers={'User-Agent':'HCoder-native-builder','Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=40) as r:return json.load(r) if r.status!=204 else None
def run(*args,cwd=None):return subprocess.check_output(args,cwd=cwd,text=True,stderr=subprocess.STDOUT)
def release():
    tag=os.environ['UPSTREAM_TAG'];commit=os.environ['UPSTREAM_COMMIT'];rid=os.environ['UPSTREAM_RELEASE_ID']
    if not re.fullmatch(r'v\d+\.\d+\.\d+',tag) or not re.fullmatch(r'[a-f0-9]{40}',commit) or not rid.isdigit():raise RuntimeError('Invalid immutable official input')
    r=api('repos/'+OFFICIAL+'/releases/tags/'+tag)
    if r['draft'] or r['prerelease'] or str(r['id'])!=rid:raise RuntimeError('Not the selected stable official release')
    resolved=api('repos/'+OFFICIAL+'/commits/'+tag)['sha']
    if resolved!=commit:raise RuntimeError('Official tag changed; refuse mixed inputs')
    a=next(x for x in r['assets'] if x['name']=='BeamMP-Server.ubuntu.24.04.arm64')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',a.get('digest','')):raise RuntimeError('Official ARM64 asset has no authenticated GitHub SHA256 metadata')
    return r,commit,a
def build():
    assert os.uname().machine=='aarch64','Native ARM64 runner required'
    r,commit,asset=release();OUT.mkdir();tag=r['tag_name']
    subprocess.run(['git','clone','--depth=1','--branch',tag,'--recurse-submodules','--shallow-submodules','https://github.com/'+OFFICIAL+'.git',str(SRC)],check=True)
    assert run('git','rev-parse','HEAD',cwd=SRC).strip()==commit
    patch=ROOT/'patches/cancellable-transfer.patch'
    # No version blacklist and no forced fuzz. An actual API/source conflict is explicit.
    subprocess.run(['git','apply','--check',str(patch)],cwd=SRC,check=True)
    subprocess.run(['git','apply',str(patch)],cwd=SRC,check=True)
    if run('git','-C',str(SRC/'vcpkg'),'rev-parse','--is-shallow-repository').strip()=='true':
        subprocess.run(['git','-C',str(SRC/'vcpkg'),'fetch','--unshallow','--filter=blob:none'],check=True)
    env={**os.environ,'VCPKG_MAX_CONCURRENCY':'2','VCPKG_BINARY_SOURCES':'clear'}
    subprocess.run(['cmake','-S',str(SRC),'-B',str(SRC/'build'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DVCPKG_TARGET_TRIPLET=arm64-linux','-DBeamMP-Server_ENABLE_UNIT_TESTING=OFF'],env=env,check=True)
    subprocess.run(['cmake','--build',str(SRC/'build'),'-j2'],env=env,check=True)
    shutil.copy2(SRC/'build/BeamMP-Server',OUT/'BeamMP-Server');subprocess.run(['strip',str(OUT/'BeamMP-Server')],check=True)
    elf=OUT/'BeamMP-Server'
    with elf.open('rb') as f:header=f.read(64)
    assert header[:4]==b'\x7fELF' and int.from_bytes(header[18:20],'little')==183
    linked=run('ldd',str(elf));assert 'not found' not in linked
    version=run(str(elf),'--version',cwd=OUT);assert tag[1:] in version,version
    subs=run('git','submodule','status','--recursive',cwd=SRC)
    # Full modified corresponding source, dependencies' pinned recipes and build tools.
    archive=OUT/'corresponding-source.tar.gz'
    def include(info):
        parts=pathlib.PurePosixPath(info.name).parts
        return None if any(p in {'.git','build','buildtrees','downloads','packages','installed','.cache'} for p in parts) else info
    with tarfile.open(archive,'w:gz') as tar:
        tar.add(SRC,arcname='source',filter=include)
        for name in ['tools','patches','Dockerfile.native','LICENSE','NOTICES.md']:
            if (ROOT/name).exists():tar.add(ROOT/name,arcname='recipe/'+name)
    assert archive.stat().st_size<268435456
    manifest={'format':'hcoder-native-release-v1','upstreamVersion':tag[1:],'version':tag[1:]+'-hcoder.c38.1','upstreamTag':tag,'upstreamCommit':commit,'officialReleaseId':r['id'],'officialAsset':{k:asset[k] for k in ['id','name','size','digest','browser_download_url']},'architecture':'aarch64','sha256':sha(elf),'bytes':elf.stat().st_size,'patch_sha256':sha(patch),'builderCommit':os.environ['GITHUB_SHA'],'builderRun':os.environ['GITHUB_RUN_ID'],'submodules':subs.splitlines(),'source_sha256':sha(archive),'license':'AGPL-3.0-only','url':'https://github.com/'+REPO+'/releases/tag/'+tag+'-hcoder.c38.1','buildEnvironment':{'runnerImage':os.environ.get('ImageVersion'),'compiler':run('c++','--version').splitlines()[0],'packages':run('dpkg-query','-W','-f=${Package}=${Version}\n','build-essential','cmake','ninja-build','pkg-config','git','autoconf','automake','libtool','libc6','libstdc++6','liblua5.3-0','python3').splitlines()}}
    (OUT/'build-result.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'compiled':True,'version':manifest['version'],'sha256':manifest['sha256']}),flush=True)
def publish():
    m=json.loads((OUT/'build-result.json').read_text());assert m['tests']['passed'] and m['tests']['actual_native']
    release();tag=m['upstreamTag']+'-hcoder.c38.1'
    # A published release is immutable to this tool. Existing candidates must be inspected.
    r=api('repos/'+REPO+'/releases',{'tag_name':tag,'target_commitish':os.environ['GITHUB_SHA'],'name':m['version'],'draft':True,'prerelease':False,'body':'Exact official stable '+m['upstreamTag']+' + cancellable resource transfer patch. ARM64 native protocol/shutdown tests and complete corresponding sources attached. No private server code or player data.'})
    published=False
    try:
        for name in ['BeamMP-Server','build-result.json','corresponding-source.tar.gz']:
            f=OUT/name;url=urllib.parse.urlsplit(r['upload_url'].split('{')[0]+'?name='+name)
            assert url.scheme=='https' and url.hostname=='uploads.github.com'
            conn=http.client.HTTPSConnection(url.hostname,timeout=180)
            try:
                conn.putrequest('POST',url.path+'?'+url.query)
                for key,value in {'User-Agent':'HCoder-native-builder','Authorization':'Bearer '+os.environ['GH_TOKEN'],'Content-Type':'application/octet-stream','Content-Length':str(f.stat().st_size)}.items():conn.putheader(key,value)
                conn.endheaders()
                with f.open('rb')as stream:
                    for block in iter(lambda:stream.read(262144),b''):conn.send(block)
                response=conn.getresponse();body=response.read(1048576)
                if response.status!=201:raise RuntimeError('Native asset upload HTTP '+str(response.status))
                uploaded=json.loads(body)
                if uploaded['size']!=f.stat().st_size or uploaded.get('digest')!='sha256:'+sha(f):raise RuntimeError('Incomplete/corrupt release asset upload')
            finally:conn.close()
        api('repos/'+REPO+'/releases/'+str(r['id']),{'draft':False},method='PATCH');published=True
    finally:
        if not published:
            # Only this invocation's incomplete draft, never a historical release.
            try:api('repos/'+REPO+'/releases/'+str(r['id']),method='DELETE')
            except Exception:pass
    print(json.dumps({'published':True,'tag':tag,'release':r['id'],'sha256':m['sha256']}))
if __name__=='__main__':{'build':build,'publish':publish}[sys.argv[1]]()
