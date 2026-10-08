# -*- coding: utf-8 -*-
# ==================== TEAM 84FF — FREEFIRE BR → LW MIX BOT ====================
# BR once → then Lone Wolf (max 2 parallel per account if possible)
# Cache + accounts.json + auto reconnect

import sys, os
os.environ['PYTHONUNBUFFERED'] = '1'
os.environ.setdefault('PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION', 'python')
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import asyncio, httpx, random, json, socket, struct, time, uuid, itertools
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from google_play_scraper import app as play_scraper
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from protobuf_decoder.protobuf_decoder import Parser
from message_ids import MESSAGE_ID_TO_NAME
import thunderFF_pb2

# ==================== CONFIG ====================
START_MATCH_INTERVAL = 1.5
MAX_MATCH_DURATION = 1500
MATCH_IDLE_TIMEOUT = 2
NON_MATCH_RECONNECT_DELAY = 0.5
NEW_MATCH_DELAY = 3.0
TOKEN_CACHE_TTL = 7200
ACCOUNTS_FILE = "accounts.json"
TOKEN_CACHE_FILE = "token_cache.json"
DEVICES_FILE = "devices.json"

# BR mode (Lone Wolf = mode 2)
BR_MODE_ID = 1
BR_MAP_ID = 1

# Lone Wolf mode
LW_MODE_ID = 1
LW_MAP_ID = 1

# Max concurrent Lone Wolf per account
LW_MAX_PARALLEL_PER_ACCOUNT = 1   # server allows only 1 LW per UID
LW_MAX_PARALLEL_TOTAL = 2          # total across all accounts

ACCOUNT_REGION = "IND"

xK, xV = b'Yg&tc%DEuh6%Zc^8', b'6oyZDr22E3ychjM%'
AES_KEY = xK
AES_IV  = xV

REGION_LANG = {
    "BD":"bn","IND":"hi","PK":"ur","SG":"en","ID":"id","ME":"ar",
    "VN":"vi","TW":"zh","CIS":"ru","TH":"th","EU":"en","US":"en",
    "SAC":"es","LK":"en","BR":"pt",
}
REGION_PREFIX = {
    "ME":"031900","IND":"031400","BD":"031400",
    "SG":"031500","TH":"031500","PH":"031500","VN":"031500",
    "MY":"031500","ID":"031500","HK":"031500","TW":"031500",
    "PK":"031500","CIS":"031500","BR":"031500","NA":"031500",
    "SAC":"031500","EUROPE":"031500",
}

CRC7_TABLE = bytes([
    0,9,18,27,36,45,54,63,72,65,90,83,108,101,126,119,
    25,16,11,2,61,52,47,38,81,88,67,74,117,124,103,110,
    50,59,32,41,22,31,4,13,122,115,104,97,94,87,76,69,
    43,34,57,48,15,6,29,20,99,106,113,120,71,78,85,92,
    100,109,118,127,64,73,82,91,44,37,62,55,8,1,26,19,
    125,116,111,102,89,80,75,66,53,60,39,46,17,24,3,10,
    86,95,68,77,114,123,96,105,30,23,12,5,58,51,40,33,
    79,70,93,84,107,98,121,112,7,14,21,28,35,42,49,56,
    65,72,83,90,101,108,119,126,9,0,27,18,45,36,63,54,
    88,81,74,67,124,117,110,103,16,25,2,11,52,61,38,47,
    115,122,97,104,87,94,69,76,59,50,41,32,31,22,13,4,
    106,99,120,113,78,71,92,85,34,43,48,57,6,15,20,29,
    37,44,55,62,1,8,19,26,109,100,127,118,73,64,91,82,
    60,53,46,39,24,17,10,3,116,125,102,111,80,89,66,75,
    23,30,5,12,51,58,33,40,95,86,77,68,123,114,105,96,
    14,7,28,21,42,35,56,49,70,79,84,93,98,107,112,121,
])

_DELTA = 0x9E3779B9
_ROUNDS = 16
_FIELD_SIZES = {0:1,1:2,2:2,3:1,4:2}
_FIELD_NAMES = {0:"sendOption",1:"cmd",2:"orderId",3:"flags",4:"length"}

CLOUDFLARE_PRIMARY_DNS = "1.1.1.1"
CLOUDFLARE_SECONDARY_DNS = "1.0.0.1"
_DNS_CACHE: Dict[str, Tuple[str,float]] = {}
_DNS_CACHE_TTL = 300.0

client = httpx.AsyncClient(verify=False, timeout=15.0,
    limits=httpx.Limits(max_connections=300, max_keepalive_connections=150))
_LOGIN_SEMAPHORE = asyncio.Semaphore(4)

headers = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Expect': '100-continue',
    'X-Unity-Version': '2018.4.12f1',
    'X-GA-SV': '1789535859',
    'X-GA': 'v1 1',
    'ReleaseVersion': 'OB55'
}


def log(m): print(m, flush=True)
def print_error(m): log(f"[-] {m}")
def print_success(m): log(f"[+] {m}")
def print_info(m): log(f"[i] {m}")
def print_warning(m): log(f"[!] {m}")


def get_proto_field(d, key, default=None):
    if not d or not isinstance(d, dict): return default
    if key in d:
        v=d[key].get('data'); return v if v is not None else default
    if str(key) in d:
        v=d[str(key)].get('data'); return v if v is not None else default
    return default


def _pb_varint(n):
    if n < 0: n = (1<<64)+n
    out=bytearray()
    while True:
        b=n&0x7F; n>>=7
        if n: b|=0x80
        out.append(b)
        if not n: break
    return bytes(out)

def _pb_tag(f,w): return _pb_varint((f<<3)|w)

def _pb_field(f,v):
    if isinstance(v,bool): v=int(v)
    if isinstance(v,int): return _pb_tag(f,0)+_pb_varint(v)
    if isinstance(v,str):
        d=v.encode('utf-8'); return _pb_tag(f,2)+_pb_varint(len(d))+d
    if isinstance(v,(bytes,bytearray)):
        d=bytes(v); return _pb_tag(f,2)+_pb_varint(len(d))+d
    return b""


def crc7(data):
    c=0
    for b in data: c=CRC7_TABLE[((2*(c&0xFF))^(b&0xFF))&0xFF]&0x7F
    return c&0x7F

def uleb_encode(n):
    out=bytearray()
    while True:
        b=n&0x7F; n>>=7
        if n: b|=0x80
        out.append(b)
        if not n: break
    return bytes(out)

def has_ssan_zig(n):
    z=(n<<1)&0xFFFFFFFFFFFFFFFF
    out=bytearray()
    while z>=0x80: out.append((z&0x7F)|0x80); z>>=7
    out.append(z); return bytes(out)


def _generate_new_device() -> dict:
    dl = [
        ("Samsung","SM-G998B","Adreno (TM) 660","Android OS 12 / API-31"),
        ("Xiaomi","2201122G","Adreno (TM) 730","Android OS 13 / API-33"),
        ("Realme","RMX3700","Mali-G710","Android OS 14 / API-34"),
        ("OnePlus","CPH2451","Adreno (TM) 740","Android OS 13 / API-33"),
        ("OPPO","CPH2611","Adreno (TM) 720","Android OS 14 / API-34"),
        ("Vivo","V2203","Mali-G710","Android OS 12 / API-31"),
        ("Poco","M2102J20SG","Adreno (TM) 660","Android OS 13 / API-33"),
    ]
    b,m,g,o=random.choice(dl)
    return {
        "unique_device_id": f"Google|{str(uuid.uuid4())}",
        "brand": b, "model": m, "gpu_renderer": g, "system_software": o,
        "screen_width": random.choice([1080,1440,720,1280]),
        "screen_height": random.choice([2400,3200,1600,2400]),
        "screen_dpi": str(random.randint(300,420)),
        "memory": random.randint(2800,6500),
        "processor_details": f"ARM64 FP ASIMD AES VMH | {random.randint(2200,3200)} | {random.randint(6,12)}",
        "client_ip": f"{random.randint(103,223)}.{random.randint(10,250)}.{random.randint(10,250)}.{random.randint(10,250)}"
    }


def get_device_for_account(aid: str) -> dict:
    devices={}
    if os.path.exists(DEVICES_FILE):
        try:
            with open(DEVICES_FILE,"r",encoding="utf-8") as f: devices=json.load(f)
        except Exception: pass
    k=str(aid)
    if k in devices: return devices[k]
    nd=_generate_new_device()
    devices[k]=nd
    try:
        with open(DEVICES_FILE,"w",encoding="utf-8") as f: json.dump(devices,f,indent=4)
    except Exception as e: print_error(f"device save: {e}")
    return nd


