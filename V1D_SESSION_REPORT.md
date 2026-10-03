# Résultat de session ASTRA V1d

Baseline V1c candidate : PASS Windows/Helius Devnet déclaré par l'utilisateur.
Les 75 fichiers ont été comparés par SHA-256 dans l'original et la nouvelle
version ; ils restent identiques. Aucun nouveau rapport détaillé de ce PASS
n'était joint. Les rapports historiques de V1c ne sont pas requalifiés.

| Validation exécutée ici (Linux) | Résultat |
|---|---|
| Tests nouveaux V1d | 31/31 PASS |
| Tests blocs V1c | 35/35 PASS |
| Tests dépôt V1b | 38/38 PASS |
| Tests runner V1b | 8/8 PASS |
| Total tests | 112/112 PASS |
| Critères locaux validator V1b | 12/12 PASS |
| Chaîne blocs simulée avec retry | PASS |
| Import/décodage/reprise nouveau processus/dataset hors réseau | PASS |
| Identité baseline V1c et V1b | PASS |
| Contrôles réels Devnet | FAIL : SOLANA_RPC_URL absent ici |
| Qualification de la nouvelle version sous Windows | Non exécutée |
| Verdict global lanceur | FAIL, prérequis réels manquants |

Couverture simulée V1d : 2 blocs importés, 2 transactions traitées, 2 transferts
publiés, 0 pending, 0 erreur hash/replay/FK, intégrité ok. Premier import limité
à 1 bloc, reprise dans un nouveau processus ; publications inchangées après
réimport et double recover. Dataset reconstruit identique hors réseau.
Le hash du dataset figure dans le rapport JSON. Les tests unitaires couvrent
aussi les transactions échouées, instructions non prises en charge, CPI,
adresses chargées v0, u64 maximal, erreurs de structure, corruption, arrêt
brutal, rollback atomique et protection des bases étrangères.

Aucun FAIL fonctionnel local ne subsiste. Les contrôles réels absents restent
FAIL dans le rapport, sans faire passer le verdict global. V1 complète reste
non qualifiée. Les métriques portent sur la fixture et ne sont pas des mesures
de couverture du réseau Devnet.

Rapports complets : `memory_validation_evidence/report.json` et `report.txt`.
Commande : `validate-memory-windows.cmd`. Voir `V1_STATUS.md` pour les critères
restants et `V1D_NEXT_SESSION.md` pour le point de reprise exact.
