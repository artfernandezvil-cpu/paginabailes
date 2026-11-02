import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
BOOT=tempfile.TemporaryDirectory(prefix='bc-import-')
os.environ['BAILES_DATA_DIR']=BOOT.name
spec=importlib.util.spec_from_file_location('bc_server',ROOT/'server.py')
server=importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='bc-test-')
        server.DATA_DIR=Path(self.directory.name)
        server.init_db()
        self.password=secrets.token_urlsafe(20)
        with server.connect() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',('admin','admin@example.test','Administración',server.password_hash(self.password),'admin'))
        self.cookie=''
        self.csrf=''

    def tearDown(self):
        self.directory.cleanup()

    def call(self,path,method='GET',body=None,auth=False,headers=None):
        payload=json.dumps(body).encode() if body is not None else b''
        env={'PATH_INFO':path,'REQUEST_METHOD':method,'CONTENT_LENGTH':str(len(payload)),'CONTENT_TYPE':'application/json','HTTP_HOST':'test.local','REMOTE_ADDR':'127.0.0.1','wsgi.url_scheme':'http','wsgi.input':io.BytesIO(payload)}
        if auth:env.update(HTTP_COOKIE=self.cookie,HTTP_X_CSRF_TOKEN=self.csrf)
        if headers:env.update(headers)
        captured={}
        def start(status,hs):captured.update(status=int(status[:3]),headers=dict(hs))
        raw=b''.join(server.app(env,start))
        value=json.loads(raw) if 'application/json' in captured['headers'].get('Content-Type','') else raw
        return captured['status'],value,captured['headers']

    def login(self,email='admin@example.test',password=None):
        status,value,headers=self.call('/api/auth/login','POST',{'email':email,'password':password or self.password})
        self.assertEqual(status,200,value)
        self.cookie=headers['Set-Cookie'].split(';')[0]
        self.csrf=value['csrf']
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertIn('SameSite=Lax',headers['Set-Cookie'])
        return value

    def state(self):
        status,value,_=self.call('/api/state')
        self.assertEqual(status,200)
        return value

    def sample(self,kind='baile'):
        r=copy.deepcopy(next(x for x in self.state()['records'] if x['type']==kind))
        for key in ['id','markerNumber','color','revision']:r.pop(key,None)
        r['name']='Agrupación de prueba' if kind=='baile' else 'Fiesta de prueba'
        return r

    def test_seed_and_marker_identity(self):
        value=self.state()
        self.assertEqual(len(value['records']),185)
        self.assertEqual(sum(x['type']=='baile' for x in value['records']),52)
        self.assertEqual(len(value['territories']),346)
        self.assertEqual(len(set(x['color'] for x in value['records'])),185)
        self.assertEqual(len(set(x['markerNumber'] for x in value['records'])),185)
        self.assertFalse(value['contributions'])
        self.assertTrue(all(not x['participantIds'] for x in value['records']))

    def test_authentication_csrf_and_logout(self):
        self.assertEqual(self.call('/api/admin/export')[0],401)
        self.assertEqual(self.call('/api/auth/login','POST',{'email':'admin@example.test','password':'incorrecta'})[0],401)
        self.login()
        status,value,_=self.call('/api/auth/session',auth=True)
        self.assertEqual(value['user']['id'],'admin')
        self.assertNotIn('password',value['user'])
        self.assertEqual(self.call('/api/admin/records','POST',self.sample(),True,{'HTTP_X_CSRF_TOKEN':''})[0],403)
        self.assertEqual(self.call('/api/admin/records','POST',self.sample(),True,{'HTTP_ORIGIN':'https://other.test'})[0],403)
        self.assertEqual(self.call('/api/auth/logout','POST',{},True)[0],200)
        self.assertEqual(self.call('/api/admin/export',auth=True)[0],401)

    def test_crud_links_conflicts_and_persistence(self):
        self.login()
        status,baile,_=self.call('/api/admin/records','POST',self.sample(),True)
        self.assertEqual(status,200,baile)
        fiesta=self.sample('fiesta');fiesta.update(participantIds=[baile['id']],date='2027-05-08',month=2)
        status,created,_=self.call('/api/admin/records','POST',fiesta,True)
        self.assertEqual(status,200,created)
        self.assertEqual(created['month'],5)
        saved=next(x for x in self.state()['records'] if x['id']==created['id'])
        self.assertEqual(saved['participantIds'],[baile['id']])
        stale=copy.deepcopy(saved);saved['name']='Fiesta modificada'
        self.assertEqual(self.call('/api/admin/records/'+saved['id'],'PUT',saved,True)[0],200)
        self.assertEqual(self.call('/api/admin/records/'+saved['id'],'PUT',stale,True)[0],409)
        with server.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM participations').fetchone()[0],1)
            self.assertTrue(c.execute('SELECT payload FROM records WHERE id=?',(saved['id'],)).fetchone())
        baile=next(x for x in self.state()['records'] if x['id']==baile['id']);baile['fiestaIds']=[]
        self.assertEqual(self.call('/api/admin/records/'+baile['id'],'PUT',baile,True)[0],200)
        self.assertFalse(next(x for x in self.state()['records'] if x['id']==saved['id'])['participantIds'])

    def test_record_validation(self):
        self.login();value=self.sample();value['lat']=1000;value['precision']='exacta'
        self.assertEqual(self.call('/api/admin/records','POST',value,True)[0],400)
        value=self.sample();value['color']=self.state()['records'][0]['color']
        self.assertEqual(self.call('/api/admin/records','POST',value,True)[0],400)
        value=self.sample();value['photoUrl']='javascript:alert(1)'
        self.assertEqual(self.call('/api/admin/records','POST',value,True)[0],400)
        value=self.sample('fiesta');value['participantIds']=['missing']
        self.assertEqual(self.call('/api/admin/records','POST',value,True)[0],400)
        self.assertEqual(len(self.state()['records']),185)

    def test_territory_updates_reference_points_only(self):
        self.login();value=self.sample();value.update(precision='exacta',lat=-32.4,lng=-70.4)
        _,created,_=self.call('/api/admin/records','POST',value,True)
        t=copy.deepcopy(next(x for x in self.state()['territories'] if x['code']==created['communeCode']))
        t.update(lat=-32.6,lng=-70.6,name='Comuna editada')
        self.assertEqual(self.call('/api/admin/territories/'+t['code'],'PUT',t,True)[0],200)
        records=[r for r in self.state()['records'] if r['communeCode']==t['code']]
        self.assertTrue(all(r['commune']=='Comuna editada' for r in records))
        self.assertEqual(next(r for r in records if r['id']==created['id'])['lat'],-32.4)
        self.assertTrue(all(r['lat']==-32.6 for r in records if r['precision']=='comuna'))

    def contribution(self):
        raw=b'\x89PNG\r\n\x1a\n'+b'valid-for-signature-test'
        return {'name':'Persona de prueba','title':'Recuerdo de una fiesta','body':'Este es un testimonio de prueba.','contact':'privado@example.test','kind':'fotografia','consent':True,'files':[{'name':'foto.png','mime':'image/png','data':base64.b64encode(raw).decode()}]}

    def test_guest_upload_moderation_and_private_contact(self):
        status,submitted,_=self.call('/api/contributions','POST',self.contribution())
        self.assertEqual(status,200,submitted)
        self.assertFalse(self.state()['contributions'])
        self.login();_,pending,_=self.call('/api/admin/contributions',auth=True)
        self.assertEqual(pending[0]['contact'],'privado@example.test')
        mid=pending[0]['files'][0]['id']
        self.assertEqual(self.call('/media/'+mid)[0],404)
        self.assertEqual(self.call('/media/'+mid,auth=True)[0],200)
        self.assertEqual(self.call('/api/admin/contributions/'+submitted['id'],'PATCH',{'status':'approved'},True)[0],200)
        public=self.state()['contributions'][0]
        self.assertNotIn('contact',public)
        self.assertNotIn('consent',public)
        self.assertEqual(self.call('/media/'+mid)[0],200)
        self.call('/api/admin/contributions/'+submitted['id'],'PATCH',{'status':'rejected'},True)
        self.assertEqual(self.call('/media/'+mid)[0],404)
        self.assertFalse(self.state()['contributions'])

    def test_consent_and_file_validation(self):
        value=self.contribution();value['consent']=False
        self.assertEqual(self.call('/api/contributions','POST',value)[0],400)
        value=self.contribution();value['files'][0]['data']=base64.b64encode(b'<script>bad</script>').decode()
        self.assertEqual(self.call('/api/contributions','POST',value)[0],400)
        value=self.contribution();value['videoUrl']='javascript:bad'
        self.assertEqual(self.call('/api/contributions','POST',value)[0],400)

    def test_assets_contents_and_version_recovery(self):
        self.login();image=self.contribution()['files'][0]
        status,asset,_=self.call('/api/admin/assets','POST',image,True)
        self.assertEqual(status,200,asset)
        self.assertEqual(self.call(asset['url'])[0],200)
        before=self.state();contents=copy.deepcopy(before['contents']);contents['appearance']['logoArt']=asset['url'];contents['intro']['title']='Portada editada'
        self.assertEqual(self.call('/api/admin/contents','PUT',contents,True,{'HTTP_IF_MATCH':'0'})[0],200)
        self.assertEqual(self.call('/api/admin/contents','PUT',contents,True,{'HTTP_IF_MATCH':'0'})[0],409)
        self.assertEqual(self.state()['contents']['intro']['title'],'Portada editada')
        _,versions,_=self.call('/api/admin/revisions',auth=True)
        self.assertEqual(self.call('/api/admin/revisions/'+str(versions[0]['id']),'POST',{},True)[0],200)
        self.assertEqual(self.state()['contents']['intro']['title'],before['contents']['intro']['title'])

    def test_removed_record_can_be_recovered(self):
        self.login();record=self.state()['records'][0]
        self.assertEqual(self.call('/api/admin/records/'+record['id'],'DELETE',auth=True)[0],200)
        self.assertEqual(len(self.state()['records']),184)
        _,versions,_=self.call('/api/admin/revisions',auth=True)
        self.assertEqual(self.call('/api/admin/revisions/'+str(versions[0]['id']),'POST',{},True)[0],200)
        recovered=next(r for r in self.state()['records'] if r['id']==record['id'])
        self.assertEqual(recovered['color'],record['color'])
        self.assertEqual(len(self.state()['records']),185)

    def test_users_and_editor_permissions(self):
        self.login();password=secrets.token_urlsafe(15)
        status,new,_=self.call('/api/admin/users','POST',{'email':'editor@example.test','name':'Edición','role':'editor','password':password},True)
        self.assertEqual(status,200,new)
        self.login('editor@example.test',password)
        self.assertEqual(self.call('/api/admin/users',auth=True)[0],403)
        self.assertEqual(self.call('/api/admin/records','POST',self.sample(),True)[0],200)
        self.login()
        self.assertEqual(self.call('/api/admin/users/admin','PATCH',{'active':False},True)[0],400)
        self.assertEqual(self.call('/api/admin/users/'+new['id'],'PATCH',{'active':False},True)[0],200)
        self.assertEqual(self.call('/api/auth/login','POST',{'email':'editor@example.test','password':password})[0],401)

    def test_private_files_cannot_be_downloaded_as_static(self):
        self.assertEqual(self.call('/../runtime/archive.sqlite')[0],404)
        self.assertEqual(self.call('/%2e%2e/server.py')[0],404)
        self.assertEqual(self.call('/server.py')[0],404)
        status,html,_=self.call('/')
        self.assertEqual(status,200)
        self.assertIn(b'const BC_SEED=',html)
        self.assertNotIn(b'chatgpt.site',html)

if __name__=='__main__':unittest.main()
