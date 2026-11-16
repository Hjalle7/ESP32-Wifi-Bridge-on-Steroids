"""Run the actual OTA validation tick against simulated time and IDF APIs."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
s = (ROOT / 'src/main.cpp').read_text()
a = s.index('#define OTA_VALIDATION_DEADLINE_MS')
b = s.index('/* Initialize the setup input', a)
tick = s[a:b]
preamble = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
using esp_err_t=int;
using esp_ota_img_states_t=int;
struct esp_partition_t {};
constexpr int ESP_OK=0, ESP_OTA_IMG_PENDING_VERIFY=1;
static bool s_ota_confirmed=false;
static uint32_t clock_ms=0;
static int state=ESP_OTA_IMG_PENDING_VERIFY,valid_result=0,rollback_result=-1;
static int valid_calls=0,rollback_calls=0,restarts=0;
struct RollbackReboot {};
static bool rollback_succeeds=false;
static uint32_t millis(){return clock_ms;}
static const esp_partition_t *esp_ota_get_running_partition(){static esp_partition_t p;return &p;}
static int esp_ota_get_state_partition(const esp_partition_t*,int *st){*st=state;return ESP_OK;}
static int esp_ota_mark_app_valid_cancel_rollback(){++valid_calls;return valid_result;}
static int esp_ota_mark_app_invalid_rollback_and_reboot(){++rollback_calls;if(rollback_succeeds)throw RollbackReboot{};return rollback_result;}
static const char *esp_err_to_name(int){return "simulated error";}
static void delay(unsigned){}
static void esp_restart(){++restarts;}
'''
main = r'''
int main(int argc,char **argv){
 assert(argc==2);
 rollback_succeeds=!strcmp(argv[1],"rollback-success");
 bool wrap=!strcmp(argv[1],"wrap");
 clock_ms=wrap?UINT32_MAX-15000:100;
 uint32_t start=clock_ms;
 if(!strcmp(argv[1],"ordinary"))state=2;
 if(!strcmp(argv[1],"confirm-failure"))valid_result=-1;
 bool success=!strcmp(argv[1],"success")||wrap;
 bool portal=!strcmp(argv[1],"unconfigured-portal");
 ota_validation_tick(success||portal||valid_result!=0);
 clock_ms=start+29999;ota_validation_tick(success||portal||valid_result!=0);
 assert(!valid_calls&&!rollback_calls);
 clock_ms=start+30000;ota_validation_tick(success||portal||valid_result!=0);
 if(success||portal){
  assert(s_ota_confirmed&&valid_calls==1);
  clock_ms=start+300000;ota_validation_tick(false);
  assert(!rollback_calls&&!restarts);return 0;
 }
 if(!strcmp(argv[1],"temporary-outage")){
  clock_ms=start+90000;ota_validation_tick(true);
  clock_ms=start+119999;ota_validation_tick(true);assert(!valid_calls);
  clock_ms=start+120000;ota_validation_tick(false); // reset continuous readiness
  clock_ms=start+121000;ota_validation_tick(true);
  clock_ms=start+151000;ota_validation_tick(true);
  assert(s_ota_confirmed&&valid_calls==1&&!rollback_calls);return 0;
 }
 // Ethernet never ready, flapping readiness, or a failed confirmation API.
 if(!strcmp(argv[1],"late-ready")){clock_ms=start+150000;ota_validation_tick(true);}
 if(!strcmp(argv[1],"flapping")){
  for(unsigned t=40000;t<170000;t+=20000){
   clock_ms=start+t;ota_validation_tick(true);
   clock_ms=start+t+10000;ota_validation_tick(false);
  }
  assert(!valid_calls);
 }
 clock_ms=start+179999;ota_validation_tick(true);assert(!rollback_calls);
 clock_ms=start+180000;
 try{ota_validation_tick(true);}catch(RollbackReboot&){
  assert(rollback_succeeds&&rollback_calls==1&&!restarts&&!s_ota_confirmed);return 0;
 }
 if(state==2){assert(!rollback_calls&&!valid_calls&&s_ota_confirmed);}
 else{assert(rollback_calls==1&&restarts==1&&!s_ota_confirmed);}
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    unit = path / 'ota.cpp'
    unit.write_text(preamble + tick + main)
    binary = path / 'ota'
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', str(unit), '-o', str(binary)], check=True)
    for case in ('success', 'never-ready', 'temporary-outage', 'confirm-failure',
                 'ordinary', 'unconfigured-portal', 'wrap', 'flapping', 'late-ready', 'rollback-success'):
        subprocess.run([str(binary), case], check=True)
print('OTA confirmation/deadline/API failure/startup/outage/wrap checks passed')
