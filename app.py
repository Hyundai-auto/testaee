import os
import asyncio
import json
import logging
import time
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from playwright.async_api import async_playwright, Page
from concurrent.futures import ThreadPoolExecutor
from typing import Tuple, Optional

# Configurar logging (apenas erros em produção)
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

EXTERNAL_CHECKOUT_URL = "https://pay.meuservicomei.com.br/r/a51L1PhTl58c6S86"
EXTERNAL_BASE_URL = "https://pay.meuservicomei.com.br"

# ============================================================================
# OTIMIZAÇÃO 1: Pool de Contextos e Páginas Pré-Aquecidas
# ============================================================================
class UltraFastBrowserManager:
    def __init__(self, max_contexts=8, preload=True):
        self.playwright = None
        self.browser = None
        self.context_pool = asyncio.Queue()
        self.page_pool = asyncio.Queue()
        self.max_contexts = max_contexts
        self.lock = asyncio.Lock()
        self.preload = preload

    async def initialize(self):
        """Inicializa o browser e pré-aquece o pool"""
        async with self.lock:
            if not self.browser:
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--no-zygote',
                        '--single-process',
                        '--disable-extensions',
                        '--disable-plugins',
                        '--disable-default-apps',
                        '--disable-sync',
                        '--disable-translate',
                        '--disable-background-networking',
                        '--disable-client-side-phishing-detection',
                        '--disable-default-apps',
                        '--disable-preconnect',
                        '--disable-prerender',
                        '--no-first-run',
                        '--no-default-browser-check',
                    ]
                )
                
                # Pré-aquecer pool
                if self.preload:
                    for _ in range(self.max_contexts):
                        context = await self.browser.new_context(
                            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        )
                        await self.context_pool.put(context)

    async def get_context(self):
        """Obtém contexto do pool (rápido)"""
        try:
            return self.context_pool.get_nowait()
        except asyncio.QueueEmpty:
            context = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            return context

    async def return_context(self, context):
        """Retorna contexto ao pool"""
        if self.context_pool.qsize() < self.max_contexts:
            await self.context_pool.put(context)
        else:
            await context.close()

    async def close(self):
        while not self.context_pool.empty():
            context = await self.context_pool.get()
            await context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

browser_manager = UltraFastBrowserManager(max_contexts=8, preload=True)

# ============================================================================
# OTIMIZAÇÃO 2: Inicializar Browser na Startup
# ============================================================================
@app.before_request
def startup():
    """Inicializa browser na primeira requisição"""
    if not browser_manager.browser:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(browser_manager.initialize())

