"""Versioned descriptions only: never post costs to the qualified ledger."""
CATEGORIES=('network','priority','DEX','LP','creator','ATA-create','ATA-close-or-refund','other','price-impact','adverse-movement','paper-slippage')
VERSION='cost-description-v1'

def row(category,amount=None,unit='lamports',source=None,available_at=None,mode='UNKNOWN',included='unknown',key=None,components=()):
    if category not in CATEGORIES:raise ValueError('unknown_cost_category')
    if mode not in ('PROVEN','DERIVED','SIMULATED','UNKNOWN'):raise ValueError('invalid_cost_classification')
    if mode=='UNKNOWN' and amount is not None:raise ValueError('unknown_is_not_zero')
    if mode!='UNKNOWN' and (amount is None or source is None or type(available_at)!=int):raise ValueError('unproven_cost')
    if included not in ('included_in_quote','separate','descriptive_only','unknown'):raise ValueError('invalid_cost_treatment')
    return dict(category=category,amount=amount,unit=unit,source=source,observed_or_simulated=mode,available_at=available_at,model_version=VERSION,included_in_quote_or_separate=included,accounting_key=key,component_keys=list(components))

def separate_total(rows,unit='lamports',as_of=None):
    seen=set();total=0;unknown=False
    for item in rows:
        at=item['available_at']
        if as_of is not None and at is not None and at>as_of:raise ValueError('cost_not_yet_available')
        if item['included_in_quote_or_separate']!='separate':continue
        key=item['accounting_key'];keys={key,*item.get('component_keys',[])}
        if not key or None in keys or keys & seen:raise ValueError('duplicate_or_missing_accounting_key')
        seen.update(keys)
        if item['amount'] is None:unknown=True;continue
        if item['unit']!=unit or type(item['amount'])!=int:raise ValueError('incompatible_cost_units')
        total+=item['amount']
    return None if unknown else total

def leg(intent,fill):
    at=fill['availability_ns'];source={'ledger_id':fill['id']};rows=[row(c) for c in CATEGORIES]
    # Aggregate remains indivisible. Any later allocations MUST share these keys.
    allocations=[fill['id']+':'+c for c in CATEGORIES[:8]]
    rows[CATEGORIES.index('other')]=row('other',fill['fees_model']['fee_quote_raw'],source=source,available_at=at,mode='SIMULATED',included='separate',key=fill['id']+':legacy_fixed_fee',components=allocations)
    q=fill['quote_evidence'];output=fill['base_units'] if intent['side']=='BUY' else fill['quote_received']+fill['fees_model']['fee_quote_raw']
    rows[CATEGORIES.index('paper-slippage')]=row('paper-slippage',q['output_raw']-output,unit=q['output_mint']+':raw',source=q['provenance'],available_at=at,mode='SIMULATED',included='descriptive_only',key=fill['id']+':haircut')
    rows[CATEGORIES.index('paper-slippage')]['already_applied_in_ledger']=True
    rows[CATEGORIES.index('price-impact')]=row('price-impact',q['impact'],unit='provider_fraction',source=q['provenance'],available_at=q['observed_ns'],mode='PROVEN',included='descriptive_only')
    return {'version':VERSION,'rows':rows,'separate_total_lamports':separate_total(rows),'fee_allocation':'UNKNOWN: fixed aggregate; no measured network/priority/DEX/LP/creator/ATA split','double_counting_rule':'Quote-to-fill haircut is already in ledger outputs. Provider impact is descriptive. Neither is subtracted again. Component allocations must share aggregate component_keys.','changes_ledger':False}
