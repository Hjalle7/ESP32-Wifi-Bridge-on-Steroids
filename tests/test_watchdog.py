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
preamble=r'''
#include <cstdint>
#include <cstdio>
#include <cassert>
#include "local_watchdog.h"
#define RTC_NOINIT_ATTR
#define WD_ACT_ETH_RESET 1
#define WD_ACT_WIFI_RECON 2
#define WD_ACT_REBOOT 4
#define WD_REASON_MAGIC 0x57445253u
#define DISC_SRC_WATCHDOG 1
static uint32_t clock_ms=100,s_wd_reason_magic=0;
static bool s_active=true,s_paused=false,s_eth_link=true,s_wifi_up=true;
static uint32_t s_pkt_e2w=0,s_drop_e2w=0,s_pkt_w2e=0,s_drop_w2e=0,s_wifi_disc_count=0;
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
main=r'''
/* Reset volatile state while optionally preserving the reboot budget. */
static void reset(bool preserve=false){
 clock_ms=100;s_active=true;s_paused=false;s_eth_link=true;s_wifi_up=true;
 s_pkt_e2w=s_drop_e2w=s_pkt_w2e=s_drop_w2e=s_wifi_disc_count=0;
 s_wd_t0=s_wd_pkt0=s_wd_drop0=s_wd_disc0=s_wd_eth_pkt0=s_wd_eth_drop0=0;
 s_wd_last_action=s_wd_healthy_since=0;s_wd_bad=s_wd_probe=s_wd_stage=s_wd_previous_reason=0;
 g_cfg={};if(!preserve){s_wd_reboot_budget=0;s_wd_reason_magic=0;}
 ethernet_resets=reconnects=0;
 watchdog_tick();
}
/* Advance one window, optionally injecting actual transmit-error evidence. */
static bool window(bool errors=false){
 clock_ms+=20000;if(errors){s_pkt_w2e+=170;s_drop_w2e+=30;}
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
 reset();g_cfg.bad=255;
 for(int i=0;i<254;++i){assert(!window(true));}
 assert(ethernet_resets==0);
 assert(!window(true));assert(ethernet_resets==1);
 puts("Watchdog quiet/outage/cooldown/reboot-budget checks passed");
}
'''
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory);(path/'watchdog.cpp').write_text(preamble+policy+globals_+tick+main)
    binary=path/'watchdog'
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-I'+str(ROOT/'src'),str(path/'watchdog.cpp'),'-o',str(binary)],check=True)
    result=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
    print(result.stdout.splitlines()[-1])
