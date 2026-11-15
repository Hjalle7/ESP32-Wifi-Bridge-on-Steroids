"""Run actual HTTP dispatch and MQTT producer functions with host-side doubles.

These checks cover authentication/origin gates and nonblocking queue behavior;
ESP-IDF builds and device tests remain separate acceptance requirements.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
web = (ROOT / 'src/web.cpp').read_text()
start = web.index('static bool admin_key_ok(')
end = web.index('/* POST /api/update', start)
functions = web[start:end]
telemetry = (ROOT / 'src/telemetry.cpp').read_text()
start = telemetry.index('struct TelemetryMessage')
end = telemetry.index('static QueueHandle_t', start)
message = telemetry[start:end]
start = telemetry.index('static void queue_publish(')
end = telemetry.index('/* Worker-only network operation', start)
producer = telemetry[start:end]
common = r'''
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include "provisioning_auth.h"
using esp_err_t = int;
constexpr int ESP_OK=0, ESP_FAIL=-1, HTTPD_401_UNAUTHORIZED=401, HTTPD_403_FORBIDDEN=403;
struct httpd_req_t { std::map<std::string,std::string> headers, response; void *user_ctx; int status=200; };
struct httpd_uri_t { void *user_ctx; esp_err_t (*handler)(httpd_req_t*); };
static bool s_provisioning=true;
static char s_http_password[33]="unit-test-secret";
static char s_http_basic[96]="Basic dW5pdC10ZXN0";
static int calls=0;
/* Model bounded IDF header reads, including absent/oversized headers. */
static int httpd_req_get_hdr_value_str(httpd_req_t *r,const char *n,char *out,size_t size) {
 auto i=r->headers.find(n); if(i==r->headers.end()||i->second.size()>=size) return ESP_FAIL;
 strcpy(out,i->second.c_str()); return ESP_OK;
}
/* Model IDF header length lookup. */
static size_t httpd_req_get_hdr_value_len(httpd_req_t *r,const char *n) {return r->headers[n].size();}
/* Capture the response instead of sending a socket packet. */
static void httpd_resp_set_hdr(httpd_req_t*r,const char*n,const char*v){r->response[n]=v;}
/* Capture rejection status. */
static void httpd_resp_send_err(httpd_req_t*r,int code,const char*){r->status=code;}
/* A protected handler must run only after the shared gates passed. */
static int protected_handler(httpd_req_t*r){assert(r->user_ctx==nullptr);++calls;return ESP_OK;}
'''
main = r'''
/* Exercise the same dispatch used for every registered route. */
int main() {
 httpd_uri_t route{nullptr,protected_handler}; httpd_req_t r;
 auto dispatch=[&](){r.user_ctx=&route;r.status=200;return provisioning_dispatch(&r);};
 assert(dispatch()==ESP_FAIL && r.status==401 && calls==0);
 assert(!r.response["WWW-Authenticate"].empty());
 r.headers["X-Admin-Key"]="wrong";assert(dispatch()==ESP_FAIL && calls==0);
 r.headers["X-Admin-Key"]="unit-test-secret";assert(dispatch()==ESP_OK && calls==1);
 r.headers.clear();r.headers["Authorization"]=s_http_basic;
 assert(dispatch()==ESP_OK && calls==2);
 r.headers["Sec-Fetch-Site"]="cross-site";assert(dispatch()==ESP_FAIL && r.status==403 && calls==2);
 r.headers["Sec-Fetch-Site"]="same-origin";r.headers["Host"]="192.168.4.1";
 r.headers["Origin"]="http://attacker.invalid";assert(dispatch()==ESP_FAIL && r.status==403 && calls==2);
 r.headers["Origin"]="http://192.168.4.1";assert(dispatch()==ESP_OK && calls==3);
 r.headers["Authorization"]=std::string(200,'x');assert(dispatch()==ESP_FAIL && r.status==401);
 r.headers.clear();r.headers["X-Admin-Key"]="unit-test-secret";s_provisioning=false;
 assert(dispatch()==ESP_FAIL && calls==3);
 puts("Provisioning authentication and origin gates passed");
}
'''
queue_preamble = r'''
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include <cstdint>
'''
queue_globals = r'''
using QueueHandle_t = void*;
static QueueHandle_t s_queue=(void*)1;
static std::atomic<bool> s_connected{false};
static std::atomic<uint32_t> s_generation{7}, s_queue_drops{0};
static std::vector<TelemetryMessage> pending;
constexpr int pdTRUE=1;
/* A producer that waits is a regression, even when the queue is full. */
static int xQueueSend(QueueHandle_t,const TelemetryMessage*m,int timeout) {
 assert(timeout==0);if(pending.size()==4)return 0;pending.push_back(*m);return pdTRUE;
}
'''
queue_main = r'''
/* Simulate offline operation, bounded saturation and oversized messages. */
int main() {
 queue_publish("topic","state",0,0);assert(pending.empty());
 s_connected=true;
 for(int i=0;i<20;++i)queue_publish("topic","state",0,0);
 assert(pending.size()==4 && s_queue_drops==16);
 assert(pending.front().generation==7);
 char large[700];memset(large,'x',sizeof(large)-1);large[699]=0;
 queue_publish("topic",large,0,0);assert(s_queue_drops==17 && pending.size()==4);
 puts("MQTT producer outage/backpressure checks passed");
}
'''
start=telemetry.index('static size_t s_discovery_cursor')
end=telemetry.index('/* Publish one Home Assistant sensor',start)
discovery=telemetry[start:end]
discovery_preamble=queue_preamble+r"""
#include <string>
static bool s_publish_ok=true,fail=true;
static std::vector<std::string> attempts;
/* Simulate a slow broker filling the outbox at the second item. */
static void worker_publish(const char*topic,const char*,int,int){
 attempts.push_back(topic);if(fail&&!strcmp(topic,"b"))s_publish_ok=false;
}
"""
discovery_main=r"""
/* Resume after backpressure instead of repeatedly occupying space with the prefix. */
static void batch(){s_publish_ok=true;s_discovery_index=0;
 discovery_publish("a","payload",1,1);discovery_publish("b","payload",1,1);
 discovery_publish("c","payload",1,1);}
int main(){batch();assert(s_discovery_cursor==1&&attempts.size()==2);
 attempts.clear();fail=false;batch();assert(s_discovery_cursor==3&&attempts.size()==2);
 assert(attempts[0]=="b"&&attempts[1]=="c");attempts.clear();batch();assert(attempts.empty());
 s_discovery_cursor=0;batch();assert(attempts.size()==3);
 puts("Discovery resumes after slow-broker backpressure");}
"""
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    for name, source in [('dispatch', common+functions+main),
                         ('producer', queue_preamble+message+queue_globals+producer+queue_main),
                         ('discovery', discovery_preamble+discovery+discovery_main)]:
        unit=path/(name+'.cpp'); unit.write_text(source)
        binary=path/name
        subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-I'+str(ROOT/'src'),str(unit),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
print('Host boundary checks passed; hardware behavior is not covered.')