async def resolve_host_cloudflare(hostname: str) -> str:
    if not hostname: return hostname
    parts=hostname.split('.')
    if len(parts)==4 and all(p.isdigit() and 0<=int(p)<=255 for p in parts): return hostname
    now=time.time()
    if hostname in _DNS_CACHE:
        ip,exp=_DNS_CACHE[hostname]
        if now<exp: return ip

    def _q(server_ip):
        s=None
        try:
            tx_id=random.randint(1000,65535)
            h=struct.pack(">HHHHHH",tx_id,0x0100,1,0,0,0)
            qn=b"".join(bytes([len(p)])+p.encode('ascii') for p in hostname.split('.'))+b"\x00"
            pkt=h+qn+struct.pack(">HH",1,1)
            s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(1.2)
            s.sendto(pkt,(server_ip,53)); r,_=s.recvfrom(1024)
            if len(r)>=12:
                an=struct.unpack(">H",r[6:8])[0]
                if an>0:
                    o=12+len(qn)+4
                    for _ in range(an):
                        if o>=len(r): break
                        if (r[o]&0xC0)==0xC0: o+=2
                        else:
                            while o<len(r) and r[o]!=0: o+=1+r[o]
                            o+=1
                        if o+10>len(r): break
                        rt,rc,tt,rl=struct.unpack(">HHIH",r[o:o+10]); o+=10
                        if rt==1 and rl==4 and o+4<=len(r):
                            return socket.inet_ntoa(r[o:o+4])
                        o+=rl
        except Exception: pass
        finally:
            if s:
                try: s.close()
                except Exception: pass
        return None

    loop=asyncio.get_running_loop()
    ip=await loop.run_in_executor(None,_q,CLOUDFLARE_PRIMARY_DNS)
    if not ip: ip=await loop.run_in_executor(None,_q,CLOUDFLARE_SECONDARY_DNS)
    if not ip:
        try:
            ii=await loop.getaddrinfo(hostname,None,family=socket.AF_INET)
            if ii: ip=ii[0][4][0]
        except Exception: ip=hostname
    if ip: _DNS_CACHE[hostname]=(ip,now+_DNS_CACHE_TTL)
    return ip or hostname


def optimize_tcp_socket(sock):
    try:
        sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_KEEPALIVE,1)
        if hasattr(socket,"SIO_KEEPALIVE_VALS") and os.name=='nt':
            try: sock.ioctl(socket.SIO_KEEPALIVE_VALS,(1,10000,2000))
            except Exception: pass
        elif hasattr(socket,"TCP_KEEPIDLE"):
            try:
                sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_KEEPIDLE,10)
                if hasattr(socket,"TCP_KEEPINTVL"):
                    sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_KEEPINTVL,2)
                if hasattr(socket,"TCP_KEEPCNT"):
                    sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_KEEPCNT,5)
            except Exception: pass
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,131072)
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,131072)
    except Exception: pass

def optimize_udp_socket(sock):
    try:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,131072)
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,131072)
        if hasattr(socket,'SIO_UDP_CONNRESET') and os.name=='nt':
            try: sock.ioctl(socket.SIO_UDP_CONNRESET,False)
            except Exception: pass
    except Exception: pass

async def safe_close_writer(w):
    if not w: return
    try:
        if not w.is_closing(): w.close()
        await asyncio.wait_for(w.wait_closed(),timeout=1.5)
    except Exception: pass


async def aes_encrypt(payload,key,iv):
    return AES.new(key,AES.MODE_CBC,iv).encrypt(pad(payload,AES.block_size))

async def get_playstore_version():
    loop=asyncio.get_event_loop()
    try:
        r=await loop.run_in_executor(None,lambda: play_scraper('com.dts.freefireth',lang='hi',country='id'))
        return r.get("version")
    except Exception:
        return "1.132.8"

async def version_config():
    av=await get_playstore_version()
    lang=REGION_LANG.get(ACCOUNT_REGION,"en")
    api=("https://version.ggwhitehawk.com/live/ver.php"
         f"?version={av}&lang={lang}&device=android&channel=android"
         f"&appstore=googleplay&region={ACCOUNT_REGION}"
         "&whitelist_version=1.3.0&whitelist_sp_version=1.0.0")
    try:
        r=await client.get(api); r.raise_for_status(); d=r.json()
        su,rv,lv=d.get("server_url"),d.get("remote_version"),d.get("latest_release_version")
        if not su or not rv or not lv: return None
        return lv,rv,su
    except Exception:
        return None


async def get_access_token(uid,password):
    url="https://100067.connect.garena.com/oauth/guest/token/grant"
    hdrs={
        "Host":"100067.connect.garena.com",
        "User-Agent":"Dalvik/2.1.0 (Linux; U; Android 12; SM-G998B Build/SP1A.210812.016)",
        "Content-Type":"application/x-www-form-urlencoded",
        "Accept-Encoding":"gzip, deflate, br",
        "Connection":"close"
    }
    data={
        "uid":str(uid),"password":str(password),
        "response_type":"token","client_type":"2",
        "client_secret":"2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id":"100067"
    }
    for _ in range(5):
        try:
            r=await client.post(url,headers=hdrs,data=data)
            if r.status_code==200:
                rd=r.json()
                oid,at,pl=rd.get("open_id"),rd.get("access_token"),rd.get("platform",4)
                if oid and at: return str(oid),str(at),str(pl)
            if r.status_code==429:
                await asyncio.sleep(1.0); continue
        except Exception: pass
        await asyncio.sleep(0.5)
    return None


# ==================== TOKEN CACHE ====================
_cache_memo: Dict[str,Any]={}; _cache_memo_t=0.0; _CACHE_TTL=5.0

def _ser(o):
    if isinstance(o,(bytes,bytearray)): return {"__bytes_hex__":bytes(o).hex()}
    raise TypeError

def _des(o):
    if isinstance(o,dict):
        if "__bytes_hex__" in o and len(o)==1:
            try: return bytes.fromhex(o["__bytes_hex__"])
            except Exception: return b""
        return {k:_des(v) for k,v in o.items()}
    if isinstance(o,list): return [_des(x) for x in o]
    return o

def _load_cache():
    global _cache_memo,_cache_memo_t
    now=time.time()
    if _cache_memo and (now-_cache_memo_t)<_CACHE_TTL: return _cache_memo
    if not os.path.exists(TOKEN_CACHE_FILE): return {}
    try:
        with open(TOKEN_CACHE_FILE,"r",encoding="utf-8") as f: c=f.read().strip()
        if not c: return {}
        d=json.loads(c)
        if not isinstance(d,dict): raise ValueError
        p=_des(d); _cache_memo=p; _cache_memo_t=now; return p
    except Exception as e:
        print_error(f"cache corrupt: {e}")
        try: os.remove(TOKEN_CACHE_FILE)
        except Exception: pass
        return {}

def _save_cache(c):
    global _cache_memo,_cache_memo_t
    try:
        tmp=TOKEN_CACHE_FILE+".tmp"
        with open(tmp,"w",encoding="utf-8") as f: json.dump(c,f,indent=2,default=_ser)
        os.replace(tmp,TOKEN_CACHE_FILE)
        _cache_memo=c; _cache_memo_t=time.time()
    except Exception as e: print_error(f"cache save: {e}")

def cache_get(uid):
    c=_load_cache(); e=c.get(str(uid))
    if not e: return None
    if time.time()-e.get("cached_at",0)>TOKEN_CACHE_TTL:
        cache_invalidate(uid); return None
    if str(e.get("account_id","")).isdigit(): e["account_id"]=int(e["account_id"])
    if not isinstance(e.get("login_payload_data"),(bytes,bytearray)):
        cache_invalidate(uid); return None
    return e

def cache_set(uid,d):
    c=_load_cache(); e=dict(d); e["cached_at"]=time.time(); c[str(uid)]=e; _save_cache(c)
    print_success(f"[CACHE] Saved for {uid}")

def cache_invalidate(uid):
    c=_load_cache()
    if str(uid) in c: del c[str(uid)]; _save_cache(c)


# ==================== PARSE ====================
async def parse_results(pr):
    rd={}
    for r in pr:
        fd={"wire_type":r.wire_type}
        if r.wire_type in ("varint","string","bytes"): fd["data"]=r.data
        elif r.wire_type=="length_delimited":
            if hasattr(r.data,"results"): fd["data"]=await parse_results(r.data.results)
            elif isinstance(r.data,list): fd["data"]=await parse_results(r.data)
            else: fd["data"]=str(r.data)
        rd[str(r.field)]=fd
    return rd

async def decode_protobuf(data):
    p=Parser().parse(data)
    return json.dumps(await parse_results(p))


