"""Exercise the actual local recovery state machine with simulated drivers/time."""
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
s=(ROOT/'src/bridge.cpp').read_text()
a=s.index('#define WD_WINDOW_MS');b=s.index('/* Failed-boot exception',a)
policy=s[a:b]
a=s.index('static uint32_t s_wd_t0');b=s.index('/* Restart the Ethernet driver',a)
globals_=s[a:b]
a=s.index('static void watchdog_tick(');b=s.index('/* ===========================================================================\n * Active roaming',a)
tick=s[a:b]
# Exercise the real policy-drop and transmit branches, without packet parsing.
a=s.index('  /* Queue cap:');b=s.index('\n/*\n * Does this frame belong', a)
forwarding=s[a:b]
a=s.index('IRAM_ATTR static esp_err_t wifi_rx_cb(');b=s.index('/* Ethernet input callback',a)
ethernet=s[a:b]
preamble=r'''
#include <cstdint>
#include <cstdio>
#include <cassert>
#include <cstdlib>
#include <initializer_list>
#include "local_watchdog.h"
#define RTC_NOINIT_ATTR
#define WD_ACT_ETH_RESET 1
#define WD_ACT_WIFI_RECON 2
#define WD_ACT_REBOOT 4
#define WD_REASON_MAGIC 0x57445253u
#define DISC_SRC_WATCHDOG 1
static uint32_t clock_ms=100,s_wd_reason_magic=0;
static bool s_active=true,s_paused=false,s_eth_link=true,s_wifi_up=true;
static uint32_t s_pkt_e2w=0,s_drop_e2w=0,s_pkt_w2e=0,s_drop_w2e=0,s_wifi_disc_count=0,s_fail_e2w=0,s_fail_w2e=0;
struct Config{bool wd_enable=true;uint8_t bad=1,actions=7;}g_cfg;
static unsigned ethernet_resets=0,reconnects=0,reboots=0;
struct Reboot{};
/* Use simulated uptime so long cooldown/quiet intervals run immediately. */
static uint32_t millis(){return clock_ms;}
/* Match configured policy without involving NVS. */
static uint8_t wd_actions_eff(){return g_cfg.actions;}
/* Default thresholds are tested separately from settings storage. */
static uint8_t wd_bad_windows_eff(){return g_cfg.bad;}
/* Driver doubles count effects while keeping network behavior out of scope. */
static bool bridge_reset_eth(){++ethernet_resets;return true;}
/* Model a connection request without synthesizing a successful association. */
static void esp_wifi_connect(){++reconnects;}
/* Count reconnect escalation on an associated link. */
static void esp_wifi_disconnect(){++reconnects;}
/* Provenance tagging has no effect on local classification in these tests. */
static void disc_mark_own(int){}
/* Telemetry must not control or delay recovery. */
static void telemetry_note_watchdog_event(const char*,const char*){}
/* Preserve the validity marker that the real boot path uses. */
static void bridge_mark_planned_restart(uint8_t){s_wd_reason_magic=WD_REASON_MAGIC;}
#define abort() throw Reboot{}
'''
forwarding_preamble=r'''
using esp_err_t=int;
constexpr int ESP_OK=0,ESP_FAIL=-1,ESP_ERR_NO_MEM=-2,WIFI_IF_STA=0;
constexpr uint32_t TXQ_CAP_MIN_LEN=100;
static uint8_t s_txq_cap=0,s_eth_tx_retries=1;
static uint32_t s_drop_cap=0,s_drop_thr=0,s_thr_kbps=0,s_air_done=0;
static uint64_t s_by_e2w=0;
static int32_t s_thr_tokens=0;
static int64_t s_thr_last_us=0;
static int queue_depth=0,tx_result=ESP_OK;
static unsigned tx_calls=0;
static int txq_depth(uint32_t){return queue_depth;}
static int64_t esp_timer_get_time(){return (int64_t)clock_ms*1000;}
static int esp_wifi_internal_tx(int,void*,uint16_t){++tx_calls;return tx_result;}
static void taskYIELD(){}
static void eth_tx_retry_wait(){}
/* The callback tail owns its buffer and includes every intentional drop. */
static int forward(uint32_t len=1000){
 uint8_t *buffer=static_cast<uint8_t*>(malloc(len));assert(buffer);
'''
ethernet_preamble=r'''
#define IRAM_ATTR
#define BRIDGE_MINIMAL
static void *s_eth=(void*)1;
static uint8_t s_wifi_tx_retries=1;
static uint64_t s_by_w2e=0;
static unsigned eth_calls=0,rx_frees=0;
static unsigned transient_eth_failures=0;
static int esp_eth_transmit(void*,void*,uint16_t){++eth_calls;if(transient_eth_failures){--transient_eth_failures;return ESP_FAIL;}return tx_result;}
static void vTaskDelay(int){}
static void esp_wifi_internal_free_rx_buffer(void*){++rx_frees;}
static esp_err_t wifi_rx_cb(void*,uint16_t,void*);
static void receive_eth(){uint8_t frame[14]{};wifi_rx_cb(frame,14,frame);}
'''
main=r'''
/* Reset volatile state while optionally preserving the reboot budget. */
static void reset(bool preserve=false){
 clock_ms=100;s_active=true;s_paused=false;s_eth_link=true;s_wifi_up=true;
 s_pkt_e2w=s_drop_e2w=s_pkt_w2e=s_drop_w2e=s_wifi_disc_count=s_fail_e2w=s_fail_w2e=0;
 s_txq_cap=0;s_thr_kbps=0;s_drop_cap=s_drop_thr=0;s_thr_tokens=0;
 s_eth_tx_retries=1;queue_depth=0;tx_result=ESP_OK;tx_calls=0;
 s_wd_t0=s_wd_pkt0=s_wd_drop0=s_wd_disc0=s_wd_eth_pkt0=s_wd_eth_drop0=0;
 s_wd_last_action=s_wd_healthy_since=0;s_wd_bad=s_wd_probe=s_wd_stage=s_wd_previous_reason=0;
 g_cfg={};if(!preserve){s_wd_reboot_budget=0;s_wd_reason_magic=0;}
 ethernet_resets=reconnects=0;
 watchdog_tick();
}
/* Advance one window, optionally injecting actual transmit-error evidence. */
static bool window(bool errors=false){
 clock_ms+=20000;if(errors){s_pkt_w2e+=170;s_drop_w2e+=30;s_fail_w2e+=30;}
 try{watchdog_tick();return false;}catch(Reboot&){++reboots;return true;}
}
/* Exercise quiet/cable/AP outages, cooldowns, symptom changes and reboot caps. */
int main(){
 reset();for(int i=0;i<100;++i)assert(!window());
 assert(!ethernet_resets&&!reconnects&&!reboots);
 reset();s_eth_link=false;for(int i=0;i<10;++i)assert(!window(true));
 assert(!ethernet_resets&&!reconnects&&!reboots);
 reset();s_wifi_up=false;for(int i=0;i<10;++i)assert(!window());
 assert(reconnects==4&&!ethernet_resets&&!reboots);
 reset();assert(!window(true));assert(ethernet_resets==1);
 assert(!window(true));assert(reconnects==0);assert(!window(true));assert(reconnects==0);
 assert(!window(true));assert(reconnects==1);
 for(int boot=0;boot<2;++boot){
  reset(boot>0);bool did_reboot=false;
  for(int i=0;i<12&&!did_reboot;++i)did_reboot=window(true);
  assert(did_reboot&&s_wd_reboot_budget==(unsigned)(boot+1));
 }
 const unsigned prior=reboots;reset(true);
 for(int i=0;i<20;++i)assert(!window(true));
 assert(reboots==prior&&s_wd_reboot_budget==2);
 reset(true);for(int i=0;i<32;++i)assert(!window());assert(s_wd_reboot_budget==0);

 // Sustained queue-cap or throttle drops remain telemetry only, even at
 // 100% loss. Use the real forwarding branches and recovery state machine.
 const unsigned before_policy=reboots;
 for(int policy=0;policy<2;++policy){
  reset();
  for(int i=0;i<20;++i){
   if(policy==0){s_txq_cap=1;queue_depth=1;}
   else{s_thr_kbps=1;s_thr_tokens=0;s_thr_last_us=esp_timer_get_time();}
   for(int j=0;j<200;++j)assert(forward()==ESP_OK);
   assert(!window());
  }
  assert(s_drop_e2w==4000&&s_fail_e2w==0&&tx_calls==0);
  assert((policy==0?s_drop_cap:s_drop_thr)==4000);
  assert(!ethernet_resets&&!reconnects&&reboots==before_policy);
 }
 // Offline frames also remain drops, without masquerading as driver errors
 // in the first window after Wi-Fi returns.
 reset();s_wifi_up=false;
 for(int j=0;j<200;++j)assert(forward()==ESP_OK);
 s_wifi_up=true;assert(!window());assert(s_drop_e2w==200&&s_fail_e2w==0);
 assert(!reconnects&&!ethernet_resets);
 // Mixed traffic: policy drops must neither inflate nor dilute the failure
 // ratio. Exactly 30 failures / 200 driver attempts still triggers recovery.
 for(int failures:{29,30}){
  reset();
  for(int j=0;j<200;++j){tx_result=j<failures?ESP_FAIL:ESP_OK;forward();}
  s_txq_cap=1;queue_depth=1;
  for(int j=0;j<1000;++j)forward();
  assert(s_fail_e2w==(unsigned)failures&&s_drop_e2w==1000u+failures);
  assert(!window());assert(reconnects==(failures==30?1u:0u));
 }
 // Retry exhaustion is one failed frame; genuine errors still escalate
 // through reconnect to reboot despite intentional drops in every window.
 reset();s_eth_tx_retries=3;tx_result=ESP_ERR_NO_MEM;forward();
 assert(tx_calls==3&&s_fail_e2w==1&&s_drop_e2w==1);
 reset();bool driver_reboot=false;
 for(int i=0;i<12&&!driver_reboot;++i){
  s_txq_cap=0;tx_result=ESP_FAIL;
  for(int j=0;j<200;++j)forward();
  s_txq_cap=1;queue_depth=1;
  for(int j=0;j<1000;++j)forward();
  driver_reboot=window();
 }
 assert(driver_reboot&&reconnects>0);
 // Both counters wrap independently; policy traffic cannot hide an error.
 reset();s_fail_e2w=UINT32_MAX-15;s_wd_drop0=s_fail_e2w;
 tx_result=ESP_FAIL;for(int j=0;j<30;++j)forward();
 tx_result=ESP_OK;for(int j=0;j<170;++j)forward();
 assert(!window());assert(reconnects==1);
 // Actual Ethernet receive path: cable loss and return inside one watchdog
 // window must not turn offline telemetry drops into a driver fault.
 reset();eth_calls=rx_frees=0;s_eth_link=false;
 for(int j=0;j<1000;++j)receive_eth();
 assert(s_drop_w2e==1000&&s_fail_w2e==0&&eth_calls==0&&rx_frees==1000);
 s_eth_link=true;assert(!window());
 for(int j=0;j<400;++j)receive_eth();
 assert(!window());assert(!ethernet_resets&&!reconnects);
 // Entire windows offline, then recovery, also stay below escalation.
 reset();s_eth_link=false;
 for(int i=0;i<12;++i){for(int j=0;j<200;++j)receive_eth();assert(!window());}
 s_eth_link=true;assert(!window());assert(!ethernet_resets&&!reconnects);
 // Paused/inactive/missing-driver drops are not driver calls either.
 reset();s_active=false;receive_eth();s_active=true;s_eth=nullptr;receive_eth();
 s_eth=(void*)1;s_paused=true;receive_eth();s_paused=false;
 assert(s_fail_w2e==0&&s_drop_w2e==2);
 // Real Ethernet failures retain the exact threshold and retry evidence.
 for(int failures:{29,30}){
  reset();for(int j=0;j<200;++j){tx_result=j<failures?ESP_FAIL:ESP_OK;receive_eth();}
  assert(s_fail_w2e==(unsigned)failures&&s_drop_w2e==(unsigned)failures);
  assert(!window());assert(ethernet_resets==(failures==30?1u:0u));
 }
 reset();s_wifi_tx_retries=3;eth_calls=0;transient_eth_failures=1;receive_eth();
 assert(eth_calls==2&&s_fail_w2e==1&&s_pkt_w2e==1&&s_drop_w2e==0);
 reset();s_wifi_tx_retries=3;eth_calls=0;tx_result=ESP_FAIL;receive_eth();
 assert(eth_calls==3&&s_fail_w2e==3&&s_drop_w2e==1);s_wifi_tx_retries=1;
 reset();s_fail_w2e=UINT32_MAX-15;s_wd_eth_drop0=s_fail_w2e;
 for(int j=0;j<200;++j){tx_result=j<30?ESP_FAIL:ESP_OK;receive_eth();}
 assert(!window());assert(ethernet_resets==1);
 reset();g_cfg.bad=255;
 for(int i=0;i<254;++i){assert(!window(true));}
 assert(ethernet_resets==0);
 assert(!window(true));assert(ethernet_resets==1);
 puts("Watchdog policy-drop/driver-failure/quiet/outage/cooldown/reboot-budget checks passed");
}
'''
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory);(path/'watchdog.cpp').write_text(preamble+policy+globals_+tick+forwarding_preamble+forwarding+ethernet_preamble+ethernet+main)
    binary=path/'watchdog'
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-I'+str(ROOT/'src'),str(path/'watchdog.cpp'),'-o',str(binary)],check=True)
    result=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
    print(result.stdout.splitlines()[-1])
