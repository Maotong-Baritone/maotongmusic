import shutil
import subprocess
import unittest
from pathlib import Path
from tests.test_composer_navigation import PRELUDE

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class CatalogSourceTest(unittest.TestCase):
    def run_js(self, code):
        result=subprocess.run(['node','-e',code],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr or result.stdout)

    def test_live_pointer_updates_deletions_and_checks_integrity_without_static_fallback(self):
        self.run_js(r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto');
let bundle={schema_version:1,scores:[{title:'重复曲目'}],logs:[],literature:{documents:[]},lyrics:{'1':{translation:'译文'}}};
let requests=[],broken=false,tamper=false,invalidKey=false;
function bytes(){return new TextEncoder().encode(JSON.stringify(bundle));}
function hash(){return crypto.createHash('sha256').update(bytes()).digest('hex');}
const context={window:{},document:{baseURI:'https://maotong.me/maotongmusic/'},URL,Date,TextDecoder,Uint8Array,crypto:crypto.webcrypto,
 fetch:async(url,options)=>{requests.push({url,options});assert(!url.endsWith('/data.json'));
  if(url.includes('current.json'))return {ok:!broken,json:async()=>({schema_version:1,revision:hash(),key:invalidKey?'../private.json':`website/releases/${hash()}.json`,score_count:bundle.scores.length,document_count:0})};
  return {ok:true,arrayBuffer:async()=>tamper?new TextEncoder().encode('wrong bytes').buffer:bytes().buffer};}};
vm.createContext(context);vm.runInContext(fs.readFileSync('js/catalog-source.js','utf8'),context);
(async()=>{
 const source=context.window.WebsiteCatalog,config={catalogSource:{manifestUrl:'https://scores.maotong.me/website/current.json'}};
 assert.equal(await source.load({}),null);
 assert.equal((await source.load(config)).scores.length,1);
 assert.equal(requests[0].options.cache,'no-store');assert.equal(requests[1].options.cache,'force-cache');
 bundle.scores=[];assert.equal((await source.load(config)).scores.length,0);
 broken=true;await assert.rejects(source.load(config),/暂时无法/);broken=false;
 tamper=true;await assert.rejects(source.load(config),/完整性/);tamper=false;
 invalidKey=true;await assert.rejects(source.load(config),/版本无效/);
})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_score_page_does_not_resurrect_static_records_when_live_source_fails(self):
        self.run_js(PRELUDE+r"""
const calls=[];context.console={...console,error(){}};
context.fetch=async url=>{calls.push(url);return {ok:true,json:async()=>({scoreStorage:{baseUrl:'https://scores.maotong.me'},catalogSource:{manifestUrl:'https://scores.maotong.me/website/current.json'}})};};
context.WebsiteCatalog={load:async()=>{throw Error('temporary live outage');}};
evaluate('musicData=[];changeLog=[];');
(async()=>{await context.loadData();assert.deepEqual(calls,['site-config.json']);assert(element('recentList').innerHTML.includes('temporary live outage'));assert.equal(evaluate('musicData.length'),0);})().catch(e=>{console.error(e);process.exitCode=1;});
""")

if __name__=='__main__':unittest.main()