# ==================== MAJORLOGIN ====================
async def build_majorlogin_payload(open_id,access_token,platform,client_version,device_info,verr=None):
    try:
        if verr is None: verr=client_version
        proto=thunderFF_pb2.MajorLoginReq()
        proto.event_time=str(datetime.now())[:-7]
        proto.game_name="free fire"
        proto.platform_id=1
        proto.client_version=str(verr)
        proto.client_version_code="2019121229"
        proto.system_software="Android OS 15 / API-35 (AP3A.240905.015.A2/185014)"
        proto.system_hardware="Handheld"
        proto.device_type="Handheld"
        proto.screen_width=1600
        proto.screen_height=719
        proto.screen_dpi="234"
        proto.processor_details="ARM64 FP ASIMD AES | 1820 | 8"
        proto.memory=2798
        proto.gpu_renderer="Mali-G57"
        proto.gpu_version="OpenGL ES 3.2 v1.r49p1-04eac0.2848c17a2fd4e9340e06555168eaa3c9"
        proto.unique_device_id="Google|f744e396-5694-4e65-995d-97a958f2bd1f"
        proto.client_ip="197.0.137.129"
        proto.language="pt-br"
        proto.open_id=str(open_id)
        proto.open_id_type="4"
        proto.login_open_id_type=4
        proto.access_token=str(access_token)
        proto.login_by=2
        proto.platform_sdk_id=1
        proto.origin_platform_type="4"
        proto.primary_platform_type="4"
        proto.reg_avatar=1
        proto.channel_type=3
        proto.telecom_operator="TUNTEL"
        proto.network_operator_a="TUNTEL"
        proto.network_type="WIFI"
        proto.network_type_a="WIFI"
        proto.cpu_type=2
        proto.cpu_architecture="64"
        proto.graphics_api="OpenGLES2"
        proto.supported_astc_bitset=8191
        proto.client_using_version="7428b253defc164018c604a1ebbfebdf"
        proto.loading_time=15078
        proto.release_channel="android"
        proto.extra_info="KqsHTx3+QOmBRR1WKvaWewlcpqJBfjki+PPHQoQG8+0yV+Uos7gUFFjHMQ/e7u6han6Fl77r7c3vMN3p8UbKgN+nfycQCgwBmWgBzomx2gj84c+p"
        proto.android_engine_init_flag=111207
        proto.if_push=1
        proto.is_vpn=0
        ma=proto.memory_available; ma.version=55; ma.hidden_value=81
        proto.external_storage_total=49973
        proto.external_storage_available=11338
        proto.internal_storage_total=854
        proto.internal_storage_available=11466
        proto.game_disk_storage_total=49973
        proto.game_disk_storage_available=11466
        proto.external_sdcard_total_storage=49973
        proto.external_sdcard_avail_storage=11466
        proto.library_path="/data/app/~~lHFxTCCbupG2QVJmsURtZw==/com.dts.freefireth-N3aCHpHNXpdxjD80uIIbww==/lib/arm64"
        proto.library_token="b8e0cd5e295eee42f5860d3c86e483dd|/data/app/~~lHFxTCCbupG2QVJmsURtZw==/com.dts.freefireth-N3aCHpHNXpdxjD80uIIbww==/base.apk"
        base=proto.SerializeToString()
        extra=b""
        extra+=_pb_field(96,'{"cur_rate":[90,60,120],"support_etc2":false}')
        extra+=_pb_field(97,1)
        extra+=_pb_field(99,"4")
        extra+=_pb_field(100,"4")
        extra+=_pb_field(102,b"\x17]ENWU\x0eR5")
        extra+=_pb_field(104,52882)
        extra+=_pb_field(105,1)
        extra+=_pb_field(106,"https://dl.ak.freefiremobile.com/live/ABHotUpdates/|https://core-ak.freefiremobile.com/live/ABHotUpdates/|6b2078db9d22dd98f8e9386a39af8462")
        extra+=_pb_field(107,"c8e41b7a93f02d56e1a94c7b8203f5d1")
        return await aes_encrypt(base+extra,AES_KEY,AES_IV)
    except Exception as e:
        print_error(f"payload: {e}"); return None


async def send_majorlogin(data,release_version,server_url):
    try:
        url=f"{server_url}MajorLogin" if server_url.endswith('/') else f"{server_url}/MajorLogin"
        hd=headers.copy(); hd["ReleaseVersion"]=str(release_version)
        r=await client.post(url,headers=hd,data=data)
        if r.status_code!=200: return None
        rc=r.content
        if len(rc)<40: return None
        res_proto=thunderFF_pb2.MajorLoginRes()
        try: res_proto.ParseFromString(rc)
        except Exception: pass
        dict_res={}
        try:
            parsed=Parser().parse(rc.hex()); dict_res=await parse_results(parsed)
        except Exception: pass
        kv=get_proto_field(dict_res,22) or res_proto.aes_ak
        ivv=get_proto_field(dict_res,23) or res_proto.iv_i
        if isinstance(kv,str):
            try: kv=bytes.fromhex(kv)
            except Exception: pass
        if isinstance(ivv,str):
            try: ivv=bytes.fromhex(ivv)
            except Exception: pass
        if not kv or not ivv:
            for off in range(min(128,len(rc))):
                try:
                    c=thunderFF_pb2.MajorLoginRes(); c.ParseFromString(rc[off:])
                    if c.region and c.token: res_proto=c; break
                except Exception: pass
            try:
                parsed=Parser().parse(rc.hex()); dict_res=await parse_results(parsed)
                k2=get_proto_field(dict_res,22); i2=get_proto_field(dict_res,23)
                if isinstance(k2,str):
                    try: k2=bytes.fromhex(k2)
                    except Exception: pass
                if isinstance(i2,str):
                    try: i2=bytes.fromhex(i2)
                    except Exception: pass
                if k2: kv=k2
                if i2: ivv=i2
            except Exception: pass
        if kv:
            try: res_proto.aes_ak=kv
            except Exception: pass
        if ivv:
            try: res_proto.iv_i=ivv
            except Exception: pass
        return res_proto
    except Exception as e:
        log(f"[-] majorlogin: {e}"); return None


async def send_getlogin(data,base_url,token,release_version):
    try:
        url=f"{base_url.rstrip('/')}/GetLoginData"
        hd=headers.copy()
        hd["ReleaseVersion"]=release_version
        hd['Authorization']=f"Bearer {token}"
        hd['Host']="clientbp.ppmainecoonghj.com"
        r=await client.post(url,headers=hd,data=data)
        if r.status_code!=200: return None
        rc=r.content
        res_proto=thunderFF_pb2.GetLoginDataRes()
        try: res_proto.ParseFromString(rc)
        except Exception: pass

        def _ext(raw,fn_target):
            try:
                pos=0; n=len(raw)
                def rv(buf,p):
                    res=0; sh=0
                    while p<len(buf):
                        b=buf[p]; p+=1; res|=(b&0x7F)<<sh
                        if not (b&0x80): break
                        sh+=7
                    return res,p
                fields={}
                while pos<n:
                    try: key,pos=rv(raw,pos)
                    except Exception: break
                    fn=key>>3; wt=key&0x07
                    try:
                        if wt==0: val,pos=rv(raw,pos)
                        elif wt==2:
                            ln,pos=rv(raw,pos); val=raw[pos:pos+ln]; pos+=ln
                        elif wt==5: val=raw[pos:pos+4]; pos+=4
                        elif wt==1: val=raw[pos:pos+8]; pos+=8
                        else: break
                    except Exception: break
                    fields.setdefault(fn,[]).append(val)
                if fn_target in fields:
                    v=fields[fn_target][0]
                    if isinstance(v,bytes):
                        try: return v.decode('utf-8','ignore')
                        except Exception: return None
                    return str(v)
            except Exception: return None

        try:
            for off in range(0,min(80,len(rc))):
                fa=_ext(rc[off:],14); ia=_ext(rc[off:],32)
                if fa and ":" in fa and ia and ":" in ia:
                    res_proto.functional_addrs=fa
                    res_proto.informational_addrs=ia
                    break
        except Exception: pass

        dict_res={}
        try:
            parsed=Parser().parse(rc.hex()); dict_res=await parse_results(parsed)
        except Exception: pass
        return res_proto,dict_res
    except Exception as e:
        log(f"[-] getlogin: {e}"); return None


# ==================== TCP STARTUP ====================
async def build_tcp_startup_packet(account_id,token,server_time,key,iv,region=None,typ='OnLine'):
    if region is None: region=ACCOUNT_REGION
    uid_hex=f"{int(account_id):016x}"
    ts=f"{int(server_time):08x}"
    enc=AES.new(key,AES.MODE_CBC,iv).encrypt(pad(token.encode(),16)).hex()
    ecl=f"{len(enc)//2:08x}"
    if typ=='OnLine':
        return f"9015{uid_hex}{ts}00000000{ecl}{enc}"
    return f"9015{uid_hex}{ts}{ecl}{enc}"

async def send_keep_alive(region=None):
    if region is None: region=ACCOUNT_REGION
    reg=str(region).upper()
    if reg=="ME": ka="0219"
    elif reg=="IND": ka="0214"
    else: ka="0215"
    return bytes.fromhex(ka)


