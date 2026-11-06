"""Evaluation with explicit judgments: drafts are not human-reviewed labels."""
import math
import statistics
import re
from .filters import canonical

def validate_judgments(rows, pool, confirm_human=False):
    source = {(r['query_id'], r['appid']): r for r in pool}
    seen = set()
    for row in rows:
        if type(row.get('appid')) is not int or not isinstance(row.get('query_id'), str):
            raise ValueError('Judgments require an integer appid and a string query_id.')
        key = row['query_id'], row['appid']
        if key not in source or key in seen: raise ValueError(f'Unknown or duplicate query/game pair: {key}')
        seen.add(key)
        grade = row.get('grade')
        if grade is not None and (type(grade) is not int or grade not in (0, 1, 2)): raise ValueError('grade must be 0, 1, 2, or null.')
        if row.get('status') not in {'agent_draft', 'human_reviewed'}: raise ValueError('Invalid judgment provenance.')
        if row['status'] == 'human_reviewed' and not confirm_human: raise ValueError('Use --confirm-human-review only after explicit human review.')
        if not isinstance(row.get('reason'), str) or not row['reason'].strip(): raise ValueError('Every judgment needs a reason.')
        if grade is not None:
            evidence = row.get('evidence', {})
            field, quote = evidence.get('field'), evidence.get('quote')
            if field not in {'name', 'description', 'genres', 'user_tags'} or not isinstance(quote, str) or not quote.strip(): raise ValueError('Catalog evidence is required.')
            text = source[key][field]
            if isinstance(text, list):
                if quote not in text: raise ValueError('Evidence label is missing from the catalog.')
            elif quote not in text: raise ValueError('Evidence is not a verbatim catalog excerpt.')
    return rows

def draft_judgment(candidate, query):
    row = {'query_id': candidate['query_id'], 'appid': candidate['appid'], 'grade': None, 'status': 'agent_draft', 'draft_method': 'needs_semantic_review', 'reason': 'Semantic relevance needs review; missing query words do not imply irrelevance.', 'evidence': None}
    if query['category'] == 'exact_title':
        def title_key(text):
            return re.sub(r'[^\w]+', '', canonical(text.translate(str.maketrans('', '', '®™©'))))
        name, q = title_key(candidate['name']), title_key(query['q'])
        grade = 2 if name == q else 1 if q in name else 0
        row.update(grade=grade, draft_method='exact_title_rule', reason='The stated intent is an exact title lookup; title variants are partially relevant. This draft rule still needs human review.', evidence={'field': 'name', 'quote': candidate['name']})
    elif query.get('no_interpretable_intent'):
        row.update(grade=0, draft_method='no_intent_rule', reason='This synthetic query has no interpretable intent and should not produce a relevant recommendation.', evidence={'field': 'name', 'quote': candidate['name']})
    elif query.get('intent_tags'):
        labels = {canonical(t): t for t in candidate['user_tags']}
        if all(canonical(t) in labels for t in query['intent_tags']):
            row.update(grade=2, draft_method='explicit_tag_rule', reason='Catalog tags cover the explicit query aspects. This rule-based draft is not human review or proof of complete relevance.', evidence={'field': 'user_tags', 'quote': labels[canonical(query['intent_tags'][0])]})
    return row

def dcg(grades):
    return sum((2**grade - 1) / math.log2(position + 2) for position, grade in enumerate(grades))

def evaluate(queries, pool, rankings, judgments, status, split):
    grades = {(r['query_id'], r['appid']): r['grade'] for r in judgments if r['status'] == status and r['grade'] is not None}
    methods = list(rankings['methods'])
    per_method = {mode: {'precision_at_5': [], 'ndcg_at_10': [], 'no_match_returned_games': 0} for mode in methods}
    evaluated, incomplete, no_relevant, categories = [], [], [], {}
    selected = [q for q in queries if q['split'] == split]
    for query in selected:
        qid = query['id']
        candidates = {r['appid'] for r in pool if r['query_id'] == qid}
        if any((qid, appid) not in grades for appid in candidates):
            incomplete.append(qid); continue
        ideal = sorted((grades[qid, a] for a in candidates), reverse=True)[:10]
        idcg = dcg(ideal)
        evaluated.append(qid)
        categories[query['category']] = categories.get(query['category'], 0) + 1
        if not idcg: no_relevant.append(qid)
        for mode in methods:
            ids = rankings['methods'][mode][qid]
            values = [grades[qid, a] for a in ids]
            if idcg:
                per_method[mode]['precision_at_5'].append(sum(g > 0 for g in values[:5]) / 5)
                per_method[mode]['ndcg_at_10'].append(dcg(values[:10]) / idcg)
            if query.get('no_interpretable_intent'):
                per_method[mode]['no_match_returned_games'] += len(ids)
    for mode, metrics in per_method.items():
        for key in ('precision_at_5', 'ndcg_at_10'):
            metrics[key] = statistics.mean(metrics[key]) if metrics[key] else None
        latency = sorted(rankings['latency_seconds'][mode])
        metrics['warm_p95_seconds'] = latency[max(0, math.ceil(len(latency) * .95) - 1)] if latency else None
        metrics['constraint_violations'] = rankings['constraint_violations'][mode]
    pairs = {(r['query_id'], r['appid']) for r in pool if any(q['id'] == r['query_id'] for q in selected)}
    return {'split': split, 'label_source': status, 'exploratory': status != 'human_reviewed', 'quality_improvement_claimed': False, 'judgment_coverage': sum(k in grades for k in pairs) / len(pairs) if pairs else 1.0, 'fully_judged_queries': evaluated, 'incomplete_queries': incomplete, 'no_relevant_judgments': no_relevant, 'evaluated_categories': categories, 'methods': per_method, 'note': 'Comparable metrics use the same fully judged query subset. IDCG=0 is excluded from relevance averages. Recall is not estimated from pooled judgments.'}
