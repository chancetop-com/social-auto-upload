import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import conf
from patchright.async_api import async_playwright
from utils.local_browser_session import local_browser_session
from utils.local_browser import resolve_local_browser

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers()
        self.wfile.write(b'<!doctype html><title>Isolated profile validation</title><p>Local fixture only</p>')
    def log_message(self, *args): pass

async def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    url = f'http://127.0.0.1:{server.server_port}/'
    results=[]
    try:
        with tempfile.TemporaryDirectory(prefix='sau-browser-smoke-') as root:
            async with async_playwright() as pw:
                sources=[('chrome', ''), ('chromium',''), ('chrome', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'), ('chromium',pw.chromium.executable_path)]
                for kind, path in sources:
                    for headless in [False, True]:
                        with patch.object(conf,'LOCAL_CHROME_PATH',path):
                            config=resolve_local_browser(headless=headless,local_browser=kind)
                            assert config.kind==kind,(path,config)
                            async with local_browser_session(pw,platform='tiktok',account='isolated-smoke',create=True,profile_root=root,configuration=config) as session:
                                expected = Path(root).resolve() / kind / 'tiktok' / 'isolated-smoke'
                                assert expected.is_dir()
                                assert not (expected / '.sau-owner.json').exists()
                                page=await session.context.new_page(); await page.goto(url)
                                token=f'{kind}-{headless}-{bool(path)}'
                                await page.evaluate('(v) => {localStorage.setItem("persist",v); document.cookie="persist="+v+"; max-age=3600; path=/"}',token)
                                anonymous=await session.browser.new_context(no_viewport=True)
                                try:
                                    visitor=await anonymous.new_page(); await visitor.goto(url)
                                    assert await visitor.evaluate('localStorage.getItem("persist")') is None
                                    assert await visitor.evaluate('document.cookie')==''
                                    await visitor.evaluate('localStorage.setItem("anonymous","yes")')
                                    assert await page.evaluate('localStorage.getItem("anonymous")') is None
                                finally:
                                    await anonymous.close()
                                assert await page.title()=='Isolated profile validation'
                                version=session.browser.version
                            async with local_browser_session(pw,platform='tiktok',account='isolated-smoke',profile_root=root,configuration=config) as session:
                                page=await session.context.new_page(); await page.goto(url)
                                assert await page.evaluate('localStorage.getItem("persist")')==token
                                assert await page.evaluate('document.cookie')=='persist='+token
                            record={'kind':kind,'headless':headless,'source':config.source,'version':version,'persistence':True,'anonymous_isolation':True}
                            results.append(record); print(json.dumps(record),flush=True)
    finally:
        server.shutdown(); server.server_close(); worker.join()
    print('PASS',len(results),'configurations')

asyncio.run(main())