# ==================== START MATCH (BR & LW) ====================
async def start_game_battle_royale(region, client_version, writer, key, iv):
    """BR match packet (mode=BR)"""
    packet = bytes.fromhex("080112800a0a010110013a110a044944433110aa011a064555524f50453a100a044944433210311a064555524f504540014a0801090a0b1219202758016291090a8001303838463832424630324139363736373032303130313030303030303030303030303136303030313030313530303032323246393745454530463030303030303436373632353134303030303030303030303030303030303030303030303030303030303030303030303030303066663030303030303030636163666131366410241afb02735d5e571400024a775d45414d1a041b1c001f11010449715f4243481a001e1d071c1703004b1a4066785c524570735c51486775421b5c5a4c07504042685a63610816054e19025e75196001477c015165406370195f5547404e4550640103020f1304064863754268676c755f65576e40467e5f0a417a4701026d675d6e73670b1108495a4c6a0b78470b740065645e525a057258425f584a447d4e6759440c11044e7c596d7f4b625f7d04055a47505c4e1d6b5b4107447d7201057d7f0f14084e430457674f7e517d72015172415d027473577c4d615f79535256780911030f4d5e027a797f614165067806505d53777750475e75064257076500460817014e741e7e5078487e7a7c465e7669767153497064605a7376677773550d160148037e18675966787f4c42607a645f577e7b441b460776026b18685d0b110205490060020f70676175654674706671797f41067346677c4e06585e780f15074c57047b40517075415f6364027259674b5b0166407f7340600407770a22047a5d5c52300b3a0a167305067162727516134208312e3133302e3232480350015ae90403626253513635686e556f4e36416456324b796f566c636f477776484f624e56526c4d727073504b4f43654177616848494176795556497273743752737149734a7a786b3247525268377a2f637664626d504f6a73552f79626d38547a4c69586d2f474351696d494b53486833447955726f39515152756c34545350626d6d624b7949565937545671577059455372323646572f59624578507338514f706d317372785455736c30796a434144444d4f34616a654b615753366361496c554b4963797a494e396d52516f715277687939797257476d337a644345337a6a61436f492f5a585233656f65365a42647a64677654636b6b665733356e4d4c6a6a565072564b6433523172756174394e50514150724a5546627859696c4c5a3859707336654d5447666b6649793574666a526c314d4648706b51774c6373374439656378566c41636f374e664f6d2b30654756466c4434744478706771385533595973587645384842502f70666c767a737138316a32524f4d7857437556445442492f684735625462773166456e4249725162762b636144775147696f74554e316d4c4b77734379456f4766706746614251457645672b736a764c4c78704743334c304a5344532f74526169504354553344374e6249306547516651622f5a466f4c36455630775a324d6f583932414c572f5049752f56634663584e70596b356f7966326151416a536971486a2f363276354843644f525551303578754e6171795251625653704654303137655237675255636b4966366c6f447476342b514e4a4670766d74757077707774396a5a5974437a4b56743657726d6e36785837706658456251555434684f3758a201050803108703a201050804108103a20105080510c001a20105081d10cc01a2010408161078a20105080e10af01a201020815")
    proto = thunderFF_pb2.StartMatch()
    proto.ParseFromString(packet)
    if hasattr(proto.main, 'region_list') and len(proto.main.region_list) > 0:
        proto.main.region_list[0].region = region
        if len(proto.main.region_list) > 1:
            proto.main.region_list[1].region = region
    if hasattr(proto.main, 'client_version'):
        proto.main.client_version.remote_version = client_version
    pkt = proto.SerializeToString()
    enc = (await aes_encrypt(pkt, key, iv)).hex()
    pl = len(enc) // 2
    hl = hex(pl)[2:]
    hl = hl if len(hl) > 1 else "0" + hl
    reg = str(region).upper() if region else ACCOUNT_REGION
    pfx = REGION_PREFIX.get(reg, "031500")
    final = pfx + "0" * (6 - len(hl)) + hl + enc
    writer.write(bytes.fromhex(final))
    await writer.drain()
    log(f"[BR] search sent ({pl}B) region={reg}")


async def start_game_lone_wolf(region, client_version, writer, key, iv):
    """Lone Wolf match packet — mode_id/map_id changed (LW variant)"""
    packet = bytes.fromhex("080112800a0a010b102b3a110a044944433110aa011a064555524f50453a100a044944433210311a064555524f504540014a0801090a0b1219202758016291090a8001303838463832424630324139363736373032303130313030303030303030303030303136303030313030313530303032323246393745454530463030303030303436373632353134303030303030303030303030303030303030303030303030303030303030303030303030303066663030303030303030636163666131366410241afb02735d5e571400024a775d45414d1a041b1c001f11010449715f4243481a001e1d071c1703004b1a4066785c524570735c51486775421b5c5a4c07504042685a63610816054e19025e75196001477c015165406370195f5547404e4550640103020f1304064863754268676c755f65576e40467e5f0a417a4701026d675d6e73670b1108495a4c6a0b78470b740065645e525a057258425f584a447d4e6759440c11044e7c596d7f4b625f7d04055a47505c4e1d6b5b4107447d7201057d7f0f14084e430457674f7e517d72015172415d027473577c4d615f79535256780911030f4d5e027a797f614165067806505d53777750475e75064257076500460817014e741e7e5078487e7a7c465e7669767153497064605a7376677773550d160148037e18675966787f4c42607a645f577e7b441b460776026b18685d0b110205490060020f70676175654674706671797f41067346677c4e06585e780f15074c57047b40517075415f6364027259674b5b0166407f7340600407770a22047a5d5c52300b3a0a167305067162727516134208312e3133302e3232480350015ae90403626253513635686e556f4e36416456324b796f566c636f477776484f624e56526c4d727073504b4f43654177616848494176795556497273743752737149734a7a786b3247525268377a2f637664626d504f6a73552f79626d38547a4c69586d2f474351696d494b53486833447955726f39515152756c34545350626d6d624b7949565937545671577059455372323646572f59624578507338514f706d317372785455736c30796a434144444d4f34616a654b615753366361496c554b4963797a494e396d52516f715277687939797257476d337a644345337a6a61436f492f5a585233656f65365a42647a64677654636b6b665733356e4d4c6a6a565072564b6433523172756174394e50514150724a5546627859696c4c5a3859707336654d5447666b6649793574666a526c314d4648706b51774c6373374439656378566c41636f374e664f6d2b30654756466c4434744478706771385533595973587645384842502f70666c767a737138316a32524f4d7857437556445442492f684735625462773166456e4249725162762b636144775147696f74554e316d4c4b77734379456f4766706746614251457645672b736a764c4c78704743334c304a5344532f74526169504354553344374e6249306547516651622f5a466f4c36455630775a324d6f583932414c572f5049752f56634663584e70596b356f7966326151416a536971486a2f363276354843644f525551303578754e6171795251625653704654303137655237675255636b4966366c6f447476342b514e4a4670766d74757077707774396a5a5974437a4b56743657726d6e36785837706658456251555434684f3758a201050803108703a201050804108103a20105080510c001a20105081d10cc01a2010408161078a20105080e10af01a201020815")
    proto = thunderFF_pb2.StartMatch()
    proto.ParseFromString(packet)
    if hasattr(proto.main, 'region_list') and len(proto.main.region_list) > 0:
        proto.main.region_list[0].region = region
        if len(proto.main.region_list) > 1:
            proto.main.region_list[1].region = region
    if hasattr(proto.main, 'client_version'):
        proto.main.client_version.remote_version = client_version
    pkt = proto.SerializeToString()
    enc = (await aes_encrypt(pkt, key, iv)).hex()
    pl = len(enc) // 2
    hl = hex(pl)[2:]
    hl = hl if len(hl) > 1 else "0" + hl
    reg = str(region).upper() if region else ACCOUNT_REGION
    pfx = REGION_PREFIX.get(reg, "031500")
    final = pfx + "0" * (6 - len(hl)) + hl + enc
    writer.write(bytes.fromhex(final))
    await writer.drain()
    log(f"[LW] search sent ({pl}B) region={reg}")


# ==================== TEA / PACKET ====================
async def tea_enc(v0,v1,k0,k1,k2,k3):
    s=0
    for _ in range(_ROUNDS):
        s=(s+_DELTA)&0xFFFFFFFF
        v0=(v0+((((v1<<4)&0xFFFFFFFF)+k0)&0xFFFFFFFF ^ ((v1+s)&0xFFFFFFFF) ^ (((v1>>5)+k1)&0xFFFFFFFF)))&0xFFFFFFFF
        v1=(v1+((((v0<<4)&0xFFFFFFFF)+k2)&0xFFFFFFFF ^ ((v0+s)&0xFFFFFFFF) ^ (((v0>>5)+k3)&0xFFFFFFFF)))&0xFFFFFFFF
    return v0,v1

async def tea_dec(v0,v1,k0,k1,k2,k3):
    s=(_DELTA*_ROUNDS)&0xFFFFFFFF
    for _ in range(_ROUNDS):
        v1=(v1-((((v0<<4)&0xFFFFFFFF)+k2)&0xFFFFFFFF ^ ((v0+s)&0xFFFFFFFF) ^ (((v0>>5)+k3)&0xFFFFFFFF)))&0xFFFFFFFF
        v0=(v0-((((v1<<4)&0xFFFFFFFF)+k0)&0xFFFFFFFF ^ ((v1+s)&0xFFFFFFFF) ^ (((v1>>5)+k1)&0xFFFFFFFF)))&0xFFFFFFFF
        s=(s-_DELTA)&0xFFFFFFFF
    return v0,v1

async def tea_cbc_encrypt(padded,kb):
    k0,k1,k2,k3=(struct.unpack_from("<I",kb,o)[0] for o in (0,4,8,12))
    out=bytearray(len(padded)); pc=bytearray(8); pi=bytearray(8)
    for i in range(0,len(padded),8):
        x=bytearray(8)
        for j in range(8): x[j]=padded[i+j]^pc[j]
        e0,e1=await tea_enc(struct.unpack_from("<I",x,0)[0],struct.unpack_from("<I",x,4)[0],k0,k1,k2,k3)
        en=bytearray(8); struct.pack_into("<I",en,0,e0); struct.pack_into("<I",en,4,e1)
        for j in range(8): out[i+j]=en[j]^pi[j]
        pc[:]=out[i:i+8]; pi[:]=x
    return bytes(out)

