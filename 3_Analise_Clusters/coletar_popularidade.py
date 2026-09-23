"""Coleta contagens de avaliacoes por genero, com cache e limite de requisicoes.

Fonte: https://steamspy.com/api.php (positive + negative).
Execute este arquivo para completar/retomar o cache; use --atualizar para renova-lo.
"""

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


RAIZ = Path(__file__).resolve().parents[1]
CACHE = RAIZ / '_DadosLimpos' / 'popularidade_steamspy.json'


def coletar(atualizar=False):
    with (RAIZ / '_DadosLimpos' / 'jogos_steam.csv').open(encoding='utf-8', newline='') as arquivo:
        jogos = list(csv.DictReader(arquivo))
    ids = {int(jogo['appid']) for jogo in jogos}
    generos = sorted({g.strip() for jogo in jogos for g in jogo['genres'].split(';') if g.strip()})
    dados = {'fonte': 'https://steamspy.com/api.php', 'metrica': 'positive + negative',
             'consultas': {}, 'jogos': {}}
    if CACHE.exists() and not atualizar:
        dados = json.loads(CACHE.read_text(encoding='utf-8'))
    for genero in generos:
        if genero in dados['consultas']:
            continue
        url = 'https://steamspy.com/api.php?' + urlencode({'request': 'genre', 'genre': genero})
        for tentativa in range(3):
            try:
                with urlopen(url, timeout=60) as resposta:
                    resultado = json.load(resposta)
                if not isinstance(resultado, (dict, list)) or (isinstance(resultado, list) and resultado):
                    raise ValueError('Resposta inesperada da API')
                break
            except (HTTPError, URLError, TimeoutError, ValueError):
                if tentativa == 2:
                    raise
                time.sleep(10 * (tentativa + 1))
        agora = datetime.now(timezone.utc).isoformat()
        registros = resultado.values() if isinstance(resultado, dict) else []
        encontrados = 0
        for jogo in registros:
            appid = int(jogo['appid'])
            if appid not in ids or appid == 999999:
                continue
            positivo, negativo = jogo.get('positive'), jogo.get('negative')
            if not isinstance(positivo, int) or not isinstance(negativo, int) or min(positivo, negativo) < 0:
                continue  # Dado ausente nao equivale a zero avaliacoes.
            dados['jogos'][str(appid)] = {
                'appid': appid, 'positive': positivo, 'negative': negativo,
                'total_avaliacoes': positivo + negativo, 'coletado_em_utc': agora,
            }
            encontrados += 1
        dados['consultas'][genero] = {'url': url, 'coletado_em_utc': agora,
                                     'jogos_no_csv': encontrados}
        temporario = CACHE.with_suffix('.tmp')
        temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding='utf-8')
        temporario.replace(CACHE)
        print(f'{genero}: {encontrados} jogos encontrados no CSV', flush=True)
        time.sleep(1.1)  # Documentacao: no maximo uma consulta por segundo.
    # Completa lacunas das categorias pequenas diretamente na Steam.
    por_genero = defaultdict(set)
    for jogo in jogos:
        for genero in jogo['genres'].split(';'):
            if genero.strip():
                por_genero[genero.strip()].add(int(jogo['appid']))
    pequenos = set().union(*(apps for apps in por_genero.values() if len(apps) <= 100))
    faltantes = sorted(pequenos - set(map(int, dados['jogos'])))
    print(f'Complemento Steam: {len(faltantes)} consultas em categorias pequenas.', flush=True)
    for indice, appid in enumerate(faltantes, 1):
        params = {'json': 1, 'filter': 'all', 'language': 'all', 'review_type': 'all',
                  'purchase_type': 'all', 'num_per_page': 1, 'filter_offtopic_activity': 0}
        url = f'https://store.steampowered.com/appreviews/{appid}?' + urlencode(params)
        for tentativa in range(3):
            try:
                with urlopen(url, timeout=45) as resposta:
                    resultado = json.load(resposta)
                resumo = resultado.get('query_summary', {})
                if resultado.get('success') != 1 or 'total_reviews' not in resumo:
                    raise ValueError(f'Steam nao retornou contagem para {appid}')
                break
            except (HTTPError, URLError, TimeoutError, ValueError):
                if tentativa == 2:
                    raise
                time.sleep(10 * (tentativa + 1))
        dados['jogos'][str(appid)] = {
            'appid': appid, 'positive': resumo['total_positive'],
            'negative': resumo['total_negative'], 'total_avaliacoes': resumo['total_reviews'],
            'coletado_em_utc': datetime.now(timezone.utc).isoformat(), 'fonte': url,
        }
        temporario = CACHE.with_suffix('.tmp')
        temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding='utf-8')
        temporario.replace(CACHE)
        print(f'Steam {indice}/{len(faltantes)}: {appid} = {resumo["total_reviews"]} avaliacoes', flush=True)
        time.sleep(1.1)
    print(f'Cache: {CACHE}; {len(dados["jogos"])} jogos com contagens.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--atualizar', action='store_true')
    coletar(parser.parse_args().atualizar)
