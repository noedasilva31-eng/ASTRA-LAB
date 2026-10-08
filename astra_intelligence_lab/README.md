# ASTRA Intelligence Lab — frontière SHADOW V0

Ce package implémente l'infrastructure des phases 0 et 1, deux spécialistes
SHADOW indépendants (`LiquidityAgentV0`, `LaunchAgentV0`) et le recorder
`AgentFusionRecorderV0`. Il fournit contrats, lecture hors réseau, journal Lab
séparé, replay, manifeste, preuve de non-influence et analyses descriptives. Il
n'est importé par aucun composant décisionnel ASTRA.

## Invariants

- Les entrées ASTRA sont lues depuis un dataset canonique ou un
  `SessionFreezeV0`; elles ne sont jamais ouvertes en écriture.
- Le store `lab.sqlite` est distinct, append-only et chaîné par hashes.
- Les actions `BUY`, `SELL`, `HOLD`, `CANDIDATE_BUY` et `EXIT_CANDIDATE` sont
  interdites dans tout `ShadowAnalysisEnvelopeV0`.
- Une valeur `UNKNOWN` est `null`, jamais zéro.
- Les timestamps de connaissance postérieurs au cutoff sont refusés.
- Le replay du store ne réalise aucun appel réseau.
- L'attestation compare archive, ledger, décisions Brain et PositionHealth avant
  et après une exécution Lab. Elle exige une session fermée/checkpointée, afin de
  ne pas ignorer un WAL actif et de ne pas le checkpoint-er implicitement.

## Périmètre explicitement absent

Tout nouvel agent, tout nouveau MarketAgent, tout score global, toute décision,
toute promotion et toute qualification Mainnet sont hors de ce jalon.

## LiquidityAgentV0

`LiquidityAgentV0` calcule seulement des features démontrables depuis les preuves
fournies : réserves, ratio rationnel exact, variations en bps, quote indicative,
âge, compte, span et gap maximal. Les seuils de fraîcheur et d'impact sont des
hypothèses descriptives versionnées et non des seuils ASTRA. La profondeur
exécutable reste `UNKNOWN` sans courbe multi-size archivée. Les réserves ne sont
pas présentées comme une profondeur, une quote comme un fill, ni l'impact provider
comme le slippage payé.

## LaunchAgentV0

`LaunchAgentV0` décrit uniquement le préfixe d'observations disponible au cutoff :
âge observable, rythme d'arrivée, gaps, activité et évolutions de valeurs de
fenêtre lorsque leurs inputs sont présents. Première observation et création de
pool observée ne sont jamais présentées comme le déploiement du token. Les
dimensions bonding/migration/layout restent `UNKNOWN` avec la cause
`BLOCKED_ON_DEPLOYED_LAYOUT_DEFINITION`; le Lab ne modifie ni ne contourne le
décodeur PumpSwap.

## AgentFusionRecorderV0

Le recorder associe uniquement des enveloppes Launch/Liquidity déjà validées qui
partagent exactement pool, mint, événement et cutoff. Il conserve des références
vérifiables par `analysis_id`, provenance, couverture et dimensions manquantes;
il ne duplique pas les payloads des agents. Un agent absent reste `MISSING` et
`UNKNOWN`. Le LabStore exige que toute analyse référencée précède le record de
fusion, puis revérifie ces références pendant le replay hors réseau. Aucun score,
poids, arbitrage ou effet décisionnel n'est produit.

## OutcomeRecordV0

Un outcome est une cible d'évaluation historique postérieure au cutoff d'une
fusion déjà enregistrée. Son horizon est une durée explicite après ce cutoff;
une mesure complète ne peut précéder la fin de cet horizon. `OBSERVED`,
`UNKNOWN`, `NOT_AVAILABLE_YET`, `MISSING` et `INCOMPLETE_COVERAGE` restent des
états distincts. Les valeurs absentes restent nulles et un outcome ne contient
ni décision ni recommandation. L'ajout d'un outcome ne modifie jamais les
enveloppes sources ou leur fusion content-addressée.
Un outcome `OBSERVED` exige une couverture complète, aucune dimension manquante
et une provenance non vide; une couverture incomplète reste explicitement
`INCOMPLETE_COVERAGE`. Les timestamps V0 sont bornés aux entiers signés 64 bits.

Le reader de freeze vérifie le manifeste content-addressed, chaque hash de fichier
et le hash canonique du dataset sans appeler le runtime ASTRA. La reconstruction
métier complète du freeze reste la responsabilité du vérificateur ASTRA existant;
le Lab ne dépend volontairement pas du chemin Brain/Context/Execution.

## Flow / On-chain V0 — spécification préalable

`FlowObservationV0` représente uniquement un fait pseudonyme observé avec temps
d'observation, temps de disponibilité, hashes et provenance. Ce n'est pas un
agent. La spécification complète est dans `FLOW_V0_SPEC.md`. Le prototype
`AstraIntelligenceLabStoreV1` démontre un append incrémental atomique sans migrer
ni remplacer silencieusement le store V0; son audit intégral reste séparé.

`FlowArchiveImporterV0` transforme uniquement les swaps canoniques déjà acceptés
du corpus offline de référence; il laisse `observed_ns` nul car cette horloge
n'est pas démontrée par ces événements. `FlowFreezeManifestV0` embarque le store,
le rapport de couverture et une copie hashée de la source nécessaire à la
vérification autonome et au replay exact par cutoff, sans réseau.
