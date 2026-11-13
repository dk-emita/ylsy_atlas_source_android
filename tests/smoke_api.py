"""Offline API smoke tests, run while python run.py --no-browser is serving."""
import os, pathlib, json, requests
from urllib.parse import urlparse
url=os.environ['ATLAS_TEST_URL']
s=requests.Session()
token=url.split('token=')[1]
base=f'{urlparse(url).scheme}://{urlparse(url).netloc}/api/'
h={'X-Atlas-Token':token}
def api(path,method='GET',data=None,success=True):
 r=s.request(method,base+path,headers=h,json=data,timeout=15)
 if success:r.raise_for_status()
 return r
for name in ('universities','programs','advisors','tasks','documents','ielts_sessions','events','attachments'):
 assert api(name).json()==[],name
assert len(api('guide').json())==46
assert len(api('templates').json())>=16
u=api('universities','POST',{'name':'Integration Test University','short':'IT Uni','country':'Turkey'}).json(); print('uni',u['id'])
assert api('universities','POST',{'name':'Integration Test University','short':'IT Uni'} ,False).status_code==400
p=api('programs','POST',{'university_id':u['id'],'name':'Mechanical Engineering PhD','deadline':'2027-12-01','deadline_verified':0}).json()
a=api('advisors','POST',{'university_id':u['id'],'program_id':p['id'],'name':'Dr Example'}).json()
t=api('tasks','POST',{'title':'Referans mektubu','guide_key':'3.7','source_page':29,'track':'Rehber'}).json()
api('tasks/'+str(t['id']),'PUT',{'status':'done'})
d=api('documents','POST',{'title':'Research Concept','kind':'SoP','html':'<p>test <b>bold</b></p>'}).json()
assert api(f'documents/{d["id"]}/export.docx').content[:2]==b'PK'
assert api('overview').json()['done']==1
assert len(api('backup').content)>100
assert api('search?q=Integration').json()
assert api('tasks.csv').content.startswith(b'\xef\xbb\xbf')
api('universities/'+str(u['id']),'DELETE')
assert api('programs').json()==[]
assert api('advisors').json()==[]
print('PASS: empty startup, 46 guide sections, 16+ templates, normalized CRUD, docx, backup, search, cascading delete')
