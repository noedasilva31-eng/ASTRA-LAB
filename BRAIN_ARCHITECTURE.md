# ASTRA Live Brain V0 — portée et architecture livrées

## Chemin rapide

Observer qualifié → événement PumpSwap archivé → plan Evidence qualifié →
OpportunityState V1 → MarketAgentV0 → MarketRegimeV0 → scores → EntryArbiter /
PositionState + PositionHealth + ExitArbiter → candidature → Evidence/Risk du
Bridge qualifié → intention paper → quote ultérieure + Risk → règlement paper.

`BrainBridge` est une sous-classe additive dans astra_brain/runtime.py. Elle
n'édite ni Observer, ni Evidence, ni Risk, ni Bridge, ni le ledger. Elle peut
retenir une proposition du Bridge (`NO_TRADE`, `HOLD`, réduction non exécutée).
Elle ne possède aucune méthode d'envoi de transaction et ne peut pas autoriser
un fill refusé par le chemin qualifié. Son replay dédié reproduit les snapshots
et les décisions dans un ledger temporaire, puis compare tout le portefeuille.
Le replay classique et les archives VSOF restent inchangés.

Le collecteur existant acquiert les preuves avant ce nouveau filtre de stratégie.
Cela conserve ses garanties, mais son HTTP synchrone et les quotes restent le
principal coût du chemin. Ce V0 n'est pas présenté comme un moteur HFT. Les calculs
Brain portent sur une fenêtre bornée de 64 événements d'un pool ; aucun LLM,
export, freeze ou calcul Research dans une décision. Les audits et exports sont
faits après la session, sous le verrou du writer.

## Contrats et sources

| Élément | Implémentation et limites |
| --- | --- |
| OpportunityState V1 | Identity, clock, market, execution, evidence, risk, coverage, provenance, market_agent, scores, regime, decision_context. Valeurs critiques enveloppées avec available_at, source, provenance, slot, unité, freshness et classification. |
| Interfaces futures | Wallet, holders, graph, launch, bundle, deployer, rug, social et meta versionnés, explicitement UNKNOWN. Pas de services externes ni valeurs simulées présentées comme observations. |
| MetaStateV0 | Contrat compact pour meta_id/strength/velocity/acceleration/age/crowding/rotation/confidence. Aucun calcul social ou narratif actuel. |
| MarketAgentV0 | Prix swap observé, variation/momentum, différence de momentum par intervalle observé, flow BUY/SELL, imbalance, volume, vitesses et accélération sur le temps de réception, nombre de swaps, volatilité descriptive en variation absolue moyenne. Quotes, impact et réserves issus des preuves validées. |
| Limites marché | Activité du sous-ensemble reçu, pas volume complet de la chaîne. Âge seulement si création présente. Profondeur exécutable complète, attribution de rotation et changements structurels non prouvés restent UNKNOWN. Réserves ≠ profondeur garantie. |
| MarketRegimeV0 | LOW_ACTIVITY/NORMAL/HIGH_ACTIVITY, HIGH_VOLATILITY, LIQUIDITY_STRESS, ACCELERATING/DECELERATING/STABLE, ROTATION_UNKNOWN. Raisons et entrées conservées ; aucune probabilité calibrée inventée. |
| Scores | MarketScoreV0, ExecutionScoreV0, DataQualityScoreV0, OpportunityScoreV0. Raw, normalisation, poids, contribution, formule, version, as_of, provenance, données manquantes. Fractions/entiers déterministes. |
| EntryArbiterV0 | Nombre minimal d'observations, momentum positif, flow non négatif, données requises fraîches, score seuil, régime non fortement volatil. CANDIDATE_BUY ou NO_TRADE explicite. Ces conditions sont des hypothèses V0, pas des règles rentables démontrées. |
| PositionState | Snapshot et thèse d'entrée, scores, quote, taille/coût, durée, évolution du marché/régime/liquidité, marque paper conditionnelle si quote de taille exacte disponible après entrée. |
| PositionHealth | Score explicable marché/liquidité, raisons invalidées conservées. Une baisse isolée n'impose pas une sortie. |
| ExitArbiterV0 | HOLD ; EXIT_CANDIDATE sur invalidations conjointes, demande hard Risk ou horizon maximal ; REDUCE_CANDIDATE lors d'une dégradation de liquidité isolée. |
| Réduction | Le ledger qualifié ne supporte que la vente totale. REDUCE_CANDIDATE est journalisé et non exécuté ; jamais converti en vente totale ou fill partiel inventé. |
| Hard Risk exit | Demande de sortie, pas autorisation de contourner Risk. Si Risk refuse l'intention ou le règlement SELL, la position reste ouverte avec le veto. |
| Protection dynamique / cible profit | Non implémentées comme règles d'exécution V0, faute de trajectoire exécutable suffisamment couverte. Pas d'extrapolation depuis quelques prix. |