async def tea_cbc_decrypt(body,kb):
    k0,k1,k2,k3=(struct.unpack_from("<I",kb,o)[0] for o in (0,4,8,12))
    out=bytearray(len(body)); pi=bytearray(8); pc=bytearray(8)
    x=bytearray(8); d=bytearray(8)
    for i in range(0,len(body),8):
        for j in range(8): x[j]=body[i+j]^pi[j]
        d0,d1=await tea_dec(struct.unpack_from("<I",x,0)[0],struct.unpack_from("<I",x,4)[0],k0,k1,k2,k3)
        struct.pack_into("<I",d,0,d0); struct.pack_into("<I",d,4,d1)
        for j in range(8): out[i+j]=d[j]^pc[j]
        pc[:]=body[i:i+8]; pi[:]=d
    return bytes(out)

async def build_padded(content):
    pl=(8-(len(content)+10)%8)%8
    return bytes([pl,0,0])+b"\x00"*pl+content+b"\x00"*7

async def encode_header(layout,so,cmd,oid,fl,ln,k,v80):
    out=bytearray()
    for code in layout:
        val={0:so,1:cmd,2:oid,3:fl,4:ln}[code]
        if _FIELD_SIZES[code]==1: out.append((val&0xFF)^k)
        else:
            v=((val&0xFFFF)^v80)&0xFFFF
            out.append(v&0xFF); out.append((v>>8)&0xFF)
    return bytes(out)

async def crc7_buff(crc,buf):
    c=crc&0x7F
    for b in buf: c=CRC7_TABLE[((2*(c&0xFF))^(b&0xFF))&0xFF]&0x7F
    return c&0x7F

async def sv_frame(mk,layout,so,cmd,oid,fl,content,key,enc=True):
    k=key[0]; v80=((k<<8)|k)&0xFFFF
    body=await tea_cbc_encrypt(await build_padded(content),key) if enc else content
    hdr=bytearray([mk,0])+await encode_header(layout,so,cmd,oid,fl,len(body),k,v80)
    pkt=bytearray(hdr+body); pkt[1]=await crc7_buff(0,bytes(pkt[2:]))&0x7F
    return bytes(pkt)


async def build_match_startup_packets(token,udp_key,match_code,account_id,block_val,
                                      server_ip="",region=None,client_version="1.132.8",
                                      client_version_code="2019121229",access_token="",
                                      mode_id=1, map_id=1):
    if region is None: region=ACCOUNT_REGION
    token=token.strip(); udp_key=bytes.fromhex(udp_key)
    match_code=[int(c) for c in str(match_code).strip()]
    tj=token[:660] if len(token)>660 else token
    sj=token[660:] if len(token)>660 else ""
    et=tj.encode() if isinstance(tj,str) else tj
    es=sj.encode() if isinstance(sj,str) else sj
    g420=has_ssan_zig(len(et))+et
    reg=str(region).upper() if region else ACCOUNT_REGION
    cso=bytes.fromhex("ca0163736f7665727365612e7374726f6e67686f6c642e66726565666972656d6f62696c652e636f6d3b302e302e302e303b33342e3132362e37362e34353b33342e38372e3137372e31343b33342e38372e3137302e3233303b33352e3138352e3138332e3537000000000000010000000000000000000000000100000800000100000000000100a8a2d7bebd8d8bdf110200")
    mid=bytes.fromhex('0000000001000102030101')+has_ssan_zig(len(reg))+reg.encode()
    mid+=bytes.fromhex('0001030003000004')
    mid+=has_ssan_zig(len(client_version))+client_version.encode()
    mid+=has_ssan_zig(len(client_version_code))+client_version_code.encode()
    mid+=cso
    cip=server_ip.split(':')[0] if server_ip else "0.0.0.0"
    mid+=has_ssan_zig(len(cip))+cip.encode()
    cat=access_token.strip() if access_token else ""
    if cat: mid+=has_ssan_zig(len(cat))+cat.encode()
    mid+=has_ssan_zig(len(es))+es
    tg=(uleb_encode(int(account_id))+uleb_encode(int(block_val))+uleb_encode(1)+
        uleb_encode(int(mode_id))+uleb_encode(int(block_val))+uleb_encode(int(map_id))+mid)
    process=await sv_frame(0x5E,match_code,2,447,0,1,g420,udp_key)
    loading=await sv_frame(0x5A,match_code,2,448,1,1,tg,udp_key)
    return process.hex(),loading.hex()


async def produce_xor_key(sk):
    k=sk[0] if sk and len(sk)>0 else 10
    return k,((k<<8)|k)&0xFFFF

async def parse_layout(l):
    if isinstance(l,str): return [int(c) for c in l.strip()]
    return list(l)

async def build_hello_packet(text,key,layout):
    d=text.encode("utf-8")
    if len(d)>25: raise ValueError("too long")
    content=b"\x10\x00\x00\x00"+d+b"\x00"*(29-4-len(d))
    k,v80=await produce_xor_key(key); layout=await parse_layout(layout)
    padded=await build_padded(content); enc=await tea_cbc_encrypt(padded,key)
    hdr=await encode_header(layout,1,1,0,1,len(enc),k,v80)
    pkt=bytearray([0x63,0x00])+hdr+enc
    pkt[1]=await crc7_buff(0,pkt[2:])&0x7F
    return bytes(pkt).hex()

async def classify(frame):
    cmd=frame["cmd"]; mn=MESSAGE_ID_TO_NAME.get(cmd,f"UNK_{cmd}")
    if mn=="UDP_HELLO": return "HELLO"
    if mn=="UDP_ACK": return "ACK"
    if mn=="UDP_PING": return "PING"
    if mn=="RUDP_JOIN_MATCH": return "JOIN_MATCH"
    if mn.startswith("RUDP_"): return mn
    if mn.startswith("UDP_"): return mn
    return "DATA"

async def build_packet(mk,layout,so,cmd,oid,fl,content,key,enc=True):
    k=key[0]; v80=((k<<8)|k)&0xFFFF
    body=await tea_cbc_encrypt(await build_padded(content),key) if enc else content
    hdr=bytearray([mk,0])
    for code in layout:
        val={0:so,1:cmd,2:oid,3:fl,4:len(body)}[code]
        if _FIELD_SIZES[code]==1: hdr.append((val&0xFF)^k)
        else:
            v=((val&0xFFFF)^v80)&0xFFFF
            hdr.append(v&0xFF); hdr.append((v>>8)&0xFF)
    pkt=bytearray(hdr+body); pkt[1]=await crc7_buff(0,bytes(pkt[2:]))&0x7F
    return bytes(pkt)

async def layouts_from_mask(m):
    ru=[int(c) for c in str(m).strip()]; nr=[c for c in ru if c!=2]
    return ru,nr

async def reply_for(frame,key,mask,ack_key=0x68,ping_key=0x6D,hello_key=0x5B,ack_style="short"):
    ru,nr=await layouts_from_mask(mask); typ=await classify(frame)
    if typ=="HELLO":
        if ack_style=="echo":
            c=frame["content"] if frame["content"] else b"\x10\x00\x00\x00"
            return typ, await build_packet(hello_key,nr,1,1,None,1,c,key)
        return typ, await build_packet(ack_key,nr,0,2,None,1,b"\x01\x00",key)
    if typ=="ACK":
        c=frame["content"] if frame["content"] else b"\x01\x00"
        return typ, await build_packet(ack_key,nr,0,2,None,1,c,key)
    if typ=="PING":
        c=frame["content"]; ctr=c[:4] if len(c)>=4 else c
        return typ, await build_packet(ping_key,nr,0,3,None,0,ctr+b"\x00\x00\x00",key,enc=False)
    if typ=="JOIN_MATCH":
        return typ, await build_packet(ack_key,nr,0,2,None,1,b"\x02\x00",key)
    return typ, None

async def keepalive_ping(sock,ip,port,kb,mask,stop):
    nr=(await layouts_from_mask(mask))[1]
    pks=[0x66,0x6D,0x69,0x6C,0x6B,0x6E,0x6F,0x70]
    loop=asyncio.get_event_loop(); i=0
    while not stop.is_set():
        pk=pks[i%len(pks)]; ctr=int(time.time()*1000)&0xFFFFFFFF
        pkt=await build_packet(pk,nr,0,3,None,0,struct.pack("<I",ctr)+b"\x00\x00\x00",kb,enc=False)
        try: await loop.sock_sendto(sock,pkt,(ip,port))
        except Exception: pass
        i+=1
        try: await asyncio.wait_for(stop.wait(),timeout=3.0)
        except asyncio.TimeoutError: pass

async def try_header(buf,layout,k,v80):
    off=2; out={}
    for code in layout:
        s=_FIELD_SIZES[code]
        if off+s>len(buf): return None
        out[_FIELD_NAMES[code]]=(buf[off]^k) if s==1 else ((buf[off]|(buf[off+1]<<8))^v80)&0xFFFF
        off+=s
    out["headerLen"]=off; return out

async def oicq_unpad(p):
    if not p or len(p)<8: return None
    if not all(p[-1-i]==0 for i in range(7)): return None
    pl=p[0]&0x07; s=3+pl; e=len(p)-7
    return p[s:e] if s<e else b""

