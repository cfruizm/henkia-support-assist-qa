"""Central access control for Henkia Support Assist."""
from __future__ import annotations
import hashlib, hmac, time
from dataclasses import dataclass
from typing import Any, Mapping
import streamlit as st
from app.ui.brand import render_login_brand

_STATE="_henkia_access_identity"; _FAIL="_henkia_access_failures"; _LOCK="_henkia_access_locked_until"

@dataclass(frozen=True)
class AccessIdentity:
    username: str
    display_name: str
    role: str
    method: str
    @property
    def is_admin(self) -> bool: return self.role.strip().casefold()=="administrator"

def _mapping(v:Any)->Mapping[str,Any]: return v if isinstance(v,Mapping) else {}
def _secret(name:str,default:Any=None)->Any:
    try:return st.secrets.get(name,default)
    except Exception:return default
def _bool(v:Any,default:bool=False)->bool:
    if v is None:return default
    if isinstance(v,bool):return v
    return str(v).strip().casefold() in {"1","true","yes","on"}
def _mode(v:Any)->str:
    value=str(v or "temporary_gate").strip().casefold()
    return {"off":"disabled","none":"disabled","password":"temporary_gate","gate":"temporary_gate","entra":"oidc","entra_id":"oidc"}.get(value,value)
def _identity()->AccessIdentity|None:
    v=st.session_state.get(_STATE)
    if not isinstance(v,Mapping) or not str(v.get("username") or "").strip():return None
    name=str(v["username"]);return AccessIdentity(name,str(v.get("display_name") or name),str(v.get("role") or "pilot_user"),str(v.get("method") or "temporary_gate"))
def _save(i:AccessIdentity)->None:
    st.session_state[_STATE]={"username":i.username,"display_name":i.display_name,"role":i.role,"method":i.method};st.session_state[_FAIL]=0;st.session_state[_LOCK]=0.0
def _clear()->None:st.session_state.pop(_STATE,None)
def _verify(candidate:str,record:Mapping[str,Any])->bool:
    encoded=str(record.get("password_hash") or "").strip()
    if encoded:
        try:
            algorithm,iterations,salt,digest=encoded.split("$",3)
            if algorithm!="pbkdf2_sha256" or int(iterations)<100000:return False
            actual=hashlib.pbkdf2_hmac("sha256",candidate.encode(),bytes.fromhex(salt),int(iterations)).hex();return hmac.compare_digest(actual,digest.casefold())
        except (TypeError,ValueError):return False
    stored=str(record.get("password") or "");return bool(stored) and hmac.compare_digest(candidate,stored)

def _temporary(config:Mapping[str,Any])->AccessIdentity:
    current=_identity()
    if current:return current
    users=_mapping(config.get("users"));remaining=max(0,int(float(st.session_state.get(_LOCK,0) or 0)-time.monotonic()))
    render_login_brand()
    if not users:st.error("El control de acceso está activo, pero no existen usuarios configurados.");st.stop()
    if remaining:st.warning(f"Acceso bloqueado temporalmente. Intenta nuevamente en {remaining} segundos.");st.stop()
    with st.form("henkia_access_form"):
        st.markdown('<div class="henkia-login-note">No ingreses claves API, datos personales sensibles ni información confidencial en las consultas.</div>',unsafe_allow_html=True)
        username=st.text_input("Usuario",autocomplete="username").strip().casefold()
        password=st.text_input("Contraseña",type="password",autocomplete="current-password")
        submitted=st.form_submit_button("Ingresar",type="primary",use_container_width=True)
    if not submitted:st.stop()
    record=_mapping(users.get(username));valid=_bool(record.get("enabled"),True) and _verify(password,record)
    if not valid:
        failures=int(st.session_state.get(_FAIL,0) or 0)+1
        if failures>=5:st.session_state[_FAIL]=0;st.session_state[_LOCK]=time.monotonic()+60;st.error("Demasiados intentos fallidos. Acceso bloqueado temporalmente.")
        else:st.session_state[_FAIL]=failures;st.error("Usuario o contraseña no válidos.")
        st.stop()
    result=AccessIdentity(username,str(record.get("display_name") or username),str(record.get("role") or "pilot_user"),"temporary_gate");_save(result);st.rerun();return result

def _oidc(config:Mapping[str,Any])->AccessIdentity:
    user=getattr(st,"user",None);logged=bool(getattr(user,"is_logged_in",False)) if user else False
    if not logged:
        render_login_brand();st.info("Acceso corporativo requerido.")
        if not hasattr(st,"login"):st.error("La versión instalada no admite OIDC.");st.stop()
        if st.button("Ingresar con identidad corporativa",type="primary"):st.login()
        st.stop()
    email=str(getattr(user,"email","") or "").strip().casefold();domain=email.rsplit("@",1)[-1] if "@" in email else ""
    emails={str(x).strip().casefold() for x in config.get("allowed_emails",[])};domains={str(x).strip().casefold() for x in config.get("allowed_domains",[])}
    if (emails or domains) and email not in emails and domain not in domains:st.error("Identidad autenticada, pero no autorizada.");st.stop()
    result=AccessIdentity(email or str(getattr(user,"sub","authenticated_user")),str(getattr(user,"name","") or email or "Usuario autorizado"),"pilot_user","oidc");_save(result);return result

def require_access()->AccessIdentity:
    config=_mapping(_secret("access",{}));mode=_mode(config.get("mode") or _secret("ACCESS_MODE","temporary_gate"))
    if mode=="disabled":return AccessIdentity("anonymous","Usuario","anonymous","disabled")
    if mode=="temporary_gate":return _temporary(config)
    if mode=="oidc":return _oidc(config)
    st.error("ACCESS_MODE no es válido. La aplicación permanece cerrada.");st.stop()

def render_access_sidebar(identity:AccessIdentity)->None:
    if identity.method=="disabled":return
    with st.sidebar:
        st.caption(f"Acceso: {identity.display_name}")
        if st.button("Cerrar sesión",key="henkia_logout",use_container_width=True):
            _clear()
            if identity.method=="oidc" and hasattr(st,"logout"):st.logout()
            st.rerun()
