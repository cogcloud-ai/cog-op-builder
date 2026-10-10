"""Rank bounded assessments and propose choices; never approve them."""
import hashlib
import json

def check_input(bundle):
    import cog_core
    ids = [item['id'] for item in bundle['opportunities']]
    decisions = [item['decision'] for item in bundle['assessments']]
    assessed = [item['opportunity_id'] for item in decisions]
    if len(ids) != len(set(ids)) or len(assessed) != len(set(assessed)) or set(ids) != set(assessed):
        return [cog_core.problem('assessment-coverage', 'Each opportunity needs exactly one assessment with the same id; no missing, duplicate or extra assessments.')]
    titles = {item['id']: item['title'] for item in bundle['opportunities']}
    if any(item['title'] != titles[item['opportunity_id']] for item in decisions):
        return [cog_core.problem('assessment-title', 'Assessment titles must match the supplied opportunities.')]
    return []

def run(bundle, grant, journal):
    import cog_core
    opportunities = {item['id']: item for item in bundle['opportunities']}
    ranked = sorted((item['decision'] for item in bundle['assessments']), key=lambda item: (-item['score'], item['opportunity_id']))
    changes = []
    for decision in ranked:
        if decision['recommendation'] == 'pass':
            continue
        opportunity = opportunities[decision['opportunity_id']]
        target = hashlib.sha256(json.dumps(opportunity, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        change = {'change_id': opportunity['id'], 'summary': f"{opportunity['title']} — {decision['recommendation']} (score {decision['score']:.2f})",
                  'opportunity': opportunity, 'assessment': decision, 'target_sha256': target}
        change['content_sha256'] = cog_core.change_content_sha256(change)
        changes.append(change)
    return {'ranked': ranked, 'changes': changes, 'authority_use': []}, []

def check_output(payload, bundle):
    import cog_core
    expected, _ = run(bundle, None, None)
    if payload != expected:
        return [cog_core.problem('shortlist-consistency', 'Ranked results and proposed changes must exactly match the supplied assessments.')]
    return []
