# Tests et critères d'acceptation

## Gate V0 : autorise V1 local, pas le trading

| Critère | Preuve | Verdict |
|---|---|---|
| Cahier des charges lu, conservé et audité | REQUIREMENTS, ARCHITECTURE | PASS revue documentaire |
| Frontières Brain/Engine et permissions | ARCHITECTURE, AGENT_CONTRACTS | PASS conception |
| Décisions justifiées et révisables | 8 ADR | PASS revue documentaire |
| Enveloppe, disponibilité, corrections et finalité | DATA_CONTRACTS, schémas JSON | PASS conception |
| Market Memory et graphe temporel | DATA_CONTRACTS | PASS modèle logique |
| Neuf rôles et responsabilités transversales | AGENT_CONTRACTS | PASS conception |
| Registries, promotion et rollback | REGISTRIES_RESEARCH | PASS conception |
| Biais, protocole et gates | REGISTRIES_RESEARCH, présent document | PASS conception |
| Dépôt concret et vérifications locales | README, tests, reports | PASS local |
| Dépendances et suite explicites | Readiness Report | PASS |

V0 satisfait pour V1a ; PASS documentaire ne signifie ni stratégie VALIDATED ni infrastructure RUNNING. Les migrations de la Market Memory cible et les services de registry restent à construire.

## Tests V1a

Commande : `python3 -m unittest discover -s tests -v` depuis la racine. Bibliothèque standard Python 3.12, sans réseau. Couverture : validation, données tardives, temps inconnu/futur, doublons/conflits, corrections/tombstones, révisions, sources distinctes, ordre de disponibilité, reprise, append-only, backup/restore, clock regression, schémas inconnus, health et snapshots.

Les interruptions sont simulées aux frontières transactionnelles par fermeture/réouverture, pas par perte d'alimentation ou SIGKILL. Les schémas JSON sont vérifiés structurellement, sans certification complète Draft 2020-12. La validation opérationnelle est dans contracts.py et store.py. Les heures fixes des tests sont injectées ; la CLI assigne la réception actuelle.

## Gate V1 complet — non satisfait

Collecteur réel, décodeurs métier, couverture slots/programmes, forks et finalité, rapprochement multi-provider, archive durable avec reprise entre frontières, contrôle d'horloge, backups distants restaurés, quotas/coûts, alertes et soak de 72 h. Reproduire un dataset depuis le brut. Qualifier les instants physiques de disponibilité et conserver les offsets consommés avant toute décision live.

Exiger 100 % des captures ACKées archivées, zéro perte silencieuse, tous conflits comptabilisés, aucune publication en quarantaine et passé inchangé après correction. Seuils de lag/couverture fixés par stratégie avant qualification ; seuil absent = stratégie non admissible.

## Gates suivants

V2 : agents implémentés, corpus d'évaluation, sorties sourcées, budgets appliqués.
V3 : ledger réconcilié, coûts/failed tx/latence/illiquidité testés, shadow traçable.
V4 : tests adverses de leakage, purging/embargo, trial registry, OOS scellé, gate refusant les promotions sans preuves.
V5 : benchmark sur trace commune, parité batch/incremental, stress/backpressure et indépendance LLM.
V6 : signer isolé, kill switch, UNKNOWN/expiry/fork, reprise et reconciliation.
V7 : capital et limites explicitement autorisés après validation, canary et critères d'arrêt. V0 n'autorise aucun trading réel.
