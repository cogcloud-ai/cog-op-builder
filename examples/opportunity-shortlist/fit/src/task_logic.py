"""Two model judgments become a recommendation under caller-supplied policy."""

def check_input(bundle):
    import cog_core
    if bundle['policy']['review_at'] >= bundle['policy']['pursue_at']:
        return [cog_core.problem('policy-order', 'review_at must be less than pursue_at.')]
    return []

def state(bundle):
    # Thresholds are deliberately withheld: judgment and policy are separate.
    return {'opportunity': bundle['opportunity'], 'company': bundle['company']}

def questions(bundle, declared):
    return declared

def decide(bundle, answers):
    scope = answers['scope_match']['noul']
    capacity = answers['delivery_capacity']['noul']
    score = min(scope, capacity)
    policy = bundle['policy']
    if score >= policy['pursue_at']:
        recommendation = 'pursue'
    elif score >= policy['review_at']:
        recommendation = 'review'
    else:
        recommendation = 'pass'
    return {'opportunity_id': bundle['opportunity']['id'], 'title': bundle['opportunity']['title'],
            'recommendation': recommendation, 'score': score,
            'reasons': [f'Scope match: {scope:.2f}.', f'Delivery capacity: {capacity:.2f}.',
                        f'The lower value is {score:.2f}; pursue at {policy["pursue_at"]:.2f}, review at {policy["review_at"]:.2f}.']}

def check_output(payload, bundle):
    import cog_core
    if payload['decision'] != decide(bundle, payload['answers']):
        return [cog_core.problem('policy-consistency', 'The recommendation must follow the supplied policy and answers.')]
    return []
