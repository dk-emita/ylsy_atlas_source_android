import base64,json,tempfile,sys,threading
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import create_server
with tempfile.TemporaryDirectory() as d:
 srv=create_server(root=Path(d));threading.Thread(target=srv.serve_forever,daemon=True).start()
 base=f'http://127.0.0.1:{srv.server_port}'
 def api(path,method='GET',obj=None):
  body=json.dumps(obj).encode() if obj is not None else None
  req=Request(base+'/api/'+path,method=method,data=body,headers={'X-Atlas-Token':srv.atlas_token,'Content-Type':'application/json'})
  with urlopen(req,timeout=60) as r:return r.read()
 try:
  assert json.loads(api('guide-pdf/status'))['available']==True
  assert len(json.loads(api('guide')))==46
  assert json.loads(api('documents'))==[]
  x=json.loads(api('documents','POST',{'title':'Document API Test','html':'<p>Delete me</p>'}))
  assert len(json.loads(api('documents')))==1
  api(f'documents/{x["id"]}','DELETE');assert json.loads(api('documents'))==[]
  original=(Path(__file__).resolve().parents[1]/'resources'/'ylsy_us_graduate_application_guide.pdf').read_bytes()
  api('guide-pdf/import','POST',{'content':base64.b64encode(original).decode()})
  assert json.loads(api('guide-pdf/status'))['available']==True
  with urlopen(base+'/pdf?token='+srv.atlas_token,timeout=30) as r:
   assert r.headers['Content-Type']=='application/pdf' and r.read(8)==original[:8]
  assert (Path(d)/'guide'/'ylsy_us_graduate_application_guide.pdf').read_bytes()==original
  print('PASS API: clean install, PDF upload from arbitrary original filename, PDF persistence and serving, document create/delete')
 finally:srv.shutdown();srv.server_close()