## Sessions et reprise

Le scheduler additif astra_multicycle pilote BrainBridge : discovery → évaluation
→ rejet/NO_TRADE ou intention → suivi du pool → position/HOLD/sortie → discovery.
Bornes par défaut de la gate Brain : 180 s, 50 plans/opportunités évaluées au plus,
3 cycles au plus, 200 tentatives RPC/quotes cumulées. Le décompte comprend les
observations de suivi, pas seulement les nouvelles entrées. Les limites et hashes
sont archivés et immuables après reprise. Les règles d'exposition et de perte
proviennent du même Risk/ledger qualifié. Fin de fenêtre ≠ liquidation.

Snapshots archivés avant l'écriture au ledger. Reprise : préfixe du ledger utilisé
au temps de décision, même état/temps source, même hash de snapshot ; les résultats
et les fills sont idempotents. Un changement de code/configuration dans une session
est refusé. Une session classique ne peut pas être convertie implicitement en
session Brain déjà négociée : un dossier dédié est requis.

## Dataset, outcomes et Research

`session-dataset.json` conserve configurations et hashes, snapshots, résultats,
positions/pending, cycles/coûts, couverture, observations, latences et outcomes.
Les horizons +5/+15/+30/+60/+300 s utilisent le premier prix de swap réellement
observé après l'échéance. Sans marque, UNKNOWN. Ces rendements ne sont ni des
prix de liquidation ni des fills contrefactuels. Ils couvrent aussi REJECT,
NO_TRADE et HOLD ; une opportunité jamais vue ne devient jamais un faux négatif.

`SessionFreezeV0` contient dataset canonique, SQLite nécessaires et manifeste de
hashes. Son identifiant dérive du contenu ; une deuxième construction identique
redonne le même identifiant. Vérification : hashes puis reconstruction hors réseau
et comparaison du dataset. Toute modification de fichier est détectée.
Immutabilité par contrat et hashes, pas prétention à un stockage matériel WORM.

`astra_brain.research` fournit BrainCandidateV0 et BrainComparisonV0 : ADD/MODIFY/
REDUCE/REMOVE, baseline, hypothèse, source freeze, étapes replay/backtest/
falsification/stress/walk-forward/paper challenger/comparaison. Toutes restent
NOT_EXECUTED tant que des évaluateurs ne les ont pas réalisées. Aucun agent ni API
de promotion LIVE n'est créé. Les interfaces d'ablation sont des contrats ; aucun
backtest ou gain hors échantillon n'est revendiqué.

## Coûts et mesures

Le forfait historique reste 0,0021 SOL par jambe. COST_MODEL.md décrit sa nature
simulée, le registre et la protection contre le double comptage. La régression
VSOF conserve exactement le scénario historique, pas une cible d'optimisation.
MAE/MFE exécutables : UNKNOWN. Les extrêmes de quelques swaps ne les remplacent pas.

Mesures monotones archivées : Observer decode/features/commit ; acquisition et
validation Evidence ; MarketAgent ; régime ; scoring ; état ; EntryArbiter ;
PositionHealth/Exit combinés ; chemins qualifiés intention/règlement combinés.
Dataset : p50, p95 à partir de 20 observations et p99 à partir de 100. Sinon null
avec limite explicite. Le temps d'émission fournisseur et le coût isolé du second
Risk interne au ledger ne sont pas inventés. Les horodatages d'arrivée bruts restent
la référence de disponibilité ; ils ne prouvent pas une latence réseau aller simple.

Les min/max des prix de swaps reçus après l'entrée sont conservés séparément dans
PositionState, avec les IDs des événements et la couverture de la fenêtre retenue.
Ils ne deviennent pas des MAE/MFE exécutables. Les paramètres réservés
protection_drawdown_bps et min_coverage_samples ne déclenchent actuellement aucune
règle supplémentaire : protection dynamique complète et calibration de couverture
restent à établir, pas à présenter comme déjà actives.

La prochaine grosse brique recommandée est un évaluateur hors ligne de freezes
appariés, avec ablations, validation hors échantillon et coûts explicitement
incertains. Elle vient après accumulation de sessions réelles suffisamment riches,
notamment NO_TRADE/HOLD/rejets et positions ouvertes. Pas d'auto-promotion LIVE.
