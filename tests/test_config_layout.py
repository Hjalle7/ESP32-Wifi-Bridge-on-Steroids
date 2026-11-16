"""Verify old NVS blobs preserve every legacy field and new profile defaults."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
legacy = subprocess.check_output(['git','show','6554addd41c99334d519df4e99283831798748d4:src/config.h'],cwd=ROOT,text=True)
current = (ROOT/'src/config.h').read_text()


def structure(text, name):
    """Extract the actual POD definition without ESP-IDF-only include files."""
    start=text.index('struct BridgeConfig {')
    end=text.index('\n};',start)+3
    return text[start:end].replace('struct BridgeConfig {','struct '+name+' {',1)


fields=re.findall(r'^\s*(?:char|bool|u?int\d+_t)\s+(\w+)',structure(legacy,'Legacy'),re.M)
checks='\n'.join('static_assert(offsetof(Legacy,'+name+')==offsetof(Current,'+name+'),"'+name+' moved");' for name in fields)
source='#include <cstdint>\n#include <cstddef>\n#include <cstring>\n#include <cassert>\n'+structure(legacy,'Legacy')+'\n'+structure(current,'Current')+'\n'+checks+r'''
static_assert(offsetof(Current,ip_profile)>=sizeof(Legacy),"new field overlaps legacy padding");
/* Model an old NVS blob with deliberately nonzero padding, then overlay it
 * on defaults just as cfg_load does; no old padding may select a profile. */
int main(){Legacy old;memset(&old,0xff,sizeof(old));Current next{};
 memcpy(&next,&old,sizeof(old));assert(next.ip_profile==0);}
'''
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory);(path/'layout.cpp').write_text(source)
    subprocess.run(['g++','-std=c++17',str(path/'layout.cpp'),'-o',str(path/'layout')],check=True)
    subprocess.run([str(path/'layout')],check=True)
print('All legacy NVS field offsets and profile default preservation passed')
