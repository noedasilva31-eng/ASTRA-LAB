# Reprise exacte — ASTRA-V1-brain

Commencer dans cette version, pas depuis ASTRA-V1-paper ou une version antérieure.
Les NEXT_SESSION.md et README.md racine sont des références historiques hashées
par les anciennes gates ; ce fichier et README_BRAIN.md sont les consignes courantes.

## État livré

Le jalon borné initial est terminé : conservation V1e, registre descriptif des coûts,
reconstruction exacte VSOF, rapport automatique, sessions multi-opportunités.
Le brief élargi joint ensuite est implémenté dans astra_brain :

- OpportunityState V1 immuable, namespaces futurs UNKNOWN et MetaState sans social ;
- MarketAgent/regime/scores/EntryArbiter déterministes, explicables et versionnés ;
- PositionState/PositionHealth/ExitArbiter : HOLD, réduction candidate non exécutée,
  sortie candidate, Risk indépendant, aucune clôture forcée ;
- BrainBridge additif : super()._apply reste l'unique chemin qualifié vers le ledger ;
- replay des snapshots/décisions/portefeuille, reprise idempotente et budgets persistants ;
- dataset de session, outcomes observés après toutes les catégories de décisions ;
- latences archivées, SessionFreeze reproductible et contrats Research/Candidate ;
- aucun changement économique, aucune optimisation sur VSOF, aucun ordre réel.

Tests : 25 tests du jalon de mesure + 22 tests Brain ; 386 tests au total dans la
gate complète. Résultat exact de la dernière exécution : validation-summary.json.
Composants protégés : PROTECTED_COMPONENTS.json, comparaison avec ASTRA-V1-live-session.

## Première action

Sur Windows, endpoints Devnet/Mainnet déjà configurés : `validate-all.cmd`.
Qualification du nouveau Brain : fenêtre 180 s, 200 requêtes cumulées, au plus
50 évaluations/plans et 3 cycles. Un journal réel de décisions/vetos/NO_TRADE
rejouable peut qualifier l'observation Brain même sans trade. Aucun événement
observé = NOT_EXECUTED. Ne pas convertir cette qualification en preuve de rentabilité
ou de round-trip ; les compteurs de cycles restent distincts.

Conserver all-validation-*/brain-proofs/ intégralement, son session-dataset.json,
brain-report.json, cycle-report.json et freezes/<hash>/, ainsi que les fichiers
pointés par V1E_PRESERVED_LAST.json. Garder ce ZIP de code avec les freezes : le
replay refuse un code/configuration incompatible. Ne joindre aucun endpoint/secret.

## Si la fenêtre se termine incomplète

Reprendre le même dossier avec :
`py -3 -m astra_brain --directory all-validation-XXXX/brain-proofs --seconds 180 --max-cycles 3`
Les limites, pertes, cash, PENDING_BUY, OPEN_POSITION et PENDING_SELL persistent.
Pas de remise à zéro d'un budget épuisé ni de liquidation fictive. Nouveau dossier
= autre session de validation, jamais une continuation cachée.

## Limites à ne pas masquer

- Windows/Mainnet du nouveau Brain : NOT_EXECUTED dans Work, endpoints absents.
- V1e historique : 137 transactions non examinables sans anciens blocs ; aucun
  défaut démontré. Conservation future prête, events=0 reste insuffisant pour PASS.
- REDUCE_CANDIDATE non exécuté : ledger qualifié supporte seulement vente totale.
- Hard Risk exit est une demande, jamais un passe-droit ; un veto laisse la position.
- Pas de validation statistique des scores/poids ; hypothèses V0 non ajustées à VSOF.
- Dynamic/profit protection complète, graphiques wallets, social et agents non construits.
- Quotes indicatives/réserves ≠ profondeur exécutable garantie. Frais réels inconnus.
- MAE/MFE exécutables et latence d'émission fournisseur inconnus.
- Outcomes de swaps observés ≠ rendements d'une stratégie contrefactuelle exécutée.
- Le chemin Evidence existant reste synchrone ; aucun label HFT n'est revendiqué.

Après des sessions suffisamment riches : évaluation hors échantillon sur freezes,
comparaison baseline/candidate, ablations et coûts/latences ; aucune auto-promotion.
