"""Author-owned work: validate and pass through a bounded opportunity list."""

def check_input(bundle):
    import cog_core
    problems = []
    ids = [item['id'] for item in bundle['opportunities']]
    if len(ids) != len(set(ids)):
        problems.append(cog_core.problem('duplicate-opportunity', 'Each opportunity must have a different id.'))
    if bundle['policy']['review_at'] >= bundle['policy']['pursue_at']:
        problems.append(cog_core.problem('policy-order', 'review_at must be less than pursue_at.'))
    return problems

def run(bundle, grant, journal):
    return {**bundle, 'authority_use': []}, []

def check_output(payload, bundle):
    import cog_core
    if any(payload.get(key) != bundle[key] for key in ('opportunities', 'company', 'policy')):
        return [cog_core.problem('grounding', 'Prepared inputs must preserve the supplied data.')]
    return []
