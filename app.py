import os
import asyncio
import json
import logging
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor

# Configurar logging detalhado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

EXTERNAL_CHECKOUT_URL = "https://pay.meuservicomei.com.br/r/a51L1PhTl58c6S86"
EXTERNAL_BASE_URL = "https://pay.meuservicomei.com.br"

# Pool de contextos reutilizáveis otimizado
class OptimizedBrowserManager:
    def __init__(self, max_contexts=10):
        self.playwright = None
        self.browser = None
        self.context_pool = asyncio.Queue(maxsize=max_contexts)
        self.max_contexts = max_contexts
        self.lock = asyncio.Lock()
        self.active_contexts = 0

    async def get_browser(self):
        if not self.browser:
            async with self.lock:
                if not self.browser:
                    logger.info("Iniciando Playwright...")
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
                            '--blink-settings=imagesEnabled=false',
                            '--disable-background-networking',
                            '--disable-background-timer-throttling',
                            '--disable-backgrounding-occluded-windows',
                            '--disable-breakpad',
                            '--disable-component-extensions-with-background-pages',
                            '--disable-features=TranslateUI,BlinkGenPropertyTrees',
                            '--disable-ipc-flooding-protection',
                            '--disable-renderer-backgrounding',
                            '--enable-features=NetworkService,NetworkServiceInProcess',
                            '--force-color-profile=srgb',
                            '--metrics-recording-only',
                            '--mute-audio'
                        ]
                    )
                    logger.info("Playwright iniciado com sucesso")
        return self.browser

    async def get_context(self):
        """Obtém um contexto reutilizável do pool"""
        try:
            # Tenta pegar um contexto existente sem bloquear
            context = self.context_pool.get_nowait()
            logger.debug("Reutilizando contexto do pool")
            return context
        except asyncio.QueueEmpty:
            # Se o pool estiver vazio e não atingimos o limite, cria um novo
            async with self.lock:
                if self.active_contexts < self.max_contexts:
                    logger.debug("Criando novo contexto")
                    browser = await self.get_browser()
                    context = await browser.new_context(
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                        bypass_csp=True
                    )
                    self.active_contexts += 1
                    return context
            
            # Se atingimos o limite, aguarda um contexto ficar disponível
            logger.debug("Aguardando contexto do pool")
            return await self.context_pool.get()

    async def return_context(self, context):
        """Retorna um contexto ao pool para reutilização"""
        try:
            # Limpa as páginas do contexto antes de devolver
            for page in context.pages:
                await page.close()
            self.context_pool.put_nowait(context)
        except asyncio.QueueFull:
            await context.close()
            async with self.lock:
                self.active_contexts -= 1

    async def close(self):
        while not self.context_pool.empty():
            context = await self.context_pool.get()
            await context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

browser_manager = OptimizedBrowserManager(max_contexts=10)

async def automate_pix_generation(payer_name, payer_cpf, payer_phone, payer_email=None):
    """
    Gera PIX com captura ultra-rápida de redirecionamento.
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
            if resource_type in ["image", "font", "media", "stylesheet"]:
                return await route.abort()
            
            url = route.request.url.lower()
            if any(domain in url for domain in ["facebook", "google-analytics", "hotjar", "clarity", "tiktok", "pixel"]):
                return await route.abort()
            
            await route.continue_()
        
        await page.route("**/*", block_resources)
        
        # Event para capturar resposta de sucesso
        response_received = asyncio.Event()
        
        async def handle_response(response):
            nonlocal pix_url, error_msg
            
            url = response.url
            
            # Procura por endpoints de pedido
            if '/orders' in url or '/pagamento' in url or '/checkout' in url:
                try:
                    data = await response.json()
                    
                    if 'redirect' in data and data['redirect']:
                        redirect = data['redirect']
                        pix_url = redirect if redirect.startswith('http') else f"{EXTERNAL_BASE_URL}/{redirect.lstrip('/')}"
                        response_received.set()
                    elif 'url' in data and data['url']:
                        pix_url = data['url']
                        response_received.set()
                    elif 'pix_url' in data and data['pix_url']:
                        pix_url = data['pix_url']
                        response_received.set()
                    elif 'errors' in data:
                        errors = data['errors']
                        first_error = list(errors.values())[0]
                        error_msg = first_error[0] if isinstance(first_error, list) else str(first_error)
                        response_received.set()
                except Exception:
                    pass
        
        page.on('response', handle_response)
        
        # Navegação otimizada
        try:
            # Não espera carregar tudo, apenas o commit da navegação
            await page.goto(EXTERNAL_CHECKOUT_URL, wait_until='commit', timeout=10000)
        except Exception as e:
            logger.warning(f"Erro na navegação: {e}")
        
        # Injeção direta de dados via JS - mais agressiva e rápida
        try:
            result = await page.evaluate("""async (data) => {
                return new Promise((resolve, reject) => {
                    let attempts = 0;
                    const maxAttempts = 50; // 5 segundos max
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
                            resolve('Pagamento iniciado');
                        }
                        
                        if (attempts > maxAttempts) {
                            clearInterval(checkInterval);
                            reject('Timeout: window.form não encontrado');
                        }
                    }, 100); // Checa a cada 100ms
                });
            }""", {
                'email': payer_email,
                'name': payer_name,
                'cpf': cpf_clean,
                'phone': phone_clean
            })
        except Exception as e:
            logger.warning(f"Erro na injeção JS: {e}")
        
        # Aguardar resposta com timeout reduzido
        try:
            await asyncio.wait_for(response_received.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            # Fallback 1: Verificar URL da página
            current_url = page.url
            if 'obrigado' in current_url or 'sucesso' in current_url or 'pix' in current_url:
                pix_url = current_url
            
            # Fallback 2: Polling rápido
            if not pix_url:
                for i in range(10): # 2 segundos max
                    if pix_url or error_msg:
                        break
                    current_url = page.url
                    if 'obrigado' in current_url or 'sucesso' in current_url:
                        pix_url = current_url
                        break
                    await asyncio.sleep(0.2)
        
    except Exception as e:
        if not pix_url:
            error_msg = str(e)
    finally:
        if page:
            try:
                await page.close()
            except:
                pass
        await browser_manager.return_context(context)
        
    return pix_url, error_msg

# Loop global para as threads
global_loop = asyncio.new_event_loop()
import threading
def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

thread = threading.Thread(target=start_background_loop, args=(global_loop,), daemon=True)
thread.start()

def run_async_in_thread(coro):
    """Executa coroutine no loop global em background"""
    future = asyncio.run_coroutine_threadsafe(coro, global_loop)
    return future.result()

@app.route('/proxy/pix', methods=['POST'])
def proxy_pix():
    """
    Endpoint para geração de PIX otimizado.
    """
    try:
        data = request.get_json()
        
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
                'redirectUrl': pix_url
            }), 200
        else:
            return jsonify({
                'success': False, 
                'error': error or 'Erro ao gerar PIX',
                'message': 'Não foi possível gerar o PIX. Tente novamente.'
            }), 400
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': str(e),
            'message': 'Erro interno do servidor'
        }), 500

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
