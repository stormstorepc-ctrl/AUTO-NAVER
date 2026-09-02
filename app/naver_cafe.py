import json
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
import re
import httpx
from .settings import settings

AUTH_URL='https://nid.naver.com/oauth2.0/authorize'
TOKEN_URL='https://nid.naver.com/oauth2.0/token'
CAFE_API_BASE='https://openapi.naver.com/v1/cafe'
PROFILE_URL='https://openapi.naver.com/v1/nid/me'
TOKEN_FILE=Path('.naver_cafe_token.json')
STATE_FILE=Path('.naver_cafe_state')

class NaverCafeClient:
    def __init__(self)->None:
        self.client_id=settings.naver_client_id; self.client_secret=settings.naver_client_secret
        self.redirect_uri=settings.naver_redirect_uri; self.club_id=settings.naver_cafe_club_id; self.menu_id=settings.naver_cafe_menu_id
        self._token=self._load_token()
    @property
    def configured(self)->bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri and self.club_id and self.menu_id)
    def _load_token(self)->dict[str,Any]:
        try:
            if TOKEN_FILE.exists():
                data=json.loads(TOKEN_FILE.read_text(encoding='utf-8'))
                if isinstance(data,dict): return data
        except Exception: pass
        if settings.naver_cafe_access_token: return {'access_token':settings.naver_cafe_access_token,'token_type':'bearer','expires_at':0}
        return {}
    def _save_token(self,payload:dict[str,Any])->None: TOKEN_FILE.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    def authorization_url(self,reprompt:bool=False)->str:
        if not self.client_id or not self.redirect_uri: raise RuntimeError('NAVER_CLIENT_ID와 NAVER_REDIRECT_URI가 필요합니다.')
        state=secrets.token_urlsafe(24); STATE_FILE.write_text(state,encoding='utf-8')
        params={'response_type':'code','client_id':self.client_id,'redirect_uri':self.redirect_uri,'state':state}
        if reprompt: params['auth_type']='reprompt'
        return AUTH_URL+'?'+urlencode(params)
    def exchange_code(self,code:str,state:str)->dict[str,Any]:
        expected=STATE_FILE.read_text(encoding='utf-8').strip() if STATE_FILE.exists() else ''
        if not expected or not secrets.compare_digest(expected,state): raise RuntimeError('네이버 OAuth state가 일치하지 않습니다. 다시 로그인해주세요.')
        r=httpx.get(TOKEN_URL,params={'grant_type':'authorization_code','client_id':self.client_id,'client_secret':self.client_secret,'code':code,'state':state},timeout=30); r.raise_for_status(); payload=r.json()
        if 'error' in payload: raise RuntimeError(payload.get('error_description') or payload['error'])
        payload['expires_at']=time.time()+int(payload.get('expires_in',3600)); self._token=payload; self._save_token(payload)
        try: STATE_FILE.unlink()
        except FileNotFoundError: pass
        return payload
    def refresh(self)->dict[str,Any]:
        refresh_token=self._token.get('refresh_token')
        if not refresh_token: raise RuntimeError('저장된 refresh token이 없습니다. 네이버 인증을 다시 진행해주세요.')
        r=httpx.get(TOKEN_URL,params={'grant_type':'refresh_token','client_id':self.client_id,'client_secret':self.client_secret,'refresh_token':refresh_token},timeout=30); r.raise_for_status(); payload=r.json()
        if 'error' in payload: raise RuntimeError(payload.get('error_description') or payload['error'])
        payload.setdefault('refresh_token',refresh_token); payload['expires_at']=time.time()+int(payload.get('expires_in',3600)); self._token=payload; self._save_token(payload); return payload
    def access_token(self)->str:
        token=self._token.get('access_token')
        if token and (not self._token.get('expires_at') or time.time()<float(self._token['expires_at'])-60): return str(token)
        return str(self.refresh()['access_token'])
    @staticmethod
    def _naver_form_value(value:str)->str:
        return quote(quote(value or '',encoding='utf-8',safe=''),encoding='ms949',safe='')
    def profile(self)->dict[str,Any]:
        token=self.access_token(); r=httpx.get(PROFILE_URL,headers={'Authorization':f'Bearer {token}','X-Naver-Client-Id':self.client_id,'X-Naver-Client-Secret':self.client_secret},timeout=30); r.raise_for_status(); return r.json()
    def post(self,subject:str,content:str)->dict[str,Any]:
        if not self.club_id or not self.menu_id: raise RuntimeError('NAVER_CAFE_CLUB_ID와 NAVER_CAFE_MENU_ID를 설정해주세요.')
        subject=re.sub(r'\s+',' ',subject or '').strip()[:120]
        clean=re.sub(r'<br\s*/?>','\n',content or '',flags=re.I)
        clean=re.sub(r'<[^>]+>','',clean)
        clean=re.sub(r'\n{3,}','\n\n',clean).strip()
        url=f'{CAFE_API_BASE}/{self.club_id}/menu/{self.menu_id}/articles'
        body=f'subject={self._naver_form_value(subject)}&content={self._naver_form_value(clean)}'.encode('ascii')
        headers={'Authorization':f'Bearer {self.access_token()}','X-Naver-Client-Id':self.client_id,'X-Naver-Client-Secret':self.client_secret,'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'}
        response=httpx.post(url,content=body,headers=headers,timeout=30)
        if response.status_code==401:
            self._token=self.refresh(); headers['Authorization']=f"Bearer {self._token['access_token']}"; response=httpx.post(url,content=body,headers=headers,timeout=30)
        if response.status_code>=400:
            raise RuntimeError(f'네이버 카페 API {response.status_code}: {response.text[:2000]}')
        return response.json()

naver_cafe=NaverCafeClient()
