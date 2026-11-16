"""Exercise the production JSON escaper, scan handler and browser error path."""
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
web = (ROOT / 'src/web.cpp').read_text()
escape = web[web.index('static bool json_escape('):web.index('/* ===========================================================================', web.index('static bool json_escape('))]
scan = web[web.index('static esp_err_t h_scan('):web.index('/* ===========================================================================', web.index('static esp_err_t h_scan('))]
preamble = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
using esp_err_t = int;
constexpr int ESP_OK=0, ESP_FAIL=-1, HTTPD_RESP_USE_STRLEN=-1;
struct httpd_req_t {std::string body; int status=200, chunks=0;};
struct wifi_scan_config_t {bool show_hidden;};
struct wifi_ap_record_t {unsigned char ssid[33]; int8_t rssi;};
static std::vector<wifi_ap_record_t> records;
static int failure=0, clears=0, allocations=0, send_failure=-1;
static unsigned s_last_activity_ms;
static unsigned millis(){return 42;}
static int esp_wifi_scan_start(wifi_scan_config_t *sc,bool block){assert(!sc->show_hidden&&block);return failure==1?ESP_FAIL:ESP_OK;}
static int esp_wifi_scan_get_ap_num(uint16_t *n){*n=records.size();return failure==2?ESP_FAIL:ESP_OK;}
static int esp_wifi_scan_get_ap_records(uint16_t *n,wifi_ap_record_t *out){assert(*n<=20);if(failure==3)return ESP_FAIL;memcpy(out,records.data(),*n*sizeof(*out));return ESP_OK;}
static void esp_wifi_clear_ap_list(){++clears;}
static void httpd_resp_set_type(httpd_req_t*,const char *s){assert(!strcmp(s,"application/json"));}
static void httpd_resp_set_status(httpd_req_t *r,const char*){r->status=500;}
static int httpd_resp_send(httpd_req_t *r,const char *s,int){r->body=s;return ESP_OK;}
static int httpd_resp_sendstr_chunk(httpd_req_t *r,const char *s){if(r->chunks++==send_failure)return ESP_FAIL;if(s)r->body+=s;return ESP_OK;}
static void *scan_malloc(size_t n){if(failure==4)return nullptr;++allocations;return malloc(n);}
static void scan_free(void *p){if(p)--allocations;free(p);}
#define malloc scan_malloc
#define free scan_free
'''
main = r'''
#undef malloc
#undef free
static void add(const std::string &ssid,int rssi=-42){wifi_ap_record_t ap{};assert(ssid.size()<=32);memcpy(ap.ssid,ssid.data(),ssid.size());ap.rssi=rssi;records.push_back(ap);}
static void emit(){httpd_req_t r;assert(h_scan(&r)==ESP_OK);assert(r.status==200&&allocations==0);puts(r.body.c_str());}
int main(){
 // Every control byte, including embedded NUL, must round-trip.
 std::string controls;for(int c=0;c<32;c++)controls+=(char)c;
 controls+="\"\\";char escaped[205];
 assert(json_escape(controls.data(),escaped,sizeof(escaped),controls.size()));
 printf("\"%s\"\n",escaped);
 // Sweep every output capacity with canaries and verify complete escape tokens.
 for(size_t cap=0;cap<206;cap++){
   unsigned char out[208];memset(out,0xa5,sizeof(out));
   bool ok=json_escape(controls.data(),(char*)out+1,cap,controls.size());
   assert(out[0]==0xa5&&out[cap+1]==0xa5);
   if(cap){assert(memchr(out+1,0,cap));printf("\"%s\"\n",out+1);}
   assert(ok==(cap>=197));
 }
 // Hidden first result, JSON injection, newline, tabs and maximum expansion.
 add("");add("\"}],[{\"ssid\":\"spoof\\\n\r\t");add(std::string(32,'\x01'),-128);
 add("ordinary");add("caf\xc3\xa9");emit();
 // All non-NUL controls in an actual SSID.
 records.clear();add(controls.substr(1,31));emit();
 // Driver data without a terminator must not read past the 32-byte SSID.
 records.clear();add(std::string(32,'\\'));records[0].ssid[32]='x';emit();
 records.clear();emit();
 for(int i=0;i<25;i++){add("network");}emit();
 for(failure=1;failure<=4;failure++){
   clears=0;httpd_req_t r;assert(h_scan(&r)==ESP_OK);
   assert(r.status==500&&allocations==0&&clears==(failure==1?0:1));puts(r.body.c_str());
 }
 failure=0;
 for(send_failure=0;send_failure<23;send_failure++){
   httpd_req_t r;assert(h_scan(&r)==ESP_FAIL&&allocations==0);
   assert(r.chunks==send_failure+1);
 }
}
'''
ui = web[web.index('async function scan(){'):web.index('/* rb=true', web.index('async function scan(){'))]
ui_tests = r'''
const assert=require('node:assert/strict');
const elements={msg:{textContent:''},nets:{textContent:'old',children:[],appendChild(o){this.children.push(o)}},ssid1:{value:'manual'},ssid2:{value:'backup'},ssid3:{value:'third'}};
const $=id=>elements[id];
const document={createElement:()=>({})};
(async()=>{
 for(const fetcher of [async()=>{throw Error('network')},async()=>({ok:false}),async()=>({ok:true,json:async()=>{throw Error('JSON')}}),async()=>({ok:true,json:async()=>({error:'scan'})}),async()=>({ok:true,json:async()=>[null]})]){
  global.fetch=fetcher;await scan();assert.match(elements.msg.textContent,/Scan failed/);assert.equal(elements.nets.textContent,'old');
 }
 const ssid='<img src=x onerror=alert(1)>\n';
 global.fetch=async()=>({ok:true,json:async()=>[{ssid,rssi:-42}]});await scan();
 assert.equal(elements.nets.children[0].value,ssid);assert.equal(elements.msg.textContent,'1 networks found');
 global.fetch=async()=>({ok:true,json:async()=>[]});await scan();assert.equal(elements.msg.textContent,'0 networks found');
 assert.equal(elements.ssid1.value,'manual');assert.equal(elements.ssid2.value,'backup');assert.equal(elements.ssid3.value,'third');
 console.log('Browser scan errors, recovery, safe DOM output and manual SSIDs passed');
})().catch(e=>{console.error(e);process.exit(1)});
'''
# The shared helper also serves saved configuration. Exercise maximum-length
# control strings there so the enlarged aggregate response cannot truncate.
config_header = (ROOT / 'src/config.h').read_text()
config_struct = config_header[config_header.index('struct BridgeConfig {'):config_header.index('\n};') + 3]
bridge_header = (ROOT / 'src/bridge.h').read_text()
end = bridge_header.index('} bridge_tuning_t;') + len('} bridge_tuning_t;')
tuning = bridge_header[bridge_header.rindex('typedef struct {', 0, end):end]
config_function = web[web.index('static esp_err_t h_config_get('):web.index('/* POST /api/config', web.index('static esp_err_t h_config_get('))]
config_doubles = r'''
static BridgeConfig g_cfg;
constexpr int HTTPD_500_INTERNAL_SERVER_ERROR=500;
static void httpd_resp_send_err(httpd_req_t *r,int code,const char *s){r->status=code;r->body=s;}
static void httpd_resp_set_hdr(httpd_req_t*,const char*,const char*){}
static void format_ipv4(const uint8_t *ip,char *out,size_t size){snprintf(out,size,"%u.%u.%u.%u",ip[0],ip[1],ip[2],ip[3]);}
static void bridge_get_effective(bridge_tuning_t *t){memset(t,0xff,sizeof(*t));}
static void bridge_get_defaults(bridge_tuning_t *t){memset(t,0xff,sizeof(*t));}
'''
config_main = r'''
#undef malloc
#undef free
template<size_t N> static void fill(char (&s)[N]){memset(s,1,N-1);s[N-1]=0;}
int main(){
 memset(&g_cfg,0xff,sizeof(g_cfg));
 fill(g_cfg.name);fill(g_cfg.ssid1);fill(g_cfg.ssid2);fill(g_cfg.ssid3);
 fill(g_cfg.mqtt_host);fill(g_cfg.mqtt_user);
 httpd_req_t r;assert(h_config_get(&r)==ESP_OK&&r.status==200&&allocations==0);puts(r.body.c_str());
 failure=4;r={};assert(h_config_get(&r)==ESP_FAIL&&r.status==500&&allocations==0);
}
'''
crash_header = (ROOT / 'src/crashlog.h').read_text()
crash_struct = crash_header[crash_header.index('typedef struct {'):crash_header.index('} crash_rec_t;') + len('} crash_rec_t;')]
crash_function = web[web.index('static esp_err_t h_crashes_get('):web.index('/* DELETE /api/crashes', web.index('static esp_err_t h_crashes_get('))]
crash_doubles = r'''
constexpr int CRASHLOG_N=8, HTTPD_401_UNAUTHORIZED=401;
static bool admin_key_ok(httpd_req_t*){return true;}
static uint32_t crashlog_now(){return UINT32_MAX;}
static size_t crashlog_get(crash_rec_t *out,size_t n){
 for(size_t i=0;i<n;i++){
  memset(&out[i],0xff,sizeof(out[i]));
  memset(out[i].task,1,sizeof(out[i].task)-1);out[i].task[sizeof(out[i].task)-1]=0;
  memset(out[i].reason,1,sizeof(out[i].reason)-1);out[i].reason[sizeof(out[i].reason)-1]=0;
  memset(out[i].build,1,sizeof(out[i].build)-1);out[i].build[sizeof(out[i].build)-1]=0;
 }
 return n;
}
'''
crash_main = r'''
#undef malloc
#undef free
int main(){httpd_req_t r;assert(h_crashes_get(&r)==ESP_OK&&r.status==200&&allocations==0);puts(r.body.c_str());}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    source = path / 'scan.cpp'
    source.write_text(preamble + escape + scan + main)
    binary = path / 'scan'
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(source), '-o', str(binary)], check=True)
    lines = subprocess.check_output([str(binary)], text=True).splitlines()
    parsed = [json.loads(line) for line in lines]
    assert parsed[0] == ''.join(map(chr, range(32))) + '"\\'
    for prefix in parsed[1:206]:
        assert parsed[0].startswith(prefix)
    results = parsed[206:]
    assert results[0] == [
        {'ssid': '"}],[{"ssid":"spoof\\\n\r\t', 'rssi': -42},
        {'ssid': '\x01' * 32, 'rssi': -128},
        {'ssid': 'ordinary', 'rssi': -42}, {'ssid': 'café', 'rssi': -42}]
    assert results[1] == [{'ssid': ''.join(map(chr, range(1,32))), 'rssi': -42}]
    assert results[2] == [{'ssid': '\\' * 32, 'rssi': -42}]
    assert results[3] == [] and len(results[4]) == 20
    assert all('error' in error for error in results[5:])
    source.write_text(preamble + config_struct + tuning + config_doubles + escape + config_function + config_main)
    subprocess.run(['g++', '-std=c++17', '-fsanitize=address,undefined',
                    str(source), '-o', str(binary)], check=True)
    configuration = json.loads(subprocess.check_output([str(binary)], text=True))
    for key, length in [('name',31), ('ssid1',32), ('ssid2',32), ('ssid3',32),
                        ('mqtt_host',63), ('mqtt_user',64)]:
        assert configuration[key] == '\x01' * length
    source.write_text(preamble + config_struct + tuning + config_doubles + crash_struct
                      + crash_doubles + escape + crash_function + crash_main)
    subprocess.run(['g++', '-std=c++17', '-fsanitize=address,undefined',
                    str(source), '-o', str(binary)], check=True)
    crashes = json.loads(subprocess.check_output([str(binary)], text=True))['recs']
    assert len(crashes) == 8
    for crash in crashes:
        assert crash['task'] == '\x01' * 15
        assert crash['reason'] == '\x01' * 95
        assert crash['build'] == '\x01' * 11
    script = path / 'scan.js'
    script.write_text(ui + ui_tests)
    subprocess.run(['node', str(script)], check=True)
print('Scan JSON round-trips, buffer boundaries, driver/allocation/send errors passed (ASan/UBSan).')
