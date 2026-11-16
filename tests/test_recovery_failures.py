"""Fault injection against production storage and OTA admission/cancellation code.
Negative controls must fail the same executable assertions.
"""
from pathlib import Path
import subprocess, tempfile
R=Path(__file__).resolve().parents[1]
c=(R/'src/config.cpp').read_text(); h=(R/'src/config.h').read_text(); w=(R/'src/web.cpp').read_text(); b=(R/'src/bridge.cpp').read_text()
struct=h[h.index('struct BridgeConfig {'):h.index('\n};',h.index('struct BridgeConfig {'))+3]
pre=r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
using esp_err_t=int;using nvs_handle_t=int;
constexpr int ESP_OK=0,ESP_ERR_NVS_NOT_FOUND=1,NVS_READONLY=0,NVS_READWRITE=1;
constexpr unsigned CFG_MAGIC=1234;
#define CFG_NVS_NS "config"
#define CFG_NVS_KEY "blob"
static int fault=0;static bool claimed=false,exists=false;
static std::string blob;
static int nvs_open(const char *ns,int mode,int *h){
 if(fault==1)return -1; *h=!strcmp(ns,"provisioning")?1:2;
 if(mode==0&&((*h==1&&!claimed)||(*h==2&&!exists)))return ESP_ERR_NVS_NOT_FOUND;return 0;}
static void nvs_close(int){}
static int nvs_get_u8(int,const char*,uint8_t *v){if(fault==2)return -1;*v=claimed;return 0;}
static int nvs_set_u8(int,const char*,uint8_t){if(fault==3)return -1;claimed=true;return 0;}
static int nvs_commit(int){return fault==4?-1:0;}
static int nvs_get_blob(int,const char*,void *out,size_t *sz){
 if(fault==5)return -1;if(blob.empty())return ESP_ERR_NVS_NOT_FOUND;
 if(out)memcpy(out,blob.data(),blob.size());*sz=blob.size();return 0;}
