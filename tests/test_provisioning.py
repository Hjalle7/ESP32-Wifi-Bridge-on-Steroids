"""Execute actual startup, GPIO, session/OTA lifecycle and retry tick on the host.

Driver doubles simulate failures; target radio/rollback acceptance is separate.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
s = (ROOT / 'src/main.cpp').read_text()
source = s[s.index('/* Pull this input'):s.index('/* ---------------------------------------------------------------------------\n * Entry point.')]
preamble = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include "provisioning_session.h"
#define RTC_NOINIT_ATTR
#define ESP_ERROR_CHECK(x) assert((x)==0)
using esp_err_t=int;
using esp_ota_img_states_t=int;
using gpio_num_t=int;
struct esp_partition_t {};
constexpr int ESP_OK=0, ESP_OTA_IMG_PENDING_VERIFY=1, ESP_ERR_INVALID_STATE=2;
constexpr int ESP_ERR_NVS_NO_FREE_PAGES=3, ESP_ERR_NVS_NEW_VERSION_FOUND=4;
constexpr int ESP_RST_SW=1, ESP_RST_TASK_WDT=2;
constexpr int GPIO_MODE_INPUT=0, GPIO_PULLUP_ENABLE=1, AP_IDLE_REBOOT_S_DEF=300;
struct gpio_config_t {uint64_t pin_bit_mask;int mode,pull_up_en;};
struct Config {bool configured=true; char ssid1[32]="saved-network";
 uint8_t client_mac[6]={2,0,0,0,0,1};uint32_t ap_idle_reboot_s=3600;} g_cfg;
struct BridgeStats {bool wifi_up,eth_link;};
static uint32_t clock_ms=0,last_activity=0,learn_at=UINT32_MAX;
static int portals=0,servers=0,restarts=0,stops=0,erases=0,saves=0;
static int eth_calls=0,wifi_calls=0,ticks=0,valid_calls=0,rollback_calls=0;
static int nvs_result=0;static bool config_readable=true;
static int reset_reason=ESP_RST_SW,ota_state=2;
static bool pin_low=false,active=false,eth_ok=true,wifi_init_ok=true;
static bool wifi_up=false,eth_link=true,sniff_ok=true,mac_known=true;
static bool planned=false,requested=false;
struct Restart {};
static uint32_t millis(){return clock_ms;}
static void delay(uint32_t ms){clock_ms+=ms;}
static void esp_restart(){++restarts;throw Restart{};}
static int esp_reset_reason(){return reset_reason;}
static int esp_wifi_stop(){++stops;return 0;}
static int gpio_config(gpio_config_t*){return 0;}
static int gpio_get_level(int){return pin_low?0:1;}
static int nvs_flash_init(){return nvs_result;}
static int nvs_flash_erase(){++erases;return 0;}
static int esp_netif_init(){return 0;}
static int esp_event_loop_create_default(){return 0;}
static void conlog_persist_prev(){}
static bool cfg_load(){return config_readable;}
static void cfg_save(){++saves;}
static void crashlog_boot(bool){}
static bool bridge_consume_planned_restart(){bool r=planned;planned=false;return r;}
static bool bridge_consume_requested_restart(){bool r=requested;requested=false;return r;}
static void bridge_restart_requested(){requested=true;esp_restart();}
static bool portal_start_ap(){++portals;return true;}
static bool web_start(bool provisioning){assert(provisioning);++servers;last_activity=millis();return true;}
static void web_expire(){}
static bool web_exit_requested(){return false;}
static bool web_shutdown_ready(){return true;}
static uint32_t web_last_activity_ms(){return last_activity;}
static bool bridge_eth_init(){++eth_calls;return eth_ok;}
static bool bridge_sniff_client_mac(uint32_t){return sniff_ok;}
static bool bridge_client_mac_known(){return mac_known || clock_ms>=learn_at;}
static void bridge_get_client_mac(uint8_t *out){memcpy(out,g_cfg.client_mac,6);if(!mac_known)out[0]=2;}
static void bridge_set_client_mac(const uint8_t*){}
// An exhausted association returns initialized/offline, not an init error.
static bool bridge_wifi_start(){++wifi_calls;return wifi_init_ok;}
static void bridge_activate(){active=true;}
static bool bridge_is_active(){return active;}
static void bridge_get_mgmt_ip(uint8_t *out){memset(out,0,4);}
static void format_ipv4(const uint8_t*,char *out,size_t){strcpy(out,"0.0.0.0");}
static void bridge_get_stats(BridgeStats *out){out->wifi_up=wifi_up;out->eth_link=eth_link;}
static void bridge_tick(){++ticks;}
static void telemetry_start(){}
static void telemetry_tick(){}
static const esp_partition_t *esp_ota_get_running_partition(){static esp_partition_t p;return &p;}
static int esp_ota_get_state_partition(const esp_partition_t*,int *st){*st=ota_state;return 0;}
static int esp_ota_mark_app_valid_cancel_rollback(){++valid_calls;return 0;}
static int esp_ota_mark_app_invalid_rollback_and_reboot(){++rollback_calls;esp_restart();return 0;}
static const char *esp_err_to_name(int){return "error";}
'''
main = r'''
static void assert_closed(){assert(!portals&&!servers&&!erases);}
static void simulate_boot(){active=false;s_provisioning=false;s_stable_reported=false;bridge_setup();}
int main(int argc,char **argv){
 assert(argc==2);std::string c=argv[1];
 Config saved=g_cfg;
 if(c=="nvs-unreadable"||c=="config-unreadable"){
  if(c=="nvs-unreadable")nvs_result=ESP_ERR_NVS_NO_FREE_PAGES;
  else config_readable=false;
  bridge_setup();bridge_loop();assert_closed();assert(!restarts&&!active);
  return 0;
 }
 if(c=="no-mac"||c=="no-mac-ota"){
  memset(g_cfg.client_mac,0,6);sniff_ok=false;mac_known=false;
  if(c=="no-mac"){
   learn_at=2000;bridge_setup();assert_closed();assert(active&&saves==1);
   assert(g_cfg.client_mac[0]==2&&clock_ms>=2000&&!restarts);
  }else{
   ota_state=ESP_OTA_IMG_PENDING_VERIFY;
   try{bridge_setup();assert(false);}catch(Restart&){}
   assert_closed();assert(rollback_calls==1&&!saves&&!active);
   assert(clock_ms>=180000);
  }
  return 0;
 }
 if(c=="initial"){g_cfg.configured=false;bridge_setup();assert(portals==1&&servers==1);
  clock_ms+=3*PROVISIONING_MAX_SESSION_MS;bridge_loop();assert(!restarts);return 0;}
 if(c=="gpio-boot"){pin_low=true;bridge_setup();assert(portals==1&&servers==1);
  assert(clock_ms>=3000&&!erases);assert(!memcmp(&saved,&g_cfg,sizeof saved));return 0;}
 if(c=="gpio-runtime"){
  bridge_setup();pin_low=true;provisioning_button_tick();clock_ms+=2999;
  pin_low=false;provisioning_button_tick();assert(!restarts); // too short
  pin_low=true;provisioning_button_tick();clock_ms+=3000;pin_low=false;
  try{provisioning_button_tick();assert(false);}catch(Restart&){}
  assert(requested&&s_portal_request==PORTAL_MAGIC);
  simulate_boot();assert(portals==1&&servers==1&&s_portal_request==0);
  simulate_boot();assert(portals==1&&servers==1); // token cannot be replayed
  assert(!memcmp(&saved,&g_cfg,sizeof saved));return 0;
 }
 if(c=="absolute"||c=="held-expiry"||c=="wrap"){
  if(c=="wrap")clock_ms=UINT32_MAX-10000;
  pin_low=true;bridge_setup();pin_low=false;uint32_t start=s_provisioning_started_at;
   for(uint32_t t=60000;t<PROVISIONING_MAX_SESSION_MS;t+=60000){
    clock_ms=start+t;last_activity=millis();bridge_loop();assert(!restarts);
   }
   clock_ms=start+PROVISIONING_MAX_SESSION_MS-1;last_activity=millis();bridge_loop();assert(!restarts);
   clock_ms=start+PROVISIONING_MAX_SESSION_MS;last_activity=millis();
  try{bridge_loop();assert(false);}catch(Restart&){}
  assert(stops==1&&restarts==1&&!s_portal_request&&requested);
  if(c=="held-expiry")pin_low=true; // same held boot authorization
  simulate_boot();assert(!s_provisioning&&portals==1&&servers==1);
  if(c=="held-expiry"){
   clock_ms+=3000;provisioning_button_tick();pin_low=false;provisioning_button_tick();
   assert(restarts==1); // releasing the original hold does not grant a new session
   pin_low=true;provisioning_button_tick();clock_ms+=3000;pin_low=false;
   try{provisioning_button_tick();assert(false);}catch(Restart&){}
   simulate_boot();assert(s_provisioning&&portals==2);
  }
  assert(!memcmp(&saved,&g_cfg,sizeof saved));return 0;
 }
 if(c=="inactivity"){
  g_cfg.ap_idle_reboot_s=60;pin_low=true;bridge_setup();pin_low=false;
  uint32_t start=clock_ms;
  clock_ms=start+59999;bridge_loop();assert(!restarts);
  last_activity=clock_ms;clock_ms+=59999;bridge_loop();assert(!restarts);
  clock_ms=last_activity+60000;try{bridge_loop();assert(false);}catch(Restart&){}
  assert(stops==1&&!s_portal_request);return 0;
 }
 if(c=="eth-failure"||c=="ota-eth-failure")eth_ok=false;
 if(c=="wifi-init-failure")wifi_init_ok=false;
 if(c=="empty-ssid")g_cfg.ssid1[0]=0;
 if(c=="watchdog"){planned=true;reset_reason=ESP_RST_TASK_WDT;}
 if(c=="stale-physical"){s_portal_request=PORTAL_MAGIC;requested=true;reset_reason=ESP_RST_TASK_WDT;}
 if(c=="ota-failure"||c=="ota-eth-failure")ota_state=ESP_OTA_IMG_PENDING_VERIFY;
 if(c=="repeated-boots"){
  for(int i=0;i<10;++i){simulate_boot();assert_closed();}
  assert(s_boot_failures==9&&!restarts);return 0;
 }
 bridge_setup();assert_closed();assert(!restarts);
 if(c=="eth-failure"||c=="ota-eth-failure"||c=="wifi-init-failure")assert(!active);
 else assert(active&&!wifi_up); // failed startup association stays in normal mode
 if(c=="stale-physical")assert(!s_portal_request);
 bridge_loop();uint32_t start=clock_ms-50;
 if(c=="ota-failure"||c=="ota-eth-failure"){
  clock_ms=start+179999;bridge_loop();assert(!rollback_calls&&!valid_calls);
  clock_ms=start+180000;try{bridge_loop();assert(false);}catch(Restart&){}
  assert(rollback_calls==1&&!valid_calls);assert_closed();
 }else{
  for(int i=0;i<10;++i){clock_ms+=60000;bridge_loop();}
  assert(!restarts);assert_closed();
 }
 if(c!="empty-ssid")assert(!memcmp(&saved,&g_cfg,sizeof saved));
}
'''
bridge = (ROOT / 'src/bridge.cpp').read_text()
a = bridge.index('static void wifi_retry_tick(')
b = bridge.index('\nvoid bridge_tick', a)
retry = bridge[a:b]
retry_test = r'''
#include <cassert>
#include <cstdint>
static uint32_t clock_ms=0;
static bool s_active=true,s_restarting=false,s_wifi_up=false;
static unsigned connects=0;
static uint32_t millis(){return clock_ms;}
static void esp_wifi_connect(){++connects;}
'''+retry+r'''
int main(){
 for(clock_ms=0;clock_ms<60000;++clock_ms)wifi_retry_tick();
 assert(connects==11); // immediate failures cannot spin in the event callback
 s_wifi_up=true;clock_ms+=60000;wifi_retry_tick();assert(connects==11);
 s_wifi_up=false;s_restarting=true;wifi_retry_tick();assert(connects==11);
 s_restarting=false;s_active=false;wifi_retry_tick();assert(connects==11);
 s_active=true;clock_ms=UINT32_MAX-1000;wifi_retry_tick();assert(connects==12);
 clock_ms+=4999;wifi_retry_tick();assert(connects==12);
 clock_ms+=1;wifi_retry_tick();assert(connects==13);
}
'''
# Guard the production wiring around the executed retry helper.
assert 'esp_wifi_connect()' not in bridge[bridge.index('static void wifi_evt('):bridge.index('/* ===========================================================================\n * Ethernet')]
tail = bridge[bridge.index('  esp_log_level_set("wifi", ESP_LOG_WARN);\n  /* Driver/netif'):bridge.index('/* Arm the data path')]
assert 'return true;' in tail and 'esp_wifi_stop' not in tail
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)
    for name,unit in [('lifecycle',preamble+source+main),('retry',retry_test)]:
        cpp=path/(name+'.cpp');cpp.write_text(unit)
        binary=path/name
        subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-I'+str(ROOT/'src'),str(cpp),'-o',str(binary)],check=True)
        cases = ('nvs-unreadable','config-unreadable','wifi-association','repeated-boots','eth-failure','wifi-init-failure',
                 'watchdog','stale-physical','ota-failure','ota-eth-failure','gpio-boot','gpio-runtime',
                 'initial','no-mac','no-mac-ota','absolute','held-expiry','inactivity','wrap','empty-ssid') if name=='lifecycle' else ('retry',)
        for case in cases:
            subprocess.run([str(binary),case],check=True,stdout=subprocess.DEVNULL)
print('Provisioning startup/fault/GPIO/session/rollback and bounded retry checks passed')