async def decode_packet(packet,key,mask=None):
    d=bytes(packet) if isinstance(packet,bytes) else bytes.fromhex(packet)
    if len(d)<8: return None
    k=key[0]; v80=((k<<8)|k)&0xFFFF
    crc_ok=(d[1]&0x7F)==await crc7_buff(0,d[2:])
    cands=[]
    if mask:
        ru,nr=await layouts_from_mask(mask)
        layouts=[("RUDP",ru),("nonRUDP",nr)]
    else:
        layouts=[("RUDP",list(p)) for p in itertools.permutations([0,1,2,3,4])]
        layouts+=[("nonRUDP",list(p)) for p in itertools.permutations([0,1,3,4])]
    for kind,layout in layouts:
        f=await try_header(d,layout,k,v80)
        if not f: continue
        if f["flags"]>7 or f["sendOption"]>7: continue
        if f["length"]!=len(d)-f["headerLen"]: continue
        body=d[f["headerLen"]:f["headerLen"]+f["length"]]
        content=None; padded=None
        if f["flags"]&1:
            if len(body)<8 or len(body)%8!=0: continue
            padded=await tea_cbc_decrypt(body,key); content=await oicq_unpad(padded)
            if content is None: continue
        else: content=body
        score=(1 if crc_ok else 0)+(1 if content is not None else 0)
        cands.append({"kind":kind,"layout":layout,"headerLen":f["headerLen"],
            "msgKey":d[0],"cmd":f["cmd"],"flags":f["flags"],"sendOption":f["sendOption"],
            "orderId":f.get("orderId"),"length":f["length"],"content":content,
            "crcOk":crc_ok,"padded":padded,"score":score,"total":len(d)})
    if not cands: return None
    cands.sort(key=lambda c:(c["kind"]=="RUDP" or c["kind"]=="nonRUDP",c["score"]),reverse=True)
    return cands[0]


# ==================== PLAY GAME ====================
async def play_game(server_ip_port,thunder,sharma,udp_key,match_code,
                    account_id,player_region,client_version,key,iv,
                    match_index,mode_label="BR"):
    t0=time.time(); ping_task=None; sock=None; stop=asyncio.Event()
    uid_str=str(account_id); done_ok=False
    try:
        ip,port=server_ip_port.split(":"); port=int(port)
        rip=await resolve_host_cloudflare(ip); loop=asyncio.get_event_loop()
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try: sock.bind(('0.0.0.0',0))
        except Exception: pass
        optimize_udp_socket(sock); sock.setblocking(False)
        ukb=bytes.fromhex(udp_key)
        hp=await build_hello_packet(f"{account_id}_2585",ukb,match_code)
        try:
            await loop.sock_sendto(sock,bytes.fromhex(hp),(rip,port))
            log(f"[{mode_label} M#{match_index}] HELLO sent {len(bytes.fromhex(hp))}B")
        except Exception as e: log(f"[{mode_label} M#{match_index}] HELLO fail: {e}")

        state="wait_hello"; t_sent=False; s_sent=False; jm=False; closed=False
        lock=asyncio.Lock()
        ping_task=asyncio.create_task(keepalive_ping(sock,rip,port,ukb,match_code,stop))
        last=time.time()

        async def send_ts():
            nonlocal state,t_sent,s_sent
            if t_sent: return
            async with lock:
                if t_sent: return
                try:
                    await loop.sock_sendto(sock,bytes.fromhex(thunder),(rip,port))
                    log(f"[{mode_label} M#{match_index}] THUNDER sent"); t_sent=True
                    await asyncio.sleep(0.3)
                    pa=await build_packet(0x68,(await layouts_from_mask(match_code))[1],0,2,None,1,b"\x01\x00",ukb)
                    await loop.sock_sendto(sock,pa,(rip,port))
                    log(f"[{mode_label} M#{match_index}] PREP-ACK sent")
                    await asyncio.sleep(0.4)
                    await loop.sock_sendto(sock,bytes.fromhex(sharma),(rip,port))
                    log(f"[{mode_label} M#{match_index}] SHARMA sent"); s_sent=True
                    state="sent"
                except Exception as e: log(f"[{mode_label} M#{match_index}] send err: {e}")

        while not closed:
            if time.time()-t0>MAX_MATCH_DURATION: done_ok=True; break
            try:
                resp,addr=await asyncio.wait_for(loop.sock_recvfrom(sock,65535),timeout=1.5)
                if resp:
                    last=time.time()
                    fr=await decode_packet(resp,ukb,match_code)
                    if fr:
                        pt=await classify(fr); cmd=fr['cmd']
                        if cmd in [103,107]:
                            print_success(f"[{mode_label} M#{match_index}] ✅ COMPLETED")
                            done_ok=True; closed=True; continue
                        if cmd==101:
                            try:
                                ap=await build_packet(0x68,(await layouts_from_mask(match_code))[1],0,2,None,1,b"\x01\x00",ukb)
                                await loop.sock_sendto(sock,ap,addr)
                            except Exception: pass
                            continue
                        if pt in ["ACK","PING","HELLO","JOIN_MATCH"]:
                            if pt=="HELLO" and state=="wait_hello":
                                _,rep=await reply_for(fr,ukb,match_code,ack_style="short")
                                if rep: await loop.sock_sendto(sock,rep,addr)
                                state="ack_wait"
                            elif pt=="ACK":
                                if state=="wait_hello":
                                    _,rep=await reply_for(fr,ukb,match_code)
                                    if rep: await loop.sock_sendto(sock,rep,addr)
                                    state="ready"
                                elif state=="ack_wait": state="ready"
                                else:
                                    _,rep=await reply_for(fr,ukb,match_code)
                                    if rep: await loop.sock_sendto(sock,rep,addr)
                            elif pt=="PING":
                                _,rep=await reply_for(fr,ukb,match_code)
                                if rep: await loop.sock_sendto(sock,rep,addr)
                            elif pt=="JOIN_MATCH" and not jm:
                                _,rep=await reply_for(fr,ukb,match_code)
                                if rep: await loop.sock_sendto(sock,rep,addr); jm=True
            except asyncio.TimeoutError:
                if state=="ready" and not t_sent: await send_ts()
                elif state=="wait_hello":
                    if time.time()-last>7.0:
                        try:
                            hp=await build_hello_packet(f"{account_id}_2585",ukb,match_code)
                            await loop.sock_sendto(sock,bytes.fromhex(hp),(rip,port))
                        except Exception: pass
                        last=time.time()
                    if time.time()-t0>25.0:
                        print_warning(f"[{mode_label} M#{match_index}] handshake timeout"); break
                elif state=="sent":
                    if time.time()-last>MATCH_IDLE_TIMEOUT:
                        print_success(f"[{mode_label} M#{match_index}] ✅ finished")
                        done_ok=True; break
                continue
            except BlockingIOError: await asyncio.sleep(0.05)
            except OSError: await asyncio.sleep(0.5); continue
            except Exception: await asyncio.sleep(0.5); continue
            if state=="ready" and not t_sent: await send_ts()
        return f"{mode_label} m#{match_index} done"
    except Exception as e:
        log(f"[{mode_label} M#{match_index}] err: {e}"); return f"{mode_label} m#{match_index} err"
    finally:
        if done_ok: exp_tracker.inc_match(uid_str, mode_label)
        stop.set()
        if ping_task:
            ping_task.cancel()
            try: await ping_task
            except asyncio.CancelledError: pass
        if sock:
            try: sock.close()
            except Exception: pass
        rem=await _dec_match(uid_str, mode_label)
        exp_tracker.set_status(uid_str, f"{mode_label} active={rem}")
        print_info(f"[{mode_label} M#{match_index}] closed. {mode_label} active: {rem}")


# ==================== EXP TRACKER ====================
class ExpTracker:
    def __init__(self): self.accounts={}
    def register(self,uid,nick,lvl,exp,reg):
        uid=str(uid)
        if uid not in self.accounts:
            self.accounts[uid]={"uid":uid,"nickname":nick,"region":reg,"level":lvl,
                "initial_exp":exp,"current_exp":exp,"gained_exp":0,
                "br_matches":0,"lw_matches":0,"status":"ONLINE"}
        else:
            a=self.accounts[uid]; a["nickname"]=nick or a["nickname"]
            a["region"]=reg or a["region"]; a["level"]=lvl or a["level"]
            a["current_exp"]=exp; a["gained_exp"]=max(0,exp-a["initial_exp"])
    def update_exp(self,uid,ce,lvl=0):
        uid=str(uid)
        if uid in self.accounts:
            a=self.accounts[uid]; old=a["current_exp"]; a["current_exp"]=ce
            if lvl>0: a["level"]=lvl
            a["gained_exp"]=max(0,ce-a["initial_exp"])
            diff=ce-old
            if diff>0: log(f"    💰 EXP +{diff} | Total +{a['gained_exp']} | Lvl {a['level']}")
    def inc_match(self,uid,mode):
        uid=str(uid)
        if uid in self.accounts:
            if mode=="BR": self.accounts[uid]["br_matches"]+=1
            else: self.accounts[uid]["lw_matches"]+=1
    def set_status(self,uid,s):
        uid=str(uid)
        if uid in self.accounts: self.accounts[uid]["status"]=s
    def print_summary(self):
        if not self.accounts: return
        log("\n" + "="*60)
        log("              📊 LIVE SUMMARY")
        log("="*60)
        for uid,a in self.accounts.items():
            log(f"  👤 {a['nickname']} (UID {uid})")
            log(f"     {a['region']} | Lvl {a['level']} | BR:{a['br_matches']} LW:{a['lw_matches']}")
            log(f"     EXP {a['initial_exp']} → {a['current_exp']} | +{a['gained_exp']}")
            log(f"     Status {a['status']}")
            log("-"*60)

