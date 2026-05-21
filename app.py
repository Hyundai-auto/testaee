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
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

EXTERNAL_CHECKOUT_URL = "https://pay.meuservicomei.com.br/r/a51L1PhTl58c6S86"
EXTERNAL_BASE_URL = "https://pay.meuservicomei.com.br"

# Pool de contextos reutilizáveis
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
                    ]
                )
                logger.info("Playwright iniciado com sucesso")
            return self.browser

    async def get_context(self):
        """Obtém um contexto reutilizável do pool"""
        async with self.context_lock:
            if self.context_pool:
                logger.debug("Reutilizando contexto do pool")
                return self.context_pool.pop()
        
        logger.debug("Criando novo contexto")
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
    Gera PIX com captura melhorada de redirecionamento.
    """
    logger.info(f"Iniciando geração de PIX para: {payer_name}")
    
    if not payer_email:
        safe_name = ''.join(c for c in payer_name.lower() if c.isalpha() or c == ' ').replace(' ', '.')
        payer_email = f"{safe_name}@gmail.com"
    
    cpf_clean = ''.join(c for c in payer_cpf if c.isdigit())
    phone_clean = ''.join(c for c in payer_phone if c.isdigit())
    
    logger.debug(f"Email: {payer_email}, CPF: {cpf_clean}, Telefone: {phone_clean}")
    
    context = await browser_manager.get_context()
    page = None
    pix_url = None
    error_msg = None
    
    try:
        page = await context.new_page()
        logger.debug("Página criada")
        
        # Armazenar todas as respostas para análise
        captured_responses = []
        
        # Bloqueio agressivo de recursos inúteis
        async def block_resources(route):
            resource_type = route.request.resource_type
            if resource_type in ["image", "font", "media"]:
                return await route.abort()
            
            url = route.request.url.lower()
            if any(domain in url for domain in ["facebook", "google-analytics", "hotjar", "clarity", "tiktok"]):
                return await route.abort()
            
            await route.continue_()
        
        await page.route("**/*", block_resources)
        logger.debug("Bloqueio de recursos configurado")
        
        # Event para capturar resposta de sucesso
        response_received = asyncio.Event()
        
        async def handle_response(response):
            nonlocal pix_url, error_msg
            
            url = response.url
            logger.debug(f"Resposta recebida: {url}")
            
            # Captura todas as respostas para análise
            if response.status < 400:
                try:
                    captured_responses.append({
                        'url': url,
                        'status': response.status,
                        'timestamp': asyncio.get_event_loop().time()
                    })
                except:
                    pass
            
            # Procura por endpoints de pedido
            if '/orders' in url or '/pagamento' in url or '/checkout' in url:
                logger.info(f"Endpoint de pedido detectado: {url}")
                try:
                    data = await response.json()
                    logger.debug(f"Resposta JSON: {json.dumps(data, indent=2)}")
                    
                    if 'redirect' in data and data['redirect']:
                        redirect = data['redirect']
                        pix_url = redirect if redirect.startswith('http') else f"{EXTERNAL_BASE_URL}/{redirect.lstrip('/')}"
                        logger.info(f"URL de redirecionamento capturada: {pix_url}")
                        response_received.set()
                    elif 'url' in data and data['url']:
                        pix_url = data['url']
                        logger.info(f"URL capturada do campo 'url': {pix_url}")
                        response_received.set()
                    elif 'pix_url' in data and data['pix_url']:
                        pix_url = data['pix_url']
                        logger.info(f"URL capturada do campo 'pix_url': {pix_url}")
                        response_received.set()
                    elif 'errors' in data:
                        errors = data['errors']
                        first_error = list(errors.values())[0]
                        error_msg = first_error[0] if isinstance(first_error, list) else str(first_error)
                        logger.error(f"Erro na resposta: {error_msg}")
                        response_received.set()
                except Exception as e:
                    logger.debug(f"Erro ao processar resposta JSON: {e}")
        
        page.on('response', handle_response)
        logger.debug("Handler de resposta configurado")
        
        # Navegação
        logger.info(f"Navegando para: {EXTERNAL_CHECKOUT_URL}")
        try:
            await page.goto(EXTERNAL_CHECKOUT_URL, wait_until='domcontentloaded', timeout=12000)
            logger.info("Navegação concluída")
        except Exception as e:
            logger.warning(f"Erro na navegação: {e}")
        
        # Aguardar carregamento da página
        await asyncio.sleep(1)
        
        # Injeção direta de dados via JS
        logger.info("Injetando dados do formulário...")
        try:
            result = await page.evaluate("""async (data) => {
                return new Promise((resolve, reject) => {
                    let attempts = 0;
                    const maxAttempts = 30;
                    const checkInterval = setInterval(() => {
                        attempts++;
                        console.log(`Tentativa ${attempts}: procurando window.form`);
                        
                        if (window.form && typeof realizarPagamento === 'function') {
                            console.log('window.form encontrado! Preenchendo dados...');
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
                            
                            console.log('Dados preenchidos. Chamando realizarPagamento...');
                            const btn = document.querySelector('#general-submit-button') || document.createElement('button');
                            btn.disabled = false;
                            realizarPagamento(btn);
                            resolve('Pagamento iniciado');
                        }
                        
                        if (attempts > maxAttempts) {
                            clearInterval(checkInterval);
                            reject('Timeout: window.form não encontrado após ' + maxAttempts + ' tentativas');
                        }
                    }, 100);
                });
            }""", {
                'email': payer_email,
                'name': payer_name,
                'cpf': cpf_clean,
                'phone': phone_clean
            })
            logger.info(f"Injeção JS resultado: {result}")
        except Exception as e:
            logger.warning(f"Erro na injeção JS: {e}")
        
        # Aguardar resposta com timeout aumentado
        logger.info("Aguardando resposta do servidor (timeout: 8s)...")
        try:
            await asyncio.wait_for(response_received.wait(), timeout=8.0)
            logger.info("Resposta recebida com sucesso")
        except asyncio.TimeoutError:
            logger.warning("Timeout aguardando resposta do servidor")
            
            # Fallback 1: Verificar URL da página
            current_url = page.url
            logger.info(f"URL atual da página: {current_url}")
            if 'obrigado' in current_url or 'sucesso' in current_url or 'pix' in current_url:
                pix_url = current_url
                logger.info(f"PIX URL capturada da URL da página: {pix_url}")
            
            # Fallback 2: Procurar por elemento com URL
            try:
                pix_element = await page.query_selector('[data-pix-url], [data-redirect], .pix-url, .redirect-url')
                if pix_element:
                    pix_url = await pix_element.get_attribute('href') or await pix_element.text_content()
                    logger.info(f"PIX URL capturada de elemento: {pix_url}")
            except:
                pass
            
            # Fallback 3: Polling rápido
            if not pix_url:
                logger.info("Tentando polling rápido...")
                for i in range(15):
                    if pix_url or error_msg:
                        break
                    current_url = page.url
                    if 'obrigado' in current_url or 'sucesso' in current_url:
                        pix_url = current_url
                        logger.info(f"PIX URL capturada via polling: {pix_url}")
                        break
                    await asyncio.sleep(0.5)
        
        # Log final
        if pix_url:
            logger.info(f"✅ PIX gerado com sucesso: {pix_url}")
        else:
            logger.error(f"❌ Falha ao gerar PIX. Respostas capturadas: {len(captured_responses)}")
            if captured_responses:
                logger.debug(f"Respostas: {json.dumps(captured_responses, indent=2)}")
            
    except Exception as e:
        if not pix_url:
            error_msg = str(e)
            logger.error(f"❌ Erro geral: {error_msg}")
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
    Endpoint para geração de PIX com logging detalhado.
    """
    try:
        data = request.get_json()
        logger.info(f"Requisição recebida: {data}")
        
        # Executa em thread separada
        pix_url, error = run_async_in_thread(
            automate_pix_generation(
                data.get('payer_name', ''),
                data.get('payer_cpf', ''),
                data.get('payer_phone', ''),
                data.get('payer_email', '')
            )
        )
        
        if pix_url:
            logger.info(f"✅ Retornando PIX URL: {pix_url}")
            return jsonify({
                'success': True, 
                'pixUrl': pix_url,
                'redirectUrl': pix_url
            }), 200
        else:
            logger.error(f"❌ Erro ao gerar PIX: {error}")
            return jsonify({
                'success': False, 
                'error': error or 'Erro ao gerar PIX',
                'message': 'Não foi possível gerar o PIX. Tente novamente.'
            }), 400
    except Exception as e:
        logger.error(f"❌ Erro no endpoint: {e}", exc_info=True)
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
    logger.info(f"Iniciando servidor na porta {port}")
    app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
