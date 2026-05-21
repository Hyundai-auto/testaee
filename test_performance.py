#!/usr/bin/env python3
"""
Script para testar performance do endpoint de geração de PIX.
Mede tempo de resposta, throughput e identifica gargalos.
"""

import requests
import time
import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

# Configuração
BASE_URL = "http://localhost:5000"
ENDPOINT = f"{BASE_URL}/proxy/pix"
NUM_REQUESTS = 20
NUM_WORKERS = 5

# Dados de teste
TEST_DATA = {
    "payer_name": "João Silva",
    "payer_cpf": "12345678901",
    "payer_phone": "11999999999",
    "payer_email": "joao@example.com"
}

def make_request(request_id: int) -> Dict:
    """Faz uma requisição e mede o tempo"""
    start_time = time.time()
    
    try:
        response = requests.post(
            ENDPOINT,
            json=TEST_DATA,
            timeout=30
        )
        
        elapsed_time = time.time() - start_time
        
        return {
            'id': request_id,
            'status': response.status_code,
            'time': elapsed_time,
            'success': response.status_code == 200,
            'error': None if response.status_code == 200 else response.text
        }
    except Exception as e:
        elapsed_time = time.time() - start_time
        return {
            'id': request_id,
            'status': 0,
            'time': elapsed_time,
            'success': False,
            'error': str(e)
        }

def test_sequential():
    """Testa requisições sequenciais"""
    print("\n" + "="*60)
    print("🔄 TESTE SEQUENCIAL (1 requisição por vez)")
    print("="*60)
    
    results = []
    for i in range(NUM_REQUESTS):
        result = make_request(i)
        results.append(result)
        status = "✅" if result['success'] else "❌"
        print(f"{status} Requisição {i+1}: {result['time']:.2f}s")
    
    return results

def test_parallel():
    """Testa requisições paralelas"""
    print("\n" + "="*60)
    print(f"⚡ TESTE PARALELO ({NUM_WORKERS} workers simultâneos)")
    print("="*60)
    
    results = []
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = [executor.submit(make_request, i) for i in range(NUM_REQUESTS)]
        
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            results.append(result)
            status = "✅" if result['success'] else "❌"
            print(f"{status} Requisição {result['id']+1}: {result['time']:.2f}s")
    
    return results

def analyze_results(results: List[Dict], test_name: str):
    """Analisa e exibe estatísticas dos resultados"""
    times = [r['time'] for r in results]
    successes = sum(1 for r in results if r['success'])
    failures = len(results) - successes
    
    print("\n" + "-"*60)
    print(f"📊 ESTATÍSTICAS - {test_name}")
    print("-"*60)
    
    print(f"Total de requisições: {len(results)}")
    print(f"Sucessos: {successes} ✅")
    print(f"Falhas: {failures} ❌")
    print(f"Taxa de sucesso: {(successes/len(results)*100):.1f}%")
    
    print(f"\n⏱️  Tempo de Resposta:")
    print(f"  Mínimo: {min(times):.2f}s")
    print(f"  Máximo: {max(times):.2f}s")
    print(f"  Média: {statistics.mean(times):.2f}s")
    print(f"  Mediana: {statistics.median(times):.2f}s")
    if len(times) > 1:
        print(f"  Desvio Padrão: {statistics.stdev(times):.2f}s")
    
    total_time = sum(times)
    print(f"\n📈 Throughput:")
    print(f"  Tempo total: {total_time:.2f}s")
    print(f"  Requisições/segundo: {len(results)/total_time:.2f} req/s")
    
    # Análise de performance
    print(f"\n🎯 Performance:")
    fast = sum(1 for t in times if t < 2)
    medium = sum(1 for t in times if 2 <= t < 4)
    slow = sum(1 for t in times if t >= 4)
    
    print(f"  Rápido (<2s): {fast} ({fast/len(times)*100:.1f}%)")
    print(f"  Médio (2-4s): {medium} ({medium/len(times)*100:.1f}%)")
    print(f"  Lento (>4s): {slow} ({slow/len(times)*100:.1f}%)")

def main():
    """Executa todos os testes"""
    print("\n" + "="*60)
    print("🚀 TESTE DE PERFORMANCE - PIX Generator")
    print("="*60)
    print(f"URL: {ENDPOINT}")
    print(f"Requisições por teste: {NUM_REQUESTS}")
    print(f"Workers paralelos: {NUM_WORKERS}")
    
    # Verificar se servidor está online
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code != 200:
            print("\n❌ Servidor não respondeu ao health check")
            return
        print("\n✅ Servidor está online")
    except Exception as e:
        print(f"\n❌ Erro ao conectar ao servidor: {e}")
        return
    
    # Teste sequencial
    seq_results = test_sequential()
    analyze_results(seq_results, "Sequencial")
    
    # Teste paralelo
    par_results = test_parallel()
    analyze_results(par_results, "Paralelo")
    
    # Comparação
    print("\n" + "="*60)
    print("📊 COMPARAÇÃO")
    print("="*60)
    
    seq_avg = statistics.mean([r['time'] for r in seq_results])
    par_avg = statistics.mean([r['time'] for r in par_results])
    
    print(f"Tempo médio sequencial: {seq_avg:.2f}s")
    print(f"Tempo médio paralelo: {par_avg:.2f}s")
    print(f"Melhoria: {((seq_avg - par_avg) / seq_avg * 100):.1f}%")
    
    seq_throughput = NUM_REQUESTS / sum(r['time'] for r in seq_results)
    par_throughput = NUM_REQUESTS / sum(r['time'] for r in par_results)
    
    print(f"\nThroughput sequencial: {seq_throughput:.2f} req/s")
    print(f"Throughput paralelo: {par_throughput:.2f} req/s")
    print(f"Melhoria: {(par_throughput / seq_throughput):.1f}x")
    
    # Recomendações
    print("\n" + "="*60)
    print("💡 RECOMENDAÇÕES")
    print("="*60)
    
    if seq_avg < 2:
        print("✅ Performance excelente! Tempo < 2s")
    elif seq_avg < 4:
        print("⚠️  Performance aceitável. Tempo 2-4s")
    else:
        print("❌ Performance lenta. Tempo > 4s")
        print("   Considere aumentar timeouts ou otimizar o site externo")
    
    if par_throughput > 5:
        print("✅ Throughput excelente! > 5 req/s")
    elif par_throughput > 2:
        print("⚠️  Throughput aceitável. 2-5 req/s")
    else:
        print("❌ Throughput baixo. < 2 req/s")
        print("   Considere aumentar número de workers")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()
