# Contrats des agents — V0, DESIGNED

Aucun agent de recherche n'est en cours d'exécution. Les protocoles Python `DataProvider` et `LLMProvider` sont des interfaces, pas des implémentations de services distants.

## Contrat commun

Task : `task_id`, `role`, `contract_version`, `as_of`, `dataset_id`, `entity_ids`, `hypothesis_id?`, `allowed_tools`, `deadline_at`, `max_tokens`, `max_cost`, `attempt`, `idempotency_key`, `trace_id`. La tâche n'a accès qu'à une vue bornée par son cutoff, pas à une connexion SQL arbitraire. Lectures de labels interdites aux agents produisant des features.

Result : `task_id`, `agent_version`, `provider_id?`, `model_id?`, `prompt_hash?`, `input_hash`, `output_schema_version`, `observations[]`, `claims[]`, `evidence_ids[]`, `counter_evidence_ids[]`, `alternative_explanations[]`, `uncertainties[]`, `proposed_experiments[]`, `tool_call_receipts[]`, `cost`, `started_at`, `finished_at`, `status`. Statuts `SUCCEEDED`, `INSUFFICIENT_EVIDENCE`, `RETRYABLE_FAILURE`, `PERMANENT_FAILURE`. Chaque claim cite les IDs de preuves et son horizon. Aucune écriture dans un état de portefeuille ou une stratégie active.

Orchestration cible : file durable, lease borné et heartbeat ; après expiration du lease, retry avec jitter plafonné, budget total inchangé. Au plus trois tentatives par tâche par défaut, dead-letter queue ensuite. Transaction d'enregistrement du résultat + ACK via outbox. Même idempotency_key + mêmes inputs -> résultat existant ; conflit -> incident. Le calcul LLM peut être non déterministe ; on archive sa sortie et on reproduit ses conséquences avec cette sortie figée, sans promettre une régénération identique.

## Rôles et critères

| Rôle | Entrées point-in-time | Sortie spécialisée | Contrôle / falsification |
|---|---|---|---|
| Scanner | Créations/pools/swaps, inventaire de programmes, couverture | Candidats et anomalies, méthode de sélection | Conserver aussi non-candidats et échecs ; un token découvert n'est pas une recommandation |
| Wallet / Smart Money | Transfers/swaps/funding, prix liquidables, frais, clusters versionnés | PnL réalisé/non réalisé séparé, timing, drawdown, sorties, répétabilité et exposition commune | Neutraliser apports/retraits, marques illiquides et wallets apparentés ; sélection prospective, holdout de clusters |
| KOL / Social | Posts capturés, édition/suppression, reach si disponible, prix et liens de wallets sourcés | Discovery/amplification/following/exit-liquidity comme hypothèses, horizons et rendements résiduels | Baselines momentum/marché, nouveauté, dépendance aux autres comptes, OOS par KOL et période ; association ne prouve pas intention |
| Meta | Entités, lexique versionné, publications et launches | Émergence/accélération/expansion/saturation/déclin avec probabilités calibrables | Lexique découvert au train uniquement ; éviter classification rétrospective avec vocabulaire futur |
| Anti-Rug | Autorités token, extension/permissions, liquidité, deployers, concentration, bundles possibles | Facteurs de risque sourcés et inconnues, pas simple badge sûr/dangereux | Faux positifs, événements non-rug, labels retardés et censure ; calibrage par régime |
| Strategy | Signaux figés et hypothèses | Proposition de règle interprétable et coût de calcul | Ablations, dépendances communes, indépendance économique des signaux |
| Research / Backtest | Protocole préenregistré, dataset gelé, coûts | Résultats et contre-exemples, rapport de biais | Ne peut réécrire protocole après OOS ; variante = nouvel essai comptabilisé |
| Learning | Résultats, erreurs, postmortems, rejets | Nouvelle hypothèse et comparaison ; mémoire des échecs | Aucune modification directe de champion |
| Risk | Expositions, état de feeds, incidents, politiques | Veto/recommandation d'arrêt et justification | Le veto immédiat est déterministe dans Engine ; lever un veto nécessite conditions vérifiées, pas opinion LLM |

## Responsabilités transversales

Data Quality : couverture des slots/programmes, horloges, changements de schéma, missingness et comparaison inter-feeds. Un dataset non conforme n'est pas silencieusement complété avec un provider plus favorable.
Feature Engineering : spécification de lookback, normalisation, unité, latence et coût ; code partagé ou golden tests entre batch et incremental.
Label Engineering : cible économique, horizon, maturité, censure, rug label observé tardivement ; séparation des permissions et namespace.
Execution Analytics : quote vs intent vs fill, taux d'échec et frais même sans fill, prix d'entrée/sortie liquidables et délai de confirmation.
Registry services : versions immuables, liens aux preuves, migrations et audit des transitions.

## Abstraction LLM

Capacités attendues : `reason`, `structured_output`, `tool_call`, `summarize`, `classify`, `research`, `critique`. `capabilities()` ne déclare que celles réellement supportées. `invoke(capability, request, deadline_ms, max_cost)` valide le schéma de sortie et retourne modèle effectif, usage et provenance. Timeout et budget sont appliqués par le worker, pas seulement demandés dans un prompt. Retries ne multiplient pas le plafond global. Fallback seulement vers un provider préautorisé et compatible, avec trace explicite. Réponses mises en cache par modèle/version/prompt/outils/dataset ; jamais par question seule.

Mesurer sur corpus ASTRA : validité JSON, exactitude des citations, abstention, recherche de contre-exemples, coût par hypothèse utile et latence. Le modèle le plus récent n'est pas automatiquement le meilleur pour chaque tâche. Le modèle ne peut ni s'auto-promouvoir ni autoriser une transaction.