# ============================================================================
# OTIMIZAÇÃO 3: Automação Ultra-Rápida com Paralelismo
# ============================================================================
async def automate_pix_generation_ultra_fast(
    payer_name: str,
    payer_cpf: str,
    payer_phone: str,
    payer_email: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Geração de PIX ultra-rápida com múltiplas otimizações.
    Tempo esperado: 1-2 segundos
    """
    
    start_time = time.time()
    
    if not payer_email:
        safe_name = ''.join(c for c in payer_name.lower() if c.isalpha() or c == ' ').replace(' ', '.')
        payer_email = f"{safe_name}@gmail.com"
    
    cpf_clean = ''.join(c for c in payer_cpf if c.isdigit())
    phone_clean = ''.join(c for c in payer_phone if c.isdigit())
    
    context = await browser_manager.get_context()
    page = None
    pix_url = None
    error_msg = None
    
    try:
        page = await context.new_page()
        
        # OTIMIZAÇÃO: Bloquear recursos em paralelo
        async def block_resources(route):
            resource_type = route.request.resource_type
            # Bloquear tudo exceto XHR/Fetch/Document
            if resource_type in ["image", "font", "media", "stylesheet", "ping", "websocket"]:
                return await route.abort()
            
            url = route.request.url.lower()
            # Bloquear tracking/ads
            if any(x in url for x in ["analytics", "hotjar", "clarity", "facebook", "tiktok", "ads"]):
                return await route.abort()
            
            await route.continue_()
        
        await page.route("**/*", block_resources)
        
        # OTIMIZAÇÃO: Event para capturar sucesso instantaneamente
        response_event = asyncio.Event()
        pix_data = {'url': None}
        
        async def handle_response(response):
            if pix_data['url']:  # Já capturou
                return
            
            url = response.url
            # Procurar por endpoints de pagamento
            if any(x in url for x in ['/orders', '/pagamento', '/checkout', '/pix', '/payment']):
                try:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Procurar URL em múltiplos campos
                        for field in ['redirect', 'url', 'pix_url', 'payment_url', 'checkout_url']:
                            if field in data and data[field]:
                                pix_data['url'] = data[field]
                                response_event.set()
                                return
                except:
                    pass
        
        page.on('response', handle_response)
        
        # OTIMIZAÇÃO: Navegação paralela com timeout mínimo
        try:
            await page.goto(EXTERNAL_CHECKOUT_URL, wait_until='commit', timeout=5000)
        except:
            pass
        
        # OTIMIZAÇÃO: Injeção JS ultra-rápida
        try:
            await page.evaluate("""(data) => {
                if (window.form && typeof realizarPagamento === 'function') {
                    window.form.email = data.email;
                    window.form.first_name = data.name;
                    window.form.doc = data.cpf;
                    window.form.phone = data.phone;
                    window.form.postal_code = '01310-100';
                    window.form.address_line_1 = 'Avenida Paulista';
                    window.form.address_number = '1000';
                    window.form.address_neighborhood = 'Bela Vista';
                    window.form.city = 'São Paulo';
                    window.form.state = 'SP';
                    window.form.payment_method = 'pix_appmax';
                    
                    const btn = document.querySelector('#general-submit-button');
                    if (btn) btn.disabled = false;
                    realizarPagamento(btn);
                }
            }""", {
                'email': payer_email,
                'name': payer_name,
                'cpf': cpf_clean,
                'phone': phone_clean
            })
        except:
            pass
        
        # OTIMIZAÇÃO: Aguardar resposta com timeout agressivo
        try:
            await asyncio.wait_for(response_event.wait(), timeout=2.0)
            pix_url = pix_data['url']
        except asyncio.TimeoutError:
            # Fallback: Verificar URL atual
            current_url = page.url
            if any(x in current_url for x in ['obrigado', 'sucesso', 'pix', 'confirmacao']):
                pix_url = current_url
        
        # OTIMIZAÇÃO: Polling ultra-rápido como último recurso
        if not pix_url:
            for _ in range(5):
                current_url = page.url
                if any(x in current_url for x in ['obrigado', 'sucesso', 'pix']):
                    pix_url = current_url
                    break
                await asyncio.sleep(0.2)
        
        elapsed = time.time() - start_time
        if pix_url:
            logger.info(f"PIX gerado em {elapsed:.2f}s")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Erro: {error_msg}")
    finally:
        if page:
            try:
                await page.close()
            except:
                pass
        await browser_manager.return_context(context)
    
    return pix_url, error_msg

# ============================================================================
# OTIMIZAÇÃO 4: ThreadPoolExecutor com Workers Otimizados
# ============================================================================
executor = ThreadPoolExecutor(max_workers=10)

def run_async_in_thread(coro):
    """Executa coroutine em thread separada"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

# ============================================================================
# OTIMIZAÇÃO 5: Endpoint com Resposta Rápida
# ============================================================================
@app.route('/proxy/pix', methods=['POST'])
def proxy_pix():
    """Endpoint ultra-rápido para geração de PIX"""
    try:
        data = request.get_json()
        
        # Executar em thread
        pix_url, error = run_async_in_thread(
            automate_pix_generation_ultra_fast(
                data.get('payer_name', ''),
                data.get('payer_cpf', ''),
                data.get('payer_phone', ''),
                data.get('payer_email', '')
            )
        )
        
        if pix_url:
            return jsonify({
                'success': True,
                'pixUrl': pix_url,
                'redirectUrl': pix_url
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': error or 'Erro ao gerar PIX'
            }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
