# Recherche, registries et promotion

Spécification V0 ; services de registry et backtester à construire en V2–V4.

## Hypothesis Registry

Objet immuable `hypothesis_id`, `version`, `claim`, `author_agent`, `created_at`, `dataset_version`, `features`, `controls`, `confounders`, `counterexamples`, `test_design`, `train_period`, `validation_period`, `oos_period`, `cost_assumptions`, `results`, `confidence_method`, `confidence`, `status`. `results` et confiance sont des références vers de nouvelles versions, pas des valeurs modifiées sur l'original. Claim précise population, direction, horizon, métrique, baseline et condition de falsification.

Transitions : PROPOSED -> TESTING -> REJECTED ou PROMISING ; PROMISING -> VALIDATED uniquement après protocole OOS concluant ; VALIDATED -> PAPER -> CHALLENGER -> PROMOTED ; RETIRED depuis toute phase devenue obsolète. Une hypothèse rejetée est terminale pour cette version : une reformulation crée une nouvelle version liée. L'événement de transition conserve from/to, preuves, auteur, policy_hash et instant. Les phases shadow et comparaison sont des gates explicites de stratégie avant CHALLENGER/PROMOTED. VALIDATED signifie validation empirique sur le périmètre déclaré, jamais garantie future.

## Experiment Registry

`experiment_id`, `hypothesis_version`, `protocol_hash`, `registered_at`, `trial_family_id`, `trial_index`, `code_hash`, `environment_hash`, `dataset_hash`, `universe_hash`, `feature_versions`, `label_version`, `seeds`, `parameters`, `splits`, `cost_model_hash`, `started_at`, `finished_at`, `metrics`, `artifacts`, `status`, `failure_reason`.

Statuts REGISTERED/RUNNING/COMPLETED/FAILED/INVALIDATED ; un échec technique et un résultat négatif sont conservés. Tous les essais d'une famille comptent, même ceux arrêtés tôt ou proposés par un autre agent. Une duplication exacte du manifest retourne l'expérience existante sauf répétition explicitement préenregistrée. Un run a ses logs, hash de sortie et durée ; les registres ne supposent aucune rentabilité.

## Protocole scientifique

1. Définir observation et question sans faire de sélection sur la future performance.
2. Geler univers de tokens/pools/wallets/KOL admissibles à chaque date, source de découverte et couverture. Inclure décès, illiquidité, transactions échouées et tokens sans prix final.
3. Préenregistrer claim, baseline, métrique primaire, confounders, variantes et famille de tests. Ajouter contre-exemples connus et critère d'abandon.
4. Geler dataset et features. Pour un horizon H, exclure les exemples dont la fenêtre de label chevauche la frontière de split. Embargo choisi selon horizon maximum + latence et dépendances, avant observation des résultats. Aucun scaling ni clustering entraîné sur OOS.
5. Train et validation chronologiques ; group holdout de wallets/clusters/KOL pour les tests de généralisation. Un cluster inféré plus tard ne devient pas une feature ancienne ; peut servir à une analyse de sensibilité explicitement rétrospective.
6. OOS scellé, consulté une fois pour cette famille de décision. Après consultation, toute adaptation utilise un nouvel OOS futur ; l'ancien n'est plus un holdout.
7. Walk-forward avec retraining exclusivement sur passé disponible ; publier résultats de toutes les fenêtres, régimes et cohorts. Block bootstrap par blocs temporels et clusters pour tenir compte de la dépendance, plutôt que traiter tous les trades comme indépendants.
8. Corriger les tests multiples selon procédure préenregistrée (par exemple Holm pour les claims confirmatoires). Rapporter nombre d'essais, effets, intervalles et stabilité, pas seulement p-value ou Sharpe. Taille minimale obtenue par analyse de puissance/effectif effectif ; pas de seuil universel "100 trades suffisent".
9. Sensibilité aux coûts, latence, spread, liquidité et concentration. Ablation de chaque signal ; permutation respectant le temps et contrôles négatifs. Comparer baseline simple et champion sur les mêmes opportunités.
10. Paper puis shadow connecté ; comparer simulation et devis réellement observables. Une sortie impossible n'est pas liquidée au dernier prix connu. Marquer perte/censure selon règle pessimiste préenregistrée, jamais supprimer le trade.
11. Conclusion avec limites, cas adverses et statut ; mémoire conservée ; nouvelle hypothèse si nécessaire.

## Modèle d'exécution V3

Simulator = état de pool point-in-time, taille de trade, fees protocole, base/priority fees, éventuel tip, spread/impact, latence décision-envoi-inclusion et probabilité d'échec conditionnelle. Frais des transactions échouées et coût des tentatives sont comptés. Aucune exécution au prix de clôture qui a servi à calculer le signal. La quote a un TTL ; taille plafonnée par capital et liquidité exécutable. Prendre en compte Token-2022 et restrictions de transfert avant admission d'un token. MEV et congestion évalués par scénarios conservateurs ; ne pas prétendre les reconstituer exactement depuis de simples bougies.

Ledger de cash/positions à double entrée ou réconciliation équivalente ; unités entières et arrondis explicites. La signature identifie la tentative on-chain ; après timeout, rechercher confirmation avant resoumission. Statuts prévus CREATED/RISK_REJECTED/SUBMITTED/UNKNOWN/CONFIRMED/FAILED/EXPIRED/RECONCILED. L'intent et ses tentatives sont distincts. V1a n'implémente aucun de ces ordres.

## Strategy Registry et champion/challenger

Version = hash du code + dataset + features + paramètres + intervalles train/validation/OOS + modèle de coûts + environnement + seed + politique de risque + compatibilité Engine. Chaque résultat cite exactement cette version.

Pipeline : RESEARCH -> CANDIDATE -> HISTORICAL -> ROBUSTNESS -> OOS -> WALK_FORWARD -> PAPER -> SHADOW -> CHALLENGER -> COMPARISON -> PROMOTION_GATE -> CHAMPION. Échec -> REJECTED ; retrait -> RETIRED. Le saut d'étape est refusé. Une phase réussie possède artifacts hashés et verdict du gate versionné. Le statut d'une stratégie ne suffit pas : vérifier les preuves et leur période de validité.

Gate exige conjointement : intégrité et couverture du dataset ; aucune fuite temporelle détectée ; protocole et essais multiples documentés ; résultats OOS conformes aux seuils préenregistrés ; coûts et capacité stressés ; paper/shadow assez longs pour l'effectif et les régimes exigés ; drawdown et concentration sous limites ; qualité d'exécution mesurée ; aucun veto actif ; bundle signé par service autorisé et procédure de rollback exercée. Seuils économiques à calibrer par stratégie et budget de risque AVANT résultats. Aucun seuil ni capital arbitraire fixé ici.

Une promotion est une transaction serializable/check-and-swap sur champion courant, avec attente explicite du hash précédent. Concurrence -> abort/retry de toute la décision, pas écrasement. Retour au champion précédent seulement si encore compatible et admissible ; sinon arrêt nouvelles entrées. Une promotion du champion paper n'autorise pas le live. Gate live distinct en V7 après limites de capital, sécurité signer et validation V6.

## Postmortem

Trigger : perte au-delà du seuil de risque versionné, slippage inattendu, data gap, divergence feed, exécution UNKNOWN ou anomalie. Reconstituer bundle, état de risque, IDs/offsets consommés, timestamps et quotes ; comparer expected/actual. Séparer causes démontrées et conjectures. Toute règle proposée devient une hypothèse avec tests indépendants ; jamais de modification automatique en réaction à une seule perte.
