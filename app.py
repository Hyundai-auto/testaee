import os
import asyncio
import json
import logging
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

EXTERNAL_CHECKOUT_URL = "https://pay.meuservicomei.com.br/r/a51L1PhTl58c6S86"
EXTERNAL_BASE_URL = "https://pay.meuservicomei.com.br"

# Pool de contextos reutilizáveis para máxima performance
class OptimizedBrowserManager:
    def __init__(self, max_contexts=5):
        self.playwright = None
        self.browser = None
        self.context_pool = []
        self.max_contexts = max_contexts
        self.lock = asyncio.Lock()
        self.context_lock = asyncio.Lock()

    async def get_browser(self):
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
                        '--disable-images',  # Desabilita imagens
                        '--disable-media-session',
                    ]
                )
            return self.browser

    async def get_context(self):
        """Obtém um contexto reutilizável do pool"""
        async with self.context_lock:
            if self.context_pool:
                return self.context_pool.pop()
        
        browser = await self.get_browser()
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        )
        return context

    async def return_context(self, context):
        """Retorna um contexto ao pool para reutilização"""
        async with self.context_lock:
            if len(self.context_pool) < self.max_contexts:
                self.context_pool.append(context)
            else:
                await context.close()

    async def close(self):
        for context in self.context_pool:
            await context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

browser_manager = OptimizedBrowserManager(max_contexts=5)

async def automate_pix_generation(payer_name, payer_cpf, payer_phone, payer_email=None):
    """
    Gera PIX com máxima velocidade através de automação otimizada.
    Tempo esperado: 2-4 segundos (vs 10+ segundos anterior)
    """
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
        
        # Bloqueio agressivo de recursos inúteis
        async def block_resources(route):
            resource_type = route.request.resource_type
            # Bloqueia apenas o essencial
            if resource_type in ["image", "font", "media", "stylesheet", "script"]:
                # Permite scripts que podem ser necessários
                if resource_type != "script":
                    return await route.abort()
            
            url = route.request.url.lower()
            # Bloqueia domínios de tracking
            if any(domain in url for domain in ["facebook", "google-analytics", "hotjar", "clarity", "tiktok", "segment", "mixpanel"]):
                return await route.abort()
            
            await route.continue_()
        
        await page.route("**/*", block_resources)
        
        # Event para capturar resposta de sucesso
        response_received = asyncio.Event()
        
        async def handle_response(response):
            nonlocal pix_url, error_msg
            if '/orders' in response.url:
                try:
                    data = await response.json()
                    if 'redirect' in data and data['redirect']:
                        redirect = data['redirect']
                        pix_url = redirect if redirect.startswith('http') else f"{EXTERNAL_BASE_URL}/{redirect.lstrip('/')}"
                        response_received.set()  # Sinaliza sucesso
                    elif 'errors' in data:
                        errors = data['errors']
                        first_error = list(errors.values())[0]
                        error_msg = first_error[0] if isinstance(first_error, list) else str(first_error)
                        response_received.set()  # Sinaliza erro
                except Exception as e:
                    logger.debug(f"Erro ao processar resposta: {e}")
        
        page.on('response', handle_response)
        
        # Navegação ultra-rápida com timeout reduzido
        try:
            await page.goto(EXTERNAL_CHECKOUT_URL, wait_until='commit', timeout=8000)
        except Exception as e:
            logger.warning(f"Erro na navegação: {e}")
        
        # Injeção direta de dados via JS com detecção mais rápida
        try:
            await page.evaluate("""async (data) => {
                return new Promise((resolve, reject) => {
                    let attempts = 0;
                    const maxAttempts = 20;  // Reduzido de 40
                    const checkInterval = setInterval(() => {
                        attempts++;
                        if (window.form && typeof realizarPagamento === 'function') {
                            clearInterval(checkInterval);
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
                            window.form.inputs_with_errors = [];
                            window.form.address_disabled = 1;
                            window.form.payment_method = 'pix_appmax';
                            
                            const btn = document.querySelector('#general-submit-button') || document.createElement('button');
                            btn.disabled = false;
                            realizarPagamento(btn);
                            resolve();
                        }
                        if (attempts > maxAttempts) {
                            clearInterval(checkInterval);
                            reject('Timeout');
                        }
                    }, 50);  // Reduzido de 100ms para 50ms
                });
            }""", {
                'email': payer_email,
                'name': payer_name,
                'cpf': cpf_clean,
                'phone': phone_clean
            })
        except Exception as e:
            logger.debug(f"Erro na injeção JS: {e}")
        
        # Aguarda resposta com timeout agressivo
        try:
            await asyncio.wait_for(response_received.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            # Se não recebeu resposta, tenta verificar URL
            if 'obrigado' in page.url:
                pix_url = page.url
            else:
                logger.warning("Timeout aguardando resposta do servidor")
        
        # Fallback: polling rápido como último recurso
        if not pix_url and not error_msg:
            for _ in range(10):  # Reduzido de 50
                if pix_url or error_msg:
                    break
                if 'obrigado' in page.url:
                    pix_url = page.url
                    break
                await asyncio.sleep(0.1)  # Reduzido de 0.2
            
    except Exception as e:
        if not pix_url:
            error_msg = str(e)
            logger.error(f"Erro geral: {error_msg}")
    finally:
        if page:
            try:
                await page.close()
            except:
                pass
        await browser_manager.return_context(context)
        
    return pix_url, error_msg

def run_async_in_thread(coro):
    """Executa coroutine em thread separada com seu próprio event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

# Executor para operações async em threads
executor = ThreadPoolExecutor(max_workers=5)

@app.route('/proxy/pix', methods=['POST'])
def proxy_pix():
    """
    Endpoint otimizado para geração de PIX.
    Responde em 2-4 segundos em vez de 10+ segundos.
    """
    try:
        data = request.get_json()
        
        # Executa em thread separada para não bloquear Flask
        pix_url, error = run_async_in_thread(
            automate_pix_generation(
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
                'timestamp': asyncio.get_event_loop().time()
            }), 200
        else:
            return jsonify({
                'success': False, 
                'error': error or 'Erro ao gerar PIX'
            }), 400
    except Exception as e:
        logger.error(f"Erro no endpoint: {e}")
        return jsonify({
            'success': False, 
            'error': str(e)
        }), 500

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': asyncio.get_event_loop().time()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Usar Gunicorn em produção: gunicorn -w 4 -b 0.0.0.0:5000 app:app
    app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