'''
load=c[c.index('void cfg_defaults('):c.index('/* Persist g_cfg')]
main=r'''
static void valid(){BridgeConfig v;cfg_defaults(&v);v.configured=true;blob.assign((char*)&v,sizeof(v));exists=true;}
int main(){
 assert(cfg_load()&&!g_cfg.configured); // absent namespace, no marker
 claimed=true;assert(!cfg_load()&&g_cfg.configured); // lost namespace
 exists=true;assert(!cfg_load()); // lost blob
 valid();assert(cfg_load()&&g_cfg.configured);
 for(int f:{1,2,5}){fault=f;assert(!cfg_load());}fault=0;
 blob="bad";assert(!cfg_load());valid();blob[0]^=1;assert(!cfg_load());
 valid();claimed=false;fault=3;assert(!cfg_load());fault=4;claimed=false;assert(!cfg_load());
 fault=0;claimed=false;valid();assert(cfg_load()&&claimed); // legacy enrollment
}
'''
ota_pre=r'''
#include <cassert>
#include <cstdint>
#include <mutex>
#include "provisioning_session.h"
struct httpd_req_t{};
static uint32_t now=0;static uint32_t millis(){return now;}
static bool s_session_configured=true;static uint32_t s_session_started_at=0;
static int shutdowns=0;
constexpr int SHUT_RDWR=2;
static int shutdown(int,int){++shutdowns;return 0;}
static int httpd_req_to_sockfd(httpd_req_t*){return 7;}
'''
a=w.index('static std::mutex s_ota_mutex');e=w.index('uint32_t web_last_activity_ms',a);ota=w[a:e]
ota_main=r'''
int main(){httpd_req_t r;
 {OtaSession active(&r);assert(active.admitted&&!web_shutdown_ready());
  OtaSession duplicate(&r);assert(!duplicate.admitted);
  now=PROVISIONING_MAX_SESSION_MS;assert(active.cancelled());
  OtaSession late(&r);assert(!late.admitted);
  web_expire();assert(shutdowns==1&&!web_shutdown_ready());
 }
 assert(web_shutdown_ready());OtaSession denied(&r);assert(!denied.admitted);
}
'''
# Guard production wiring as well as executing the shared cancellation protocol.
assert 'ESP_ERROR_CHECK(esp_wifi_' not in b[b.index('bool bridge_wifi_start'):b.index('/* Arm the data path')]
assert 'if (esp_wifi_init(&fb) != ESP_OK) return fail();' in b
for call in ('esp_wifi_deinit()', 'esp_netif_destroy_default_wifi(s_mgmt_netif)', 'esp_event_handler_unregister('):assert call in b
handler=w[w.index('static esp_err_t h_update('):w.index('/* ===========================================================================',w.index('static esp_err_t h_update('))]
assert handler.count('session.cancelled()')>=2
assert 'if (session_closed())' in handler and 'std::lock_guard<std::mutex>' in handler
assert 'if (ota) esp_ota_abort(ota);' in handler
m=(R/'src/main.cpp').read_text();assert 'nvs_flash_erase()' not in m
assert m.index('if (!web_shutdown_ready())')<m.index('      esp_wifi_stop();')
with tempfile.TemporaryDirectory() as d:
 for name,src,negative in [('storage',pre+struct+'\nBridgeConfig g_cfg;\n'+load+main,load.replace('&& !commissioned','')),
                           ('ota',ota_pre+ota+ota_main,ota.replace('s_expired = true;','s_expired = false;').replace('if (!session_closed() && !s_ota_active)', 'if (!s_ota_active)'))]:
  for bad in (False,True):
   code=src if not bad else (src.replace(load,negative) if name=='storage' else src.replace(ota,negative))
   p=Path(d)/'test.cpp';p.write_text(code);exe=Path(d)/'test'
   subprocess.run(['g++','-std=c++17','-I'+str(R/'src'),str(p),'-o',str(exe)],check=True)
   result=subprocess.run([str(exe)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   assert (result.returncode==0)!=bad,(name,bad)
print('Storage fault injection and OTA cancellation/admission passed; negative controls rejected')
# Execute the production cleanup lambda and fallback branch with injected driver
# errors; unlike the lifecycle suite this does not double bridge_wifi_start.
a=b.index('  bool initialized = false, started = false;',b.index('bool bridge_wifi_start'))
e=b.index('#ifdef BRIDGE_MINIMAL',a);cleanup=b[a:e]
a=b.index('  esp_err_t werr = esp_wifi_init(&wcfg);');e=b.index('  /* Remember for display',a);fallback=b[a:e]
wpre=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
using esp_err_t=int;constexpr int ESP_OK=0,WIFI_EVENT=0,ESP_EVENT_ANY_ID=0;
struct wifi_init_config_t {unsigned rx_ba_win=32, static_rx_buf_num=16,dynamic_rx_buf_num=32;};
#define WIFI_INIT_CONFIG_DEFAULT() wifi_init_config_t{}
static bool s_active=false,s_wifi_up=false;
static void *s_mgmt_netif=(void*)1;static int calls=0,deinits=0,destroyed=0,stops=0;
static void wifi_evt(){}static void disc_on_restart(){}
static void esp_event_handler_unregister(int,int,void(*)()){}
static void esp_unregister_shutdown_handler(void(*)()){}
static void esp_wifi_stop(){++stops;}static int esp_wifi_deinit(){++deinits;return 0;}
static void esp_netif_destroy_default_wifi(void*){++destroyed;}
static int esp_wifi_init(wifi_init_config_t*){++calls;return -1;}
static const char *esp_err_to_name(int){return "fault";}
static bool run(int mode){
'''
wsource=wpre+cleanup+'wifi_init_config_t wcfg; if(mode==1){initialized=started=true;return fail();}\n'+fallback+'return true;}\n'+r'''
int main(){assert(!run(0));assert(calls==3&&destroyed==1&&!deinits&&!stops&&!s_mgmt_netif);
s_mgmt_netif=(void*)1;assert(!run(1));assert(deinits==1&&stops==1&&destroyed==2);}
'''
with tempfile.TemporaryDirectory() as d:
 for bad in (False,True):
  src=wsource if not bad else wsource.replace('if (esp_wifi_init(&fb) != ESP_OK) return fail();','if (esp_wifi_init(&fb) != ESP_OK) __builtin_trap();')
  p=Path(d)/'wifi.cpp';p.write_text(src);exe=Path(d)/'wifi'
  subprocess.run(['g++','-std=c++17',str(p),'-o',str(exe)],check=True)
  result=subprocess.run([str(exe)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  assert (result.returncode==0)!=bad
print('Wi-Fi init/partial-start cleanup injection passed; fatal-error negative control rejected')
# Existing policy negative controls run in disposable trees, never production.
import shutil
for which in ('automatic-portal','unbounded-session'):
 with tempfile.TemporaryDirectory() as d:
  root=Path(d);shutil.copytree(R/'src',root/'src');(root/'tests').mkdir()
  shutil.copy(R/'tests/test_provisioning.py',root/'tests/test_provisioning.py')
  p=root/('src/main.cpp' if which=='automatic-portal' else 'src/provisioning_session.h')
  text=p.read_text()
  text=text.replace('if (!g_cfg.configured) {','if (!g_cfg.configured || s_boot_failures >= 3) {') if which=='automatic-portal' else text.replace('return configured_at_entry &&','return false && configured_at_entry &&')
  p.write_text(text)
  result=subprocess.run(['python3',str(root/'tests/test_provisioning.py')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  assert result.returncode!=0,which
print('Repeated-failure provisioning and deadline-removal negative controls rejected')
# Execute the real upload handler with failures at every OTA API boundary.
u=w[w.index('static esp_err_t h_update('):w.index('/* ===========================================================================',w.index('static esp_err_t h_update('))]
u_pre=ota_pre.replace('struct httpd_req_t{};', 'struct httpd_req_t{unsigned content_len=8;};')+r'''
#include <cstdlib>
#include <cstdio>
using esp_err_t=int;using esp_ota_handle_t=unsigned;
constexpr int ESP_OK=0,ESP_FAIL=-1,HTTPD_401_UNAUTHORIZED=401,HTTPD_500_INTERNAL_SERVER_ERROR=500;
constexpr int HTTPD_400_BAD_REQUEST=400,HTTPD_SOCK_ERR_TIMEOUT=-3,HTTPD_RESP_USE_STRLEN=-1;
constexpr int ESP_ERR_OTA_VALIDATE_FAILED=-4;constexpr unsigned OTA_SIZE_UNKNOWN=0xffffffff,ESP_IMAGE_HEADER_MAGIC=0xe9;
struct esp_partition_t{const char *label="app1";unsigned size=100;};
static int fault=0,aborts=0,ends=0,commits=0;static bool handle=false,paused=false;
static bool admin_key_ok(httpd_req_t*){return true;}
static void httpd_resp_send_err(httpd_req_t*,int,const char*){}
static void httpd_resp_set_type(httpd_req_t*,const char*){}
static void httpd_resp_send(httpd_req_t*,const char*,int){}
static const char *esp_err_to_name(int){return "fault";}
static void delay(int){}
static void bridge_set_paused(bool v){paused=v;}
static const esp_partition_t *esp_ota_get_next_update_partition(void*){static esp_partition_t p;return &p;}
static int esp_ota_begin(const esp_partition_t*,unsigned,esp_ota_handle_t *h){*h=1;handle=true;return fault==1?-1:0;}
static int esp_ota_abort(unsigned){++aborts;handle=false;return 0;}
static int esp_ota_write(unsigned,const void*,unsigned){return fault==3?-1:0;}
static int esp_ota_end(unsigned){++ends;handle=false;return fault==4?-1:0;}
static int esp_ota_set_boot_partition(const esp_partition_t*){++commits;return fault==5?-1:0;}
'''
u_recv=r'''
static int httpd_req_recv(httpd_req_t*,char *buf,unsigned n){
 if(fault==2)return -1;
 if(fault==6){now=PROVISIONING_MAX_SESSION_MS;web_expire();assert(!web_shutdown_ready());}
 buf[0]=ESP_IMAGE_HEADER_MAGIC;return n;
}
'''
u_main=r'''
int main(){httpd_req_t r;
 for(fault=1;fault<=6;++fault){
  now=0;s_expired=false;aborts=ends=commits=0;handle=false;
  assert(h_update(&r)==ESP_FAIL);assert(!handle&&!paused&&web_shutdown_ready());
  if(fault==6)assert(!commits&&aborts==1&&shutdowns==1);
 }
 now=PROVISIONING_MAX_SESSION_MS;s_expired=false;fault=0;
 assert(h_update(&r)==ESP_FAIL&&!handle&&web_shutdown_ready());
 now=0;assert(h_update(&r)==ESP_OK&&commits==1&&s_expired&&!handle&&web_shutdown_ready());
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'upload.cpp';p.write_text(u_pre+ota+u_recv+u+u_main);exe=Path(d)/'upload'
 subprocess.run(['g++','-std=c++17','-I'+str(R/'src'),str(p),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,stdout=subprocess.DEVNULL)
print('Actual OTA handler begin/receive/write/end/commit/expiry cleanup and success passed')
