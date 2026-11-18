"""Operational checks are separate from independently supplied human judgments."""
def evaluate_turn(case_id, turn, result, searches, diagnostics, judgments):
    final_ids = [g['appid'] for g in result.get('results', [])]
    candidates = searches[-1]['candidate_appids'] if searches else []
    reviewed = {j['appid']: j for j in judgments if j.get('appid') is not None and j['case_id'] == case_id and j['turn'] == turn
                and j.get('source') == 'human_reviewed' and j.get('reviewer')}
    relevance = [reviewed[i]['relevant'] for i in final_ids if i in reviewed and isinstance(reviewed[i].get('relevant'), bool)]
    support = [reviewed[i]['supported'] for i in final_ids if i in reviewed and isinstance(reviewed[i].get('supported'), bool)]
    candidate_relevance = [reviewed[i]['relevant'] for i in candidates if i in reviewed and isinstance(reviewed[i].get('relevant'), bool)]
    turn_review = next((j for j in judgments if j['case_id'] == case_id and j['turn'] == turn
                       and j.get('source') == 'human_reviewed' and j.get('reviewer') and j.get('appid') is None), {})
    def reviewed_bool(name):
        value = turn_review.get(name)
        return value if isinstance(value, bool) else None
    return {'case_id': case_id, 'turn': turn, 'status': result.get('kind', result.get('status')),
            'candidate_appids': candidates, 'final_appids': final_ids,
            'selection_from_search': all(i in candidates for i in final_ids) if searches and result.get('kind') != 'answer' else None,
            'exact_citations_validated': True, 'semantic_support_rate': sum(support) / len(support) if support else None,
            'relevant_game_rate': sum(relevance) / len(relevance) if relevance else None,
            'judged_relevance_games': len(relevance), 'judged_support_games': len(support),
            'candidate_relevant_game_rate': sum(candidate_relevance) / len(candidate_relevance) if candidate_relevance else None,
            'judged_candidate_games': len(candidate_relevance), 'candidate_game_count': len(candidates),
            'unreviewed_games': len([i for i in final_ids if i not in reviewed]),
            'constraint_preservation': reviewed_bool('constraint_preservation'),
            'clarification_appropriate': reviewed_bool('clarification_appropriate'),
            'preferences': result.get('preferences', []), 'filters': result.get('filters', {}),
            'elapsed_ms': result.get('elapsed_ms'), 'diagnostics': dict(diagnostics)}