exp_tracker = ExpTracker()

# Match counters per (uid, mode)
_mc: Dict[str,int]={}
_mc_lock=asyncio.Lock()
def _key(uid,mode): return f"{uid}_{mode}"
async def _inc_match(uid,mode):
    async with _mc_lock:
        k=_key(uid,mode); _mc[k]=_mc.get(k,0)+1; return _mc[k]
async def _dec_match(uid,mode):
    async with _mc_lock:
        k=_key(uid,mode)
        if k in _mc and _mc[k]>0: _mc[k]-=1
        return _mc.get(k,0)
async def _get_match_count(uid,mode):
    async with _mc_lock: return _mc.get(_key(uid,mode),0)


# ==================== WORKER: STARTMATCH + MATCH PARSE ====================
async def worker_loop(addrs, starter_packet, account_region, client_version,
                      key, iv, account_id="", account_data=None,
                      mode="BR", max_reconnects=10):
    """
    mode = "BR" or "LW"
    Har mode ka apna TCP gateway + match parse
    """
    reconnects=0; ip,port=addrs.split(":")
    no_resp=0; attempts=0; last_start=0.0; uid_str=str(account_id)
    ct=starter_packet; ck=key; civ=iv; cad=account_data
    mode_label = mode

    try:
        while True:
            writer=None; gwt=None
            try:
                rip=await resolve_host_cloudflare(ip)
                reader,writer=await asyncio.open_connection(rip,int(port))
                rs=writer.get_extra_info('socket')
                if rs: optimize_tcp_socket(rs)
                writer.write(bytes.fromhex(ct)); await writer.drain()
                try:
                    ka=await send_keep_alive(account_region)
                    if ka and writer and not writer.is_closing():
                        writer.write(ka); await asyncio.wait_for(writer.drain(),timeout=3)
                except Exception: pass

                async def gw_ka():
                    kb=await send_keep_alive(account_region)
                    while True:
                        await asyncio.sleep(5)
                        try:
                            if writer and not writer.is_closing():
                                writer.write(kb); await writer.drain()
                        except Exception: break

                gwt=asyncio.create_task(gw_ka())
                print_success(f"[{mode_label}] TCP gateway UID={uid_str} DNS={rip}")
                reconnects=0; no_resp=0; last_start=0.0

                async def send_sm():
                    nonlocal attempts,last_start
                    attempts+=1
                    try:
                        await asyncio.sleep(random.uniform(0.2,0.5))
                        log(f"[{mode_label}] UID {uid_str} search #{attempts}")
                        if mode=="BR":
                            await start_game_battle_royale(account_region,client_version,writer,ck,civ)
                        else:
                            await start_game_lone_wolf(account_region,client_version,writer,ck,civ)
                    except Exception as e:
                        log(f"[!] start match {mode_label}: {e}")
                    last_start=asyncio.get_running_loop().time()

                await send_sm()
                while True:
                    now=asyncio.get_running_loop().time()
                    if now-last_start>=START_MATCH_INTERVAL:
                        await send_sm()
                    try:
                        data=await asyncio.wait_for(reader.read(65535),timeout=0.5)
                    except asyncio.TimeoutError:
                        no_resp+=1
                        if no_resp>300:
                            no_resp=0
                            raise ConnectionError(f"{mode_label} idle")
                        continue
                    if not data: raise ConnectionError("closed")
                    hd=data.hex(); pl=len(data); no_resp=0
                    if pl<10: continue
                    is_m=False; ph=None
                    if hd.startswith("0300"):
                        if 10<pl<30:
                            log(f"[{mode_label}] queue ok UID={uid_str}"); continue
                        elif pl>=300: is_m=True; ph=hd[10:]
                        else: continue
                    elif pl>=200: is_m=True; ph=hd
                    if not is_m: continue
                    print_success(f"[{mode_label}] Match found UID={uid_str} size={pl}")

                    try:
                        res=json.loads(await decode_protobuf(ph))
                        token=None; udp_key=None; mc=None; sip=None; maid=None; bv=None
                        if '42' in res and 'data' in res['42']: mc=res['42']['data']
                        if '5' in res and 'data' in res['5']:
                            r5=res['5']['data']
                            sip=r5.get('2',{}).get('data')
                            udp_key=r5.get('3',{}).get('data')
                            token=r5.get('4',{}).get('data')
                            if '42' in r5: mc=r5['42']['data']
                        if '1' in res and 'data' in res['1']: maid=res['1']['data']
                        if '5' in res and 'data' in res['5']:
                            bv=res['5']['data'].get('1',{}).get('data')
                        eid=maid or account_id or f"{mode_label}_BOT"
                        if token and udp_key and mc and sip:
                            at=cad.get('access_token','') if cad else ""
                            th,sh=await build_match_startup_packets(token,udp_key,mc,eid,bv or 0,
                                server_ip=sip,region=account_region,client_version=client_version,
                                access_token=at,mode_id=1,map_id=1)
                            mi=await _inc_match(uid_str,mode_label)
                            print_success(f"[{mode_label} M#{mi}] injected → {sip}")
                            nm=asyncio.create_task(play_game(sip,th,sh,udp_key,mc,eid,
                                account_region,client_version,ck,civ,match_index=mi,mode_label=mode_label))

                            # drain gateway while match plays
                            async def drain():
                                while not nm.done():
                                    try:
                                        dg=await asyncio.wait_for(reader.read(4096),timeout=1.0)
                                        if not dg: break
                                    except asyncio.TimeoutError: continue
                                    except Exception: break
                            dt=asyncio.create_task(drain())
                            try: await nm
                            except Exception as e: log(f"[{mode_label} M#{mi}] err: {e}")
                            finally:
                                dt.cancel()
                                try: await dt
                                except asyncio.CancelledError: pass

                            try: await refresh_account_profile(cad)
                            except Exception: pass

                            if gwt: gwt.cancel()
                            await safe_close_writer(writer); writer=None
                            log(f"[OFF] {mode_label} match done → {NEW_MATCH_DELAY}s → next")
                            await asyncio.sleep(NEW_MATCH_DELAY)
                            break
                        else:
                            continue
                    except Exception as e:
                        log(f"[!] parse {mode_label}: {e}"); continue
            except asyncio.CancelledError:
                if gwt: gwt.cancel()
                raise
            except Exception as e:
                if gwt: gwt.cancel()
                await safe_close_writer(writer)
                reconnects+=1
                if reconnects>max_reconnects:
                    reconnects=0
                    await asyncio.sleep(3)
                else:
                    await asyncio.sleep(min(reconnects*0.5,2.0))
            finally:
                if gwt: gwt.cancel()
                if writer: await safe_close_writer(writer)
    except asyncio.CancelledError:
        raise


# ==================== INFORMATIONAL ====================
async def informational(addrs, starter_packet, key, iv, region=None, account_id="", max_reconnects=3):
    if region is None: region=ACCOUNT_REGION
    uid_str=str(account_id); reconnects=0; ip,port=addrs.split(":")
    while True:
        writer=None; pt=None
        try:
            rip=await resolve_host_cloudflare(ip)
            reader,writer=await asyncio.open_connection(rip,int(port))
            rs=writer.get_extra_info('socket')
            if rs: optimize_tcp_socket(rs)
            writer.write(bytes.fromhex(starter_packet)); await writer.drain()
            reconnects=0
            try:
                ka=await send_keep_alive(region)
                if ka and writer and not writer.is_closing():
                    writer.write(ka); await asyncio.wait_for(writer.drain(),timeout=3)
            except Exception: pass
            async def ika():
                kb=await send_keep_alive(region)
                while True:
                    await asyncio.sleep(5)
                    try:
                        if writer and not writer.is_closing():
                            writer.write(kb); await writer.drain()
                    except Exception: break
            pt=asyncio.create_task(ika())
            while True:
                try: d=await asyncio.wait_for(reader.read(8192),timeout=1.0)
                except asyncio.TimeoutError: continue
                if not d: raise ConnectionError("closed")
        except asyncio.CancelledError:
            if pt: pt.cancel()
            await safe_close_writer(writer); raise
        except Exception:
            if pt: pt.cancel()
            await safe_close_writer(writer)
            reconnects+=1
            if reconnects>max_reconnects: await asyncio.sleep(3); reconnects=0
            else: await asyncio.sleep(1)


async def refresh_account_profile(ad):
    try:
        if not ad: return
        url=ad.get('server_url'); tok=ad.get('token')
        rv=ad.get('release_version'); pl=ad.get('login_payload_data')
        if not (url and tok and rv and pl): return
        res=await send_getlogin(pl,url,tok,rv)
        if not res: return
        rp,dr=res
        lvl=int(get_proto_field(dr,6,1)); exp=int(get_proto_field(dr,7,0))
        aid=str(ad['account_id'])
        if exp>0: exp_tracker.update_exp(aid,exp,lvl)
    except Exception: pass


