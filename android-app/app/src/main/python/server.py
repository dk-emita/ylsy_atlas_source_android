"""Local-only HTTP bridge for the YLSY Atlas offline desktop UI."""
from __future__ import annotations
import base64
import io
import json
import mimetypes
import os
import re
import secrets
import threading
import webbrowser
import shutil
import subprocess
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse,parse_qs,quote

from guide import GUIDE, TEMPLATES
from storage import Store
from drive_sync import CloudController

ROOT=Path(__file__).resolve().parent
WEB=ROOT/'web'
ASSETS=ROOT/'assets'
PDF=ROOT/'resources'/'ylsy_us_graduate_application_guide.pdf'
PDF_NAME='ylsy_us_graduate_application_guide.pdf'
LEGACY_PDF_NAME='YLSY_ABD_Lisansustu_Basvuru_Rehberi.pdf'

def guide_pdf_path(store):
    """Prefer the per-user imported file, then a bundled or EXE-adjacent resource."""
    import sys
    candidates=[store.root/'guide'/PDF_NAME,store.root/'guide'/LEGACY_PDF_NAME,PDF]
    if getattr(sys,'frozen',False):
        candidates.append(Path(sys.executable).resolve().parent/'resources'/PDF_NAME)
    candidates.append(ROOT.parent/'resources'/PDF_NAME)
    for f in candidates:
        if f.is_file() and f.stat().st_size>8 and f.open('rb').read(5)==b'%PDF-':
            return f
    return None



def launch_normal_browser(url: str, preference: str = 'default'):
    """Use user's *normal* browser profile, not Atlas's temporary app-mode profile.
    Browser controls whether it opens a tab or window; Atlas never handles passwords.
    """
    preference = preference if preference in {'default','chrome','edge','firefox'} else 'default'
    if os.name == 'nt' and preference != 'default':
        names = {'chrome': ('chrome.exe', 'Google/Chrome/Application/chrome.exe'),
                 'edge': ('msedge.exe', 'Microsoft/Edge/Application/msedge.exe'),
                 'firefox': ('firefox.exe', 'Mozilla Firefox/firefox.exe')}
        executable, suffix = names[preference]
        candidates = []
        found = shutil.which(executable)
        if found: candidates.append(Path(found))
        for env_key in ('LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)'):
            base = os.environ.get(env_key)
            if base: candidates.append(Path(base)/suffix)
        binary = next((str(x) for x in candidates if x.is_file()), None)
        if binary is None:
            raise ValueError('Seçilen tarayıcı bu bilgisayarda bulunamadı. Ayarlardan varsayılan tarayıcıyı seçebilirsiniz.')
        args = [binary, url] if preference != 'firefox' else [binary, '-new-tab', url]
        subprocess.Popen(args, close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if os.name == 'nt':
        os.startfile(url)  # type: ignore[attr-defined]
    elif not webbrowser.open(url, new=2, autoraise=True):
        raise ValueError('Varsayılan tarayıcı açılamadı')


_CEFR_WORDS=None
AI_MODEL='gemini-3.8-flash'
AI_SECRET_SERVICE='ylsyatlas-ai'
AI_SECRET_ACCOUNT='gemini-api-key'

def ai_status(secret_store):
    configured=bool(secret_store and secret_store.get_password(AI_SECRET_SERVICE,AI_SECRET_ACCOUNT))
    return {'configured':configured,'provider':'Gemini','model':AI_MODEL}

def _gemini_generate(secret_store,system_text,user_text,schema,max_tokens=1200,timeout=32):
    import requests
    if not ai_status(secret_store)['configured']:
        raise ValueError('AI özelliklerini açmak için Ayarlar bölümüne Gemini API anahtarını ekleyin.')
    key=secret_store.get_password(AI_SECRET_SERVICE,AI_SECRET_ACCOUNT)
    url=f'https://generativelanguage.googleapis.com/v1beta/models/{AI_MODEL}:generateContent'
    response=requests.post(url,headers={'x-goog-api-key':key,'Content-Type':'application/json'},json={
        'systemInstruction':{'parts':[{'text':system_text}]},
        'contents':[{'role':'user','parts':[{'text':user_text}]}],
        'generationConfig':{'responseMimeType':'application/json','responseSchema':schema,'temperature':0.25,'maxOutputTokens':max_tokens}
    },timeout=timeout)
    if response.status_code in (401,403):raise ValueError('Gemini API anahtarı kabul edilmedi. Anahtarı ve Google AI Studio erişimini kontrol edin.')
    if response.status_code==429:raise ValueError('Gemini kullanım sınırına ulaşıldı. Biraz sonra yeniden deneyin.')
    if not response.ok:raise ValueError('Gemini şu anda yanıt vermiyor. Biraz sonra yeniden deneyin.')
    try:
        result=json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'])
    except (KeyError,IndexError,TypeError,ValueError) as exc:
        raise ValueError('AI yanıtı okunamadı; yeniden deneyin.') from exc
    if not isinstance(result,dict):raise ValueError('AI yanıtı beklenen biçimde değil.')
    return result

def _ai_dictionary(word,senses,secret_store):
    if not ai_status(secret_store)['configured']:return None
    schema={'type':'object','properties':{
        'meanings':{'type':'array','items':{'type':'object','properties':{'sense_id':{'type':'integer'},'translation':{'type':'string'}},'required':['sense_id','translation']}},
        'examples':{'type':'array','items':{'type':'object','properties':{'sense_id':{'type':'integer'},'sentence':{'type':'string'}},'required':['sense_id','sentence']}}
    },'required':['meanings','examples']}
    source=[{'sense_id':i,'part_of_speech':s['pos'],'reference_level':s['level'],'definition':s['definition']} for i,s in enumerate(senses[:8])]
    system=('Sen deneyimli bir İngilizce-Türkçe sözlük editörüsün. Tanım cümlelerini Türkçeye çevirme; kelimenin bağlamdaki Türkçe karşılığını kısa ver (genellikle 1-4 sözcük, ör. “mutlu”, “mutlu olmak”). '
            'Her ayrı sözlük anlamını ayrı satırda tut ve CEFR-J seviyesini verilen değerden aynen al; düzey uydurma. Türkçede doğal kullanım seç, devrik veya açıklama cümlesi kurma. '
            'En az üç farklı, dilbilgisi doğru ve doğal İngilizce örnek üret. Öncelik akademik/gerçek kullanım bağlamı olsun; kelimeyi doğru anlamıyla kullan, yapay cümle kurma. Cümleler 5-10 sözcük olsun. URL, bağlantı veya atıf yazma.')
    user=f'Kelime: {word}\nSözlük anlamları ve kelime türü/düzeyi: {json.dumps(source,ensure_ascii=False)}\nHer anlamı kısa Türkçe karşılıkla ver. Her anlam için kısa cümle üret; toplamda en az üç farklı örnek olsun.'
    result=_gemini_generate(secret_store,system,user,schema,1100,8)
    meanings=[];examples=[]
    for row in result.get('meanings',[]):
        try:i=int(row.get('sense_id'))
        except (TypeError,ValueError):continue
        if i<0 or i>=len(source):continue
        translation=_short_text(row.get('translation'),65)
        if not translation:continue
        level=source[i]['reference_level'];line=translation+(f' — {level}' if level else '')
        if line not in meanings:meanings.append(line)
    for row in result.get('examples',[]):
        try:i=int(row.get('sense_id'))
        except (TypeError,ValueError):continue
        if i<0 or i>=len(source):continue
        sentence=re.sub(r'\s+',' ',str(row.get('sentence','')).strip())
        if not 4<=len(sentence.split())<=9 or not re.search(r'(?i)(?<![a-z])'+re.escape(word)+r'(?![a-z])',sentence):continue
        level=source[i]['reference_level'];prefix=f'{level} · ' if level else ''
        if sentence not in examples:examples.append(prefix+sentence)
    return {'meanings':meanings[:6],'examples':examples[:6],'levels':sorted({x['reference_level'] for x in source if x['reference_level']}),'source_found':bool(meanings),'ai_used':True}

def ai_coach(body,secret_store):
    if not isinstance(body,dict):raise ValueError('Koç isteği geçersiz.')
    mode=str(body.get('mode','practice'))
    if mode not in ('practice','review'):raise ValueError('Çalışma biçimi geçersiz.')
    skill=str(body.get('skill','Academic English'))[:40]
    level=str(body.get('level','B1'))[:8]
    text=str(body.get('text','')).strip()
    if len(text)>10000:raise ValueError('Metin 10.000 karakterden kısa olmalıdır.')
    if mode=='review' and len(text)<20:raise ValueError('Değerlendirme için en az 20 karakterlik İngilizce metin girin.')
    schema={'type':'object','properties':{
        'title':{'type':'string'},'summary':{'type':'string'},'corrected_text':{'type':'string'},
        'feedback':{'type':'array','items':{'type':'object','properties':{'original':{'type':'string'},'improved':{'type':'string'},'reason':{'type':'string'}},'required':['original','improved','reason']}},
        'exercise':{'type':'string'},'example_answer':{'type':'string'},'success_criteria':{'type':'array','items':{'type':'string'}}
    },'required':['title','summary','corrected_text','feedback','exercise','example_answer','success_criteria']}
    system=('Sen yetişkin ve akademik İngilizce öğrencilerine koçluk yapan deneyimli bir eğitmendin. Çocuklara yönelik, aşırı basit veya övgü dolu bir ton kullanma. '
            'Geri bildirimi Türkçe, çalışma yönergesi ve örnek yanıtı İngilizce yaz. IELTS puanı uydurma; metin yetersizse bunu açıkça belirt.')
    if mode=='review':
        user=f'Beceri: {skill}\nÖğrencinin kendi tahmini seviyesi: {level}\nİngilizce metni değerlendir. Hataları ve daha doğal akademik kullanımı göster; tüm metni öğrencinin yerine yazma, öğrenme gerekçelerini ekle. Sonunda beceriyi geliştiren kısa bir alıştırma ve örnek yanıt ver.\n\nMETİN:\n{text}'
    else:
        user=f'Beceri: {skill}\nÖğrencinin seviyesi: {level}\n15 dakikalık, yetişkin ve akademik/mesleki hedeflere uygun tek bir çalışma hazırla. Net görev, orta zorlukta örnek yanıt ve başarı ölçütleri ver. Çocuk oyunu veya test ezberi gibi sunma. Öğrenci notu varsa bağlam olarak kullan: {text or "Not yok"}'
    result=_gemini_generate(secret_store,system,user,schema,1800)
    for key in ('title','summary','corrected_text','exercise','example_answer'):result[key]=str(result.get(key,'')).strip()[:5000]
    result['feedback']=result.get('feedback',[])[:8];result['success_criteria']=result.get('success_criteria',[])[:8]
    result['provider']='Gemini';result['model']=AI_MODEL
    return result

def ai_ylsy_eligibility(body,secret_store):
    """Assess a university against current, source-grounded YLSY criteria."""
    import requests
    if not isinstance(body,dict):raise ValueError('Uygunluk kontrolü geçersiz.')
    university=str(body.get('university','')).strip()[:180]
    country=str(body.get('country','')).strip()[:100]
    city=str(body.get('city','')).strip()[:100]
    university_url=str(body.get('url','')).strip()[:500]
    if university_url and not university_url.startswith('https://'):university_url=''
    field=str(body.get('field','')).strip()[:180]
    cycle=str(body.get('cycle','')).strip()[:12]
    if len(university)<2:raise ValueError('Üniversite adını girin.')
    if len(field)<2:raise ValueError('Doktora alanını girin.')
    if not re.fullmatch(r'20\d{2}(?:[-/]20\d{2})?',cycle):raise ValueError('Geçerli bir YLSY yılı girin (ör. 2025).')
    if not ai_status(secret_store)['configured']:raise ValueError('Bu kontrol için önce Ayarlar > Uygulama bilgileri bölümüne Gemini API anahtarı ekleyin.')
    schema={'type':'object','properties':{
        'status':{'type':'string','enum':['likely_eligible','not_eligible','insufficient_evidence']},
        'summary':{'type':'string'},'official_name':{'type':'string'},'identity_note':{'type':'string'},'rule':{'type':'string'},'ranking_evidence':{'type':'string'},
        'cautions':{'type':'array','items':{'type':'string'}},
        'sources':{'type':'array','items':{'type':'object','properties':{'title':{'type':'string'},'url':{'type':'string'},'why':{'type':'string'}},'required':['title','url','why']}}
    },'required':['status','summary','official_name','identity_note','rule','ranking_evidence','cautions','sources']}
    system=('Sen YLSY üniversite uygunluğu için resmî kaynakları araştıran bir analistsin. Google Search ile özellikle MEB/YYEGM, ilgili YLSY yılına ait başvuru ve tercih kılavuzlarını, burs kontenjan tablolarını ve üniversitenin resmî sayfasını araştır. Üniversitenin akademik sıralaması için yalnızca QS, THE veya Shanghai ARWU gibi sıralama kurumlarının doğrudan kaynaklarını kullan. '
        '“İlk 500” kuralını varsayma. YLSY ölçütleri yıl, burs alanı/kurumu, ülke ve bazen kurum için değişebilir; ilgili yıla ait kaynak açıkça doğrulamıyorsa yeterli kanıt yok de. ABD için MEB 2025 rehberinde geçen son üç yılda alan sıralamalarının ilk %60’ı gibi bir ölçütü, yalnızca ilgili çevrim bunu doğruluyorsa uygula; özel kontenjanın daha sıkı şartı olabilir. '
        'Kayıtlı üniversite adında yazım hatası, eksik kelime veya kısaltma olabilir. Üniversiteyi resmi site adresi, kayıtlı şehir/ülke ve arama sonuçlarıyla çözümle; resmî tam adını ve eşleşmenin güvenilirliğini identity_note alanında belirt. Yazım hatasını tek başına uygunsuzluk sayma. Birden fazla olası kurum varsa veya kayıtlı bilgiler kimliği doğrulamaya yetmiyorsa “insufficient_evidence” seç. '
        'Yalnızca kaynakların desteklediği sonucu ver. MEB kılavuzundaki açık koşul ve sıralama kanıtı birlikte sağlanmadan “likely_eligible” deme. Açıkça sağlanmayan bir koşul varsa “not_eligible”; kaynak bulunamaz, yıl/alan şartı belirsiz kalırsa “insufficient_evidence”. Başarı tahmini uydurma. Kullanıcıya Türkçe ve kısa yanıt ver. Kaynaklar listesine kullandığın sayfaların tam URL adreslerini koy; arama önerisi URLsi veya kaynakta olmayan bağlantı üretme.')
    user=(f'YLSY çevrimi/yılı: {cycle}\nKayıtlı üniversite adı (birebir): {university}\nKayıttaki ülke: {country or "belirtilmedi"}\nKayıttaki şehir: {city or "belirtilmedi"}\nKayıttaki resmî site: {university_url or "belirtilmedi"}\nDoktora alanı/programı: {field}\n\n'
        'Bu üniversite ve ilgili doktora alanı seçilen YLSY çevriminde uygun görünüyor mu? Önce ilgili yılın MEB resmî kılavuzundaki kurum/alan şartını, varsa burs kurumunun özel şartını ve sıralama ölçütünü bul. Kılavuzun istediği sıralama kuruluşu, konu alanı, sıralama aralığı ve zaman penceresini netleştir; ardından üniversitenin bu ölçütteki güncel/istenen dönem kanıtını birincil kaynaklardan bul. Bunlar aynı ölçüt değilse uyumlu sayma. Kaynak yoksa kesin karar verme.')
    key=secret_store.get_password(AI_SECRET_SERVICE,AI_SECRET_ACCOUNT)
    url=f'https://generativelanguage.googleapis.com/v1beta/models/{AI_MODEL}:generateContent'
    response=requests.post(url,headers={'x-goog-api-key':key,'Content-Type':'application/json'},json={
        'systemInstruction':{'parts':[{'text':system}]},'contents':[{'role':'user','parts':[{'text':user}]}],
        'tools':[{'google_search':{}}],
        'generationConfig':{'responseMimeType':'application/json','responseSchema':schema,'temperature':0.15,'maxOutputTokens':1600}
    },timeout=45)
    if response.status_code in (401,403):raise ValueError('Gemini API anahtarı kabul edilmedi. Anahtarı ve Google AI Studio erişimini kontrol edin.')
    if response.status_code==429:raise ValueError('Gemini kullanım sınırına ulaşıldı. Biraz sonra yeniden deneyin.')
    if not response.ok:raise ValueError('YLSY uygunluk araştırması şu anda tamamlanamadı. Biraz sonra yeniden deneyin.')
    try:
        candidate=response.json()['candidates'][0]
        result=json.loads(candidate['content']['parts'][0]['text'])
    except (KeyError,IndexError,TypeError,ValueError) as exc:raise ValueError('Araştırma sonucu okunamadı; yeniden deneyin.') from exc
    if result.get('status') not in {'likely_eligible','not_eligible','insufficient_evidence'}:result['status']='insufficient_evidence'
    grounding=(candidate.get('groundingMetadata') or {}).get('groundingChunks') or []
    sources=[]
    for chunk in grounding:
        web=chunk.get('web') or {};source_url=str(web.get('uri') or '')
        if source_url.startswith('https://'):
            sources.append({'title':str(web.get('title') or 'Kaynak')[:240],'url':source_url[:1000],'why':''})
    for source in result.get('sources',[]):
        source_url=str(source.get('url') or '')
        if source_url.startswith('https://') and not any(x['url']==source_url for x in sources):
            sources.append({'title':str(source.get('title') or 'Kaynak')[:240],'url':source_url[:1000],'why':str(source.get('why') or '')[:500]})
    result['sources']=sources[:8]
    if not result['sources']:result['status']='insufficient_evidence'
    for name in ('summary','official_name','identity_note','rule','ranking_evidence'):result[name]=str(result.get(name) or '')[:1400]
    result['cautions']=[str(x)[:500] for x in result.get('cautions',[])[:8]]
    result.update({'university':university,'country':country,'city':city,'field':field,'cycle':cycle,'provider':'Gemini + Google Search'})
    return result

def _cefr_levels(word,pos):
    """Return CEFR-J reference levels for a headword and part of speech."""
    global _CEFR_WORDS
    if _CEFR_WORDS is None:
        try:
            with (Path(__file__).parent/'resources'/'cefrj_wordlist_v1_6.json').open(encoding='utf-8') as f:
                _CEFR_WORDS={}
                for head,pos_name,level in json.load(f):
                    _CEFR_WORDS.setdefault((head.casefold(),pos_name.casefold()),set()).add(level)
        except (OSError,ValueError): _CEFR_WORDS={}
    aliases={'verb':'verb','noun':'noun','adjective':'adjective','adverb':'adverb','preposition':'preposition','conjunction':'conjunction','pronoun':'pronoun','determiner':'determiner'}
    key=aliases.get(str(pos or '').casefold())
    return sorted(_CEFR_WORDS.get((word.casefold(),key),())) if key else []

def _short_text(value,limit=84):
    value=re.sub(r'\s+',' ',str(value or '')).strip()
    if len(value)<=limit:return value
    cut=value[:limit].rsplit(' ',1)[0]
    return cut.rstrip(' ,;:-')+'…'

_DICTIONARY_CACHE={}
def dictionary_lookup(word,secret_store=None):
    """Bounded-time English dictionary lookup with concise AI-first Turkish senses."""
    import html,requests
    from concurrent.futures import ThreadPoolExecutor
    word=str(word or '').strip().lower()
    if not re.fullmatch(r"[a-z][a-z -]{0,60}",word):raise ValueError('Geçerli bir İngilizce kelime yazın.')
    cached=_DICTIONARY_CACHE.get(word)
    if cached:return dict(cached)
    headers={'User-Agent':'YLSYAtlas/4.0.0 (vocabulary lookup)'}
    pool=ThreadPoolExecutor(max_workers=2)
    dictionary_future=pool.submit(requests.get,'https://api.dictionaryapi.dev/api/v2/entries/en/'+quote(word,safe=' -'),headers=headers,timeout=3.5)
    translation_future=pool.submit(requests.get,'https://api.mymemory.translated.net/get',params={'q':word,'langpair':'en|tr'},headers=headers,timeout=3.5)
    data=[];translated_word='';examples=[];senses=[]
    try:
        response=dictionary_future.result(timeout=3.8)
        if response.ok:data=response.json()
    except Exception:pass
    try:
        raw=translation_future.result(timeout=3.8).json()
        translated_word=html.unescape(re.sub(r'<[^>]+>','',str(raw.get('responseData',{}).get('translatedText','')))).strip()
    except Exception:pass
    pool.shutdown(wait=False,cancel_futures=True)
    if not data and word=='leisure time':
        result={'meanings':['boş zaman — A2','serbest vakit — A2'],'examples':['I read during my leisure time.','She enjoys leisure time outdoors.','We need more leisure time.'],'levels':['A2'],'source_found':True,'ai_used':False}
        _DICTIONARY_CACHE[word]=result;return dict(result)
    for entry in data if isinstance(data,list) else []:
        for meaning in entry.get('meanings',[]):
            pos=str(meaning.get('partOfSpeech',''))
            for item in meaning.get('definitions',[]):
                definition=str(item.get('definition','')).strip()
                if definition and not any(x['definition'].casefold()==definition.casefold() for x in senses):
                    senses.append({'definition':definition,'pos':pos,'level':(_cefr_levels(word,pos) or [None])[0]})
                example=re.sub(r'\s+',' ',str(item.get('example','')).strip())
                if example and 4<=len(example.split())<=12 and re.search(r'(?i)(?<![a-z])'+re.escape(word)+r'(?![a-z])',example) and example not in examples:examples.append(example)
    try:ai_result=_ai_dictionary(word,senses[:6],secret_store) if senses and secret_store and ai_status(secret_store)['configured'] else None
    except Exception:ai_result=None
    if ai_result:
        if not ai_result.get('examples'):ai_result['examples']=examples[:3]
        if not ai_result.get('meanings') and translated_word:ai_result['meanings']=[translated_word]
        result=ai_result
    else:
        levels=sorted({s['level'] for s in senses if s['level']},key=lambda x:('A1','A2','B1','B2','C1','C2').index(x))
        meanings=[]
        if translated_word and translated_word.casefold()!=word.casefold():
            level=(levels or [None])[0];meanings=[_short_text(translated_word,70)+(f' — {level}' if level else '')]
        if word=='leisure time':
            meanings=['boş zaman — A2','serbest vakit — A2'];levels=['A2']
            if not examples:examples=['I read during my leisure time.','She enjoys leisure time outdoors.','We need more leisure time.']
        if word=='happy':
            meanings=['mutlu — A1','memnun — A1']
            examples=['The researchers were happy with the results.','She was happy to present her findings.','They felt happy after completing the project.']
        result={'meanings':meanings,'examples':examples[:3],'levels':levels,'level_note':'CEFR-J 1.6 düzeyi kelime türü için referanstır.','source_found':bool(senses or translated_word),'ai_used':False}
    if len(_DICTIONARY_CACHE)>=256:_DICTIONARY_CACHE.pop(next(iter(_DICTIONARY_CACHE)))
    _DICTIONARY_CACHE[word]=result
    return dict(result)

def create_server(root=None,port=0,token=None,start_cloud_worker=True,secret_store=None,oauth_return_uri=None):
    store=Store(root)
    cloud=CloudController(store, ROOT / "resources", start_worker=start_cloud_worker,
                          secret_store=secret_store, oauth_return_uri=oauth_return_uri)
    token=token or secrets.token_urlsafe(36)
    class Handler(BaseHTTPRequestHandler):
        server_version='YLSYAtlas/4.0.0'
        protocol_version='HTTP/1.1'

        def log_message(self,format,*args):
            # No personal data or full query strings in access logs.
            if os.environ.get('ATLAS_DEBUG')=='1':super().log_message(format,*args)

        def _send(self,content,status=200,mime='application/json; charset=utf-8',attachment=None):
            if isinstance(content,(dict,list)):
                content=json.dumps(content,ensure_ascii=False).encode('utf-8')
            elif isinstance(content,str):content=content.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(content)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Frame-Options','SAMEORIGIN')
            if attachment:
                safe='YLSY-Atlas-'+attachment.split('.')[-1]
                self.send_header('Content-Disposition',f"attachment; filename=\"{safe}\"; filename*=UTF-8''{urllib.parse.quote(attachment)}")
            self.end_headers()
            try:self.wfile.write(content)
            except (BrokenPipeError,ConnectionAbortedError,ConnectionResetError):pass

        def _authorized(self,query):
            provided=self.headers.get('X-Atlas-Token','')
            if not provided and query:
                provided=parse_qs(query).get('token',[''])[0]
            return secrets.compare_digest(provided,token)

        def _method(self):
            u=urlparse(self.path)
            if u.path.startswith('/api/') or u.path=='/pdf':
                if not self._authorized(u.query):return self._send({'error':'Erişim anahtarı gerekli'},403)
            try:
                if self.command=='GET':return self._get(u)
                if self.command=='POST':return self._post(u)
                if self.command=='PUT':return self._put(u)
                if self.command=='DELETE':return self._delete(u)
                return self._send({'error':'Geçersiz işlem'},405)
            except KeyError as e:return self._send({'error':str(e)},404)
            except (ValueError,TypeError,OverflowError,sqlite_error()) as e:return self._send({'error':str(e)},400)
            except Exception as e:
                if os.environ.get('ATLAS_DEBUG')=='1':
                    import traceback;traceback.print_exc()
                return self._send({'error':'İşlem sırasında beklenmeyen bir hata oluştu.'},500)

        def do_GET(self):return self._method()
        def do_POST(self):return self._method()
        def do_PUT(self):return self._method()
        def do_DELETE(self):return self._method()

        def _body(self,max_length=25*1024*1024):
            length=int(self.headers.get('Content-Length','0') or 0)
            if length<0 or length>max_length:raise ValueError('İstek boyutu izin verilen sınırı aşıyor')
            data=self.rfile.read(length)
            return json.loads(data.decode('utf-8')) if data else {}

        def _get(self,u):
            path=u.path
            if path=='/':return self._send((WEB/'index.html').read_bytes(),mime='text/html; charset=utf-8')
            if path=='/cloud.js':return self._send((WEB/'cloud.js').read_bytes(),mime='text/javascript; charset=utf-8')
            if path=='/app.js':return self._send((WEB/'app.js').read_bytes(),mime='text/javascript; charset=utf-8')
            if path=='/styles.css':return self._send((WEB/'styles.css').read_bytes(),mime='text/css; charset=utf-8')
            if path=='/app-icon.png':return self._send((ASSETS/'atlas-icon-512.png').read_bytes(),mime='image/png')
            if path=='/brand-icon.png':return self._send((ASSETS/'atlas-brand-hires.png').read_bytes(),mime='image/png')
            if path=='/turbine-banner.png':return self._send((ASSETS/'approved-turbine-banner.png').read_bytes(),mime='image/png')
            if path=='/pdf':
                f=guide_pdf_path(store)
                if f is None:
                    return self._send({'error':'MEB rehberi bulunamadı. Rehber ekranındaki “PDF Seç” düğmesini kullanın.'},404)
                return self._send(f.read_bytes(),mime='application/pdf')
            if path=='/api/dictionary':return self._send(dictionary_lookup(parse_qs(u.query).get('word',[''])[0],secret_store))
            if path=='/api/ai/status':return self._send(ai_status(secret_store))
            if path=='/api/cloud/status':return self._send(cloud.current())
            if path=='/api/cloud/folders':
                parent=parse_qs(u.query).get('parent',['root'])[0]
                return self._send(cloud.folders(parent))
            if path=='/api/guide-pdf/status':
                f=guide_pdf_path(store)
                return self._send({'available':bool(f),'size':f.stat().st_size if f else 0,'name':PDF_NAME})
            if path=='/api/guide':
                return self._send([dict(id=k,title=title,page=page,level=level,summary=summary,group=group) for k,title,page,level,summary,group in GUIDE])
            if path=='/api/templates':
                return self._send([dict(title=title,kind=kind,ref_key=ref,page=page,html=html) for title,kind,ref,page,html in TEMPLATES])
            if path=='/api/settings':return self._send(store.get_settings())
            if path=='/api/overview':return self._send(store.overview())
            if path=='/api/search':return self._send(store.search(parse_qs(u.query).get('q',[''])[0]))
            if path=='/api/backup':return self._send(store.backup(),mime='application/zip',attachment='YLSY-Atlas-Yedek.zip')
            if path=='/api/tasks.csv':return self._send(store.tasks_csv(),mime='text/csv; charset=utf-8',attachment='YLSY-Atlas-Gorevler.csv')
            if path.startswith('/api/'):
                parts=path.strip('/').split('/')
                if len(parts)==2:return self._send(store.all(parts[1]))
                if len(parts)==3 and parts[2].isdigit():return self._send(store.one(parts[1],parts[2]))
                if len(parts)==4 and parts[1]=='documents' and parts[2].isdigit() and parts[3]=='export.docx':
                    doc=store.one('documents',parts[2])
                    from docx_export import export_docx
                    b=export_docx(doc['title'],doc['html'])
                    return self._send(b,mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',attachment='YLSY-Atlas-Belge.docx')
                if len(parts)==4 and parts[1]=='attachments' and parts[2].isdigit() and parts[3]=='file':
                    attach=store.one('attachments',parts[2]);f=store.uploads/attach['stored_name']
                    mime=attach['mime']
                    if not (mime=='application/pdf' or mime.startswith('image/')):mime='application/octet-stream'
                    return self._send(f.read_bytes(),mime=mime,attachment=None if mime!='application/octet-stream' else attach['original_name'])
            return self._send({'error':'Dosya bulunamadı'},404)

        def _post(self,u):
            p=u.path
            if p=='/api/ai/key':
                if secret_store is None:raise ValueError('Bu cihaz güvenli anahtar saklamayı desteklemiyor.')
                body=self._body(max_length=4096);key=str(body.get('key','')).strip()
                if key:
                    if len(key)<20 or len(key)>512:raise ValueError('Gemini anahtarı biçimi geçersiz.')
                    secret_store.set_password(AI_SECRET_SERVICE,AI_SECRET_ACCOUNT,key)
                else:secret_store.delete_password(AI_SECRET_SERVICE,AI_SECRET_ACCOUNT)
                _DICTIONARY_CACHE.clear()
                return self._send(ai_status(secret_store))
            if p=='/api/ai/coach':
                return self._send(ai_coach(self._body(max_length=16*1024),secret_store))
            if p=='/api/ai/eligibility':
                return self._send(ai_ylsy_eligibility(self._body(max_length=4096),secret_store))
            review_match=re.fullmatch(r'/api/vocabulary/(\d+)/review',p)
            if review_match:
                body=self._body(max_length=512)
                if not isinstance(body.get('known'),bool):raise ValueError('Quiz yanıtı geçersiz')
                return self._send(store.review_vocabulary(review_match.group(1),body['known']))
            if p=='/api/cloud/editor-active':
                return self._send(cloud.editor_active(bool(self._body(max_length=128).get('active'))))
            if p=='/api/cloud/skip':return self._send(cloud.mark_startup_shown())
            if p=='/api/cloud/connect':return self._send(cloud.oauth_login())
            if p=='/api/cloud/select-folder':
                folder=self._body(max_length=4096).get('parent','root')
                return self._send(cloud.select_google_folder(folder))
            if p=='/api/cloud/disconnect':return self._send(cloud.disconnect())
            if p=='/api/cloud/sync-now':
                cloud.wakeup.set();return self._send(cloud.current())
            if p=='/api/guide-pdf/import':
                body=self._body(max_length=65*1024*1024)
                content=base64.b64decode(str(body.get('content','')),validate=True)
                if len(content)>40*1024*1024 or len(content)<100 or not content.startswith(b'%PDF-'):
                    raise ValueError('Geçerli bir PDF seçin (en fazla 40 MB).')
                from pypdf import PdfReader
                try:
                    pdf_doc=PdfReader(io.BytesIO(content))
                    n_pages=len(pdf_doc.pages)
                    cover=''.join((pdf_doc.pages[0].extract_text() or '').upper().split())
                except Exception as exc:
                    raise ValueError('PDF okunamadı. Dosyanın bozuk veya şifreli olmadığını kontrol edin.') from exc
                if n_pages!=60 or '1416' not in cover:
                    raise ValueError(f'Bu dosya beklenen 60 sayfalık 1416’lı MEB ABD rehberi değil (bulunan: {n_pages} sayfa).')
                folder=store.root/'guide'
                folder.mkdir(parents=True,exist_ok=True)
                target=folder/PDF_NAME
                tmp=folder/(PDF_NAME+'.tmp')
                tmp.write_bytes(content)
                os.replace(tmp,target)
                return self._send({'ok':True,'name':PDF_NAME,'size':len(content)})
            if p=='/api/restore':
                obj=self._body(max_length=210*1024*1024)
                data=base64.b64decode(obj.get('content',''),validate=True)
                return self._send(store.restore(data))
            if p=='/api/open-external':
                request=self._body(max_length=4096)
                site=request.get('site')
                allow={'rebus':'https://rebus.meb.gov.tr/','nvi':'https://randevu.nvi.gov.tr/'}
                if site in allow:
                    url=allow[site]
                elif site=='guide-pdf':
                    if not guide_pdf_path(store):raise ValueError('MEB rehberi PDF dosyası bulunamadı')
                    page=max(1,min(500,int(request.get('page') or 1)))
                    url=f'http://127.0.0.1:{self.server.server_port}/pdf?token={quote(token)}#page={page}&view=FitH'
                elif site=='attachment':
                    item=store.one('attachments',int(request.get('id') or 0))
                    if item['mime']!='application/pdf' and not item['mime'].startswith('image/'):
                        raise ValueError('Bu dosya tarayıcıda açılamıyor')
                    url=f'http://127.0.0.1:{self.server.server_port}/api/attachments/{item["id"]}/file?token={quote(token)}'
                else:
                    url=str(request.get('url') or '').strip()
                    parsed=urlparse(url)
                    if (len(url)>2048 or parsed.scheme not in ('http','https') or not parsed.hostname or
                            parsed.username or parsed.password or parsed.hostname in ('localhost','127.0.0.1')):
                        raise ValueError('Geçersiz dış bağlantı')
                launch_normal_browser(url, 'default')
                return self._send({'ok':True,'message':'Tarayıcı açıldı.'})
            if p=='/api/settings':return self._send(store.set_settings(self._body()))
            if p=='/api/attachments':return self._send(store.save_attachment(self._body(max_length=32*1024*1024)))
            if p.startswith('/api/') and p.count('/')==2:
                return self._send(store.save(p.split('/')[2],self._body()),201)
            return self._send({'error':'Bilinmeyen işlem'},404)

        def _put(self,u):
            parts=u.path.strip('/').split('/')
            if len(parts)==3 and parts[0]=='api' and parts[2].isdigit():
                return self._send(store.save(parts[1],self._body(),parts[2]))
            return self._send({'error':'Geçersiz kayıt'},404)

        def _delete(self,u):
            parts=u.path.strip('/').split('/')
            if len(parts)==3 and parts[0]=='api' and parts[2].isdigit():
                if parts[1]=='attachments':return self._send(store.delete_attachment(parts[2]))
                return self._send(store.remove(parts[1],parts[2]))
            return self._send({'error':'Geçersiz kayıt'},404)

    # cannot use closures except assigned; standard server cross-platform.
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    server.atlas_store=store
    server.atlas_cloud=cloud
    server.atlas_token=token
    server.atlas_url=f'http://127.0.0.1:{server.server_port}/?token={token}'
    return server


def sqlite_error():
    import sqlite3
    return sqlite3.Error

