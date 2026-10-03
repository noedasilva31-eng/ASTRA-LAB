# Event Envelope, Market Memory et disponibilité

## Deux niveaux distincts

`source-record.schema.json` décrit le record accepté par le connecteur offline V1a. `event-envelope.schema.json` décrit sa publication. La capture brute précède même le parsing JSON. Le fournisseur ne peut fournir ni `observed_at`, ni `processed_at`, ni `available_to_strategy_at` dans ce connecteur. Un champ inconnu entraîne une quarantaine.

| Champ | Sens / contrainte |
|---|---|
| schema_version | Entier 1, évolution incompatible = nouvelle version |
| source, source_id | Fournisseur et identifiant de cette révision ; conflit si même paire et autre contenu |
| logical_id | Identité stable du fait chez ce fournisseur ; pas fusion automatique inter-fournisseurs |
| kind | token_creation, pool, swap, transfer, liquidity, social_post, risk, observation |
| event_time | Unix UTC en microsecondes ; nullable si inconnu ; horloge de la source, pas ordre causal |
| slot, blockhash | Obligatoires on-chain ; null pour offchain ; fixtures explicitement synthétiques |
| commitment | processed, confirmed, finalized, offchain ; ce qui a été observé, pas la finalité connue aujourd'hui |
| revision, supersedes | Révision 0 puis chaîne contiguë pointant vers le source_id précédent |
| retracted | Tombstone versionné, visible uniquement après publication |
| payload | Objet JSON, valeurs monétaires en chaînes décimales ou entiers d'unités minimales ; schémas métier par programme à ajouter avant décodage live |
| observed_at | Horloge ASTRA à réception des octets |
| processed_at | Horloge ASTRA à normalisation ; doit être >= observed_at pour acceptation |
| available_to_strategy_at | Horloge ASTRA de publication durable, après normalisation commitée |
| capture_id | Séquence du journal local ; tie-break stable, à qualifier par journal_id en distribué |
| raw_sha256 | Hash des octets exacts, y compris whitespace et newline |
| normalizer_version | Version du code de normalisation ; nouvelle version = nouveau dataset |

V1a : microsecondes entières, borne SQLite signée. Un `event_time` dépassant la réception de plus de 5 secondes est mis en quarantaine (tolérance initiale à calibrer). Une absence de temps source n'est jamais remplacée par zéro. Les payloads métier restent opaques en V1a : leur véracité économique n'est pas validée.

L'identité canonique on-chain V1b ajoutera cluster/genesis hash, signature, instruction index, inner instruction index, account write version et blockhash. Les changements de commitment sont de nouveaux faits, pas des UPDATE. Les timestamps de publication d'un feed historique ne sont jamais ceux du bloc. Les anciennes normalisations restent consultables.

## Sémantique as-of

Un événement est utilisable à T si publication commitée et `available_to_strategy_at <= T`. La vue as-of ne filtre pas sur le seul event_time. Le replay trie par disponibilité puis séquence. La vue d'état choisit la révision maximale publiée pour chaque `(source, logical_id)` et applique la rétraction après cette sélection. Une révision en quarantaine n'est pas publiée. Les désaccords de fournisseurs restent deux assertions, pas une vérité arbitraire.

Dans la cible distribuée, chaque décision conserve les IDs effectivement consommés, les offsets par partition et le bundle. La disponibilité d'une feature = max(disponibilité de toutes ses dépendances, publication du calcul). Celle d'une jointure inclut les métadonnées et les arêtes de graphe. Une version recalculée aujourd'hui ne remplace pas la feature connue hier. Pour les timestamps exactement égaux, la séquence/offset consommée tranche : un timestamp seul est insuffisant pour reconstruire une décision distribuée.

Deux modes de dataset : `recorded-availability` pour les réceptions effectives ; `counterfactual` pour une simulation d'infrastructure passée avec latence supposée. Ils ne peuvent être mélangés ni présentés comme la même preuve. V1a n'implémente que le premier. Ses fixtures enregistrées maintenant ne constituent aucune preuve historique de marché.

## Archive et reprise locales

Trois tables opérationnelles : raw_capture (octets et réception), normalization (résultat accepté/duplicate/quarantined et document hashé), publication (instant de disponibilité). Triggers interdisant UPDATE et DELETE. Chaque étape commitée avant la suivante ; reprise idempotente des captures sans résultat et publications manquantes. Les doublons gardent leur réception brute mais pas une nouvelle publication. Les rejets restent archivés et nécessitent un nouveau record corrigé ; `recover` ne les blanchit pas.

SQLite n'est pas un stockage WORM contre un administrateur local : celui-ci peut supprimer triggers ou fichiers. Les hashes détectent une altération accidentelle, pas une réécriture coordonnée de données et hashes. V1b exige permissions séparées, rétention objet et manifests ancrés hors du writer. Le backup SQLite est cohérent via l'API backup ; ne pas copier seulement le fichier principal en ignorant WAL.

## Market Memory cible — modèle logique normatif

Chaque table versionnée possède `id`, `version`, `created_at`, `available_at`, `provenance_ids[]`, `content_hash`, `schema_version`. Les versions sont immuables ; liens par clé étrangère ou manifest externe hashé. Valeurs quantitatives avec unité, devise, décimales et convention de signe explicites. Intervalles `[start,end)` UTC.

| Table / famille | Clés, colonnes spécifiques et contraintes |
|---|---|
| entity / entity_revision | entity_id, type, chain, native_id ; unique(type,chain,native_id). Types token/pool/wallet/cluster/deployer/KOL/social_account/narrative/protocol |
| event / event_revision | event_id, source, source_id, logical_id, enveloppe ; captures N:1 révision ; publication obligatoire pour toute lecture stratégie |
| graph_edge_revision | edge_id, from_entity, to_entity, relation, confidence_method, weight, valid_from/to, available_at, evidence_ids, alternative_explanations ; aucun merge irréversible de wallets |
| observation / signal | author, claim, entity_ids, input_event_ids, feature_versions, horizon, expiration, confidence_method, limitations |
| hypothesis | claim, controls, confounders, counterexamples, protocol_id ; spec détaillée dans REGISTRIES |
| evidence / counter_evidence | hypothesis_id, source_ids, dataset_id, method, direction, strength, uncertainty ; aucune suppression des échecs |
| confidence_history | hypothesis_id, method_version, sample_size, interval, calibration, computed_at ; séparer jugement LLM et mesure |
| feature_definition / feature_value | name, version, code_hash, units, inputs, lookback, missingness_rule ; value, entity_id, knowledge_cutoff, publication |
| label_definition / label_value | horizon, maturity_at, target, censoring_rule ; interdiction lecture dans namespace features |
| dataset_manifest | hashes des partitions et captures, univers/couverture, schémas, normalizers, mode, cutoff, seeds, code/environment hashes |
| experiment / backtest / OOS | hypothèse/version, préenregistrement, splits, coûts, trial_family, paramètres, résultats et statut |
| strategy_version / promotion / rollback | immutable bundle hash, inputs, experiments, gate policy hash ; événements d'activation atomiques |
| trade_candidate / decision / rejection | decision_id, bundle_hash, input_ids, offsets, risk_state, reasons ; rejets conservés |
| order_intent / attempt / fill | client_order_id, signature, state, quote_age, expected/actual execution, fees, slippage, reconciliation_id |
| position / pnl / drawdown | projections dérivées du ledger de fills et flux ; mark source, timestamp et liquidabilité explicites |
| error / postmortem | incident_id, décision reconstruite, causes possibles, counterfactuals, nouvelle hypothèse ; jamais nouvelle règle immédiate |

Index cibles : `(available_at,id)`, `(entity_id,event_time)`, `(source,source_id)`, `(logical_id,version)`, `(hypothesis_id,created_at)`, arêtes `(from_entity,relation,available_at)` et inverse. Partitionner les gros événements par date de réception, pas seulement par date de bloc ; vérifier les requêtes réelles avant ajout d'index. Un graphe dédié n'est pas nécessaire au démarrage.

Rétention proposée : brut on-chain au moins 90 jours chauds puis archive froide selon budget ; métadonnées, preuves et manifests pour la durée du projet. Les conditions d'accès et de conservation sociales peuvent exiger effacement : garder provenance/hash et tombstone selon droits, invalider les datasets dont les sources ne sont plus redistribuables. Cette politique doit être arrêtée avant collecte sociale, pas présumée autorisée.

## Limite de précision du prototype local

Le timestamp de publication V1a est pris dans la transaction juste avant commit : c'est une heure logique, pas la mesure de l'instant physique où un autre processus peut lire le commit. Une reconstruction à la microseconde dans cette fenêtre peut donc être trop optimiste. Les tests prouvent l'ordre logique, pas cette précision physique. Avant un Engine connecté, capturer à sa réception l'instant et l'offset réellement consommés et conserver les inputs de chaque décision. Le replay fidèle repose sur ce reçu ; les bornes de disponibilité distribuée doivent être qualifiées séparément. Ce risque bloque l'affirmation « connaissance exacte à toute heure murale T » en production, sans bloquer V1a offline.