# ==================== LOGIN ====================
async def process_account_uid_pass(uid: str, password: str) -> Optional[Dict]:
    cache_key=f"guest_{uid}"
    cached=cache_get(cache_key)
    if cached:
        print_success(f"[CACHE HIT] UID {uid} → instant login")
        return cached

    log(f"[*] Login UID: {uid} (fresh OAuth)")
    try:
        async with _LOGIN_SEMAPHORE:
            vc=await version_config()
            if vc is None: return None
            rv,cv,su=vc
            tg=await get_access_token(uid,password)
            if tg is None:
                log(f"[-] OAuth failed {uid}"); return None
            oid,at,pl=tg
            print_success(f"[LOGIN] OAuth OK open_id={oid[:12]}...")

            dev=get_device_for_account(uid)
            print_info(f"[DEVICE] {dev['brand']} {dev['model']}")

            payload=await build_majorlogin_payload(oid,at,pl,cv,dev)
            if payload is None: return None

            ml=await send_majorlogin(payload,rv,su)
            if ml is None:
                log(f"[-] MajorLogin failed"); return None
            print_success(f"[LOGIN] MajorLogin OK acc={ml.account_id} reg={ml.region}")

            gl=await send_getlogin(payload,ml.url,ml.token,rv)
            if gl is None:
                log(f"[-] GetLoginData failed"); return None
            rp,dr=gl

        acc_id=str(ml.account_id)
        if acc_id=="0" or not acc_id or acc_id=="None":
            log(f"[-] invalid acc_id"); return None

        lvl=int(get_proto_field(dr,6,1)); exp=int(get_proto_field(dr,7,0))
        nick=rp.nickname or get_proto_field(dr,4,f"P_{acc_id}")
        reg=ml.region or get_proto_field(dr,3,ACCOUNT_REGION)
        if lvl<=0: lvl=1
        if exp<0: exp=0

        fa=rp.functional_addrs; ia=rp.informational_addrs
        if not isinstance(fa,str) or not fa or ":" not in fa: fa=None
        if not isinstance(ia,str) or not ia or ":" not in ia: ia=None

        kv=ml.aes_ak; ivv=ml.iv_i
        if not isinstance(kv,(bytes,bytearray)) or len(kv)<16: kv=AES_KEY
        if not isinstance(ivv,(bytes,bytearray)) or len(ivv)<16: ivv=AES_IV

        print_success(f"[PROFILE] {nick} | Lvl {lvl} | Reg {reg} | addr={fa}")
        exp_tracker.register(acc_id,nick,lvl,exp,reg)

        ad={
            'account_id': ml.account_id,
            'nickname': nick,
            'region': reg,
            'level': lvl,
            'exp': exp,
            'open_id': oid,
            'access_token': at,
            'platform': str(pl),
            'token': ml.token,
            'server_time': ml.server_time,
            'aes_ak': kv,
            'iv_i': ivv,
            'functional_addrs': fa,
            'informational_addrs': ia,
            'release_version': rv,
            'client_version': cv,
            'server_url': ml.url,
            'login_payload_data': payload,
            'auth_type': 'guest',
            'auth_uid': uid,
            'auth_password': password
        }
        cache_set(cache_key, ad)
        return ad
    except Exception as e:
        log(f"[-] process_account: {e}"); return None


# ==================== ACCOUNT WORKER (BR → LW) ====================
async def run_account_worker(ad: Dict, label: str):
    acc_id=str(ad['account_id'])
    informational_task=None; exp_task=None; br_task=None; lw_task=None
    try:
        reg=ad.get('region',ACCOUNT_REGION)
        fa=ad.get('functional_addrs'); ia=ad.get('informational_addrs')
        if not fa or not isinstance(fa,str) or ":" not in fa:
            print_warning(f"no functional_addrs for {acc_id}"); return

        tpo=await build_tcp_startup_packet(ad['account_id'],ad['token'],ad['server_time'],
            ad['aes_ak'],ad['iv_i'],region=reg,typ='OnLine')
        tpc=await build_tcp_startup_packet(ad['account_id'],ad['token'],ad['server_time'],
            ad['aes_ak'],ad['iv_i'],region=reg,typ='ChaT')

        if ia and isinstance(ia,str) and ":" in ia:
            informational_task=asyncio.create_task(informational(ia,tpc,ad['aes_ak'],ad['iv_i'],
                region=reg,account_id=acc_id))

        async def exp_refresher():
            while True:
                await asyncio.sleep(120+random.uniform(-10,10))
                try: await refresh_account_profile(ad)
                except Exception: pass
        exp_task=asyncio.create_task(exp_refresher())

        # ============ STEP 1: BR (ONCE) ============
        print_info(f"[{acc_id}] === PHASE 1: BR match (once) ===")
        br_task=asyncio.create_task(worker_loop(fa,tpo,ad['region'],ad['client_version'],
            ad['aes_ak'],ad['iv_i'],account_id=acc_id,account_data=ad,mode="BR"))
        try:
            await br_task
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print_error(f"BR worker error: {e}")

        print_success(f"[{acc_id}] === PHASE 1 COMPLETE (BR done) ===")
        await asyncio.sleep(3)

        # ============ STEP 2: LONE WOLF (loop, max 2 total) ============
        print_info(f"[{acc_id}] === PHASE 2: Lone Wolf (loop) ===")
        while True:
            # check total active LW across all accounts
            total_active=await _get_match_count("GLOBAL","LW")
            if total_active>=LW_MAX_PARALLEL_TOTAL:
                await asyncio.sleep(2)
                continue

            # check this account's LW count
            my_active=await _get_match_count(acc_id,"LW")
            if my_active>=LW_MAX_PARALLEL_PER_ACCOUNT:
                await asyncio.sleep(2)
                continue

            print_info(f"[{acc_id}] Starting LW worker (my={my_active}, total={total_active})")
            try:
                await worker_loop(fa,tpo,ad['region'],ad['client_version'],
                    ad['aes_ak'],ad['iv_i'],account_id=acc_id,account_data=ad,mode="LW")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print_error(f"LW worker error: {e}")
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print_error(f"run_account_worker {label}: {e}")
        import traceback; traceback.print_exc()
    finally:
        for t in (informational_task,exp_task,br_task,lw_task):
            if t and not t.done(): t.cancel()
        for t in (informational_task,exp_task,br_task,lw_task):
            if t:
                try: await t
                except (asyncio.CancelledError,Exception): pass


async def account_loop_guest(uid: str, password: str):
    uid_str=str(uid)
    while True:
        try:
            log(f"[LOOP] login UID: {uid_str}")
            ad=await process_account_uid_pass(uid_str,password)
            if not ad:
                log(f"[-] Login failed {uid_str}. Retry 15s...")
                await asyncio.sleep(15); continue
            await run_account_worker(ad,uid_str)
            log(f"[!] Session ended {uid_str}. Reconnect 3s...")
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            log(f"[!] stopped {uid_str}"); break
        except Exception as e:
            log(f"[-] err {uid_str}: {e}. Retry 10s...")
            await asyncio.sleep(10)


# ==================== MAIN ====================
def load_accounts():
    accounts=[]
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE,"r",encoding="utf-8") as f:
                d=json.load(f)
                if isinstance(d,list):
                    accounts=d
                    print_success(f"[accounts.json] {len(accounts)} account(s)")
        except Exception as e:
            print_error(f"accounts.json: {e}")
    return accounts


def _prompt():
    print("[i] Enter UID and password")
    return [{"uid": input("UID: ").strip(), "password": input("Password: ").strip()}]


def _prompt_region():
    print("[i] Region: IND")
    return "IND"


async def main():
    global ACCOUNT_REGION
    os.system('cls' if os.name=='nt' else 'clear')
    print("="*60)
    print("    TEAM 84FF — BR (once) → Lone Wolf (loop, max 2)")
    print("="*60)
    print(f"[i] BR: 1 match (once)")
    print(f"[i] LW: max {LW_MAX_PARALLEL_TOTAL} parallel total")
    print(f"[i] Cache TTL: {TOKEN_CACHE_TTL}s")
    print(f"[i] accounts.json: {ACCOUNTS_FILE}")
    print("="*60)

    accs=load_accounts()
    if not accs:
        print_warning("accounts.json not found → manual entry")
        accs=_prompt()

    r=_prompt_region()
    ACCOUNT_REGION=r
    print(f"[i] Region = {ACCOUNT_REGION}")

    tasks=[]
    for i,acc in enumerate(accs,1):
        uid=str(acc.get("uid","")).strip()
        pw=str(acc.get("password","")).strip()
        if not uid or not pw:
            print_error(f"skip invalid #{i}: {acc}"); continue
        log(f"[*] Launching worker {i} | UID: {uid}")
        tasks.append(asyncio.create_task(account_loop_guest(uid,pw)))

    if not tasks:
        print_error("No valid accounts"); return

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt,asyncio.CancelledError):
        log("[!] Shutting down...")
        for t in tasks: t.cancel()
        for t in tasks:
            try: await t
            except (asyncio.CancelledError,Exception): pass
        log("[+] All closed.")


if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\nStopped.")