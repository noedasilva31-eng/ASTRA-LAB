# État V1 après ajout V1d

Autorité : gate V1 complet de `docs/TESTING_ACCEPTANCE.md`, contrats de
`docs/DATA_CONTRACTS.md`. Les documents historiques restent inchangés.

| Critère | État et preuve |
|---|---|
| V1b brut/replay/reprise/dédup/quarantaine/backup | Validé Windows/Devnet précédemment par l'utilisateur ; non-régression locale réexécutée |
| V1c chronologie finalisée, erreurs distinctes des sauts, retry, checkpoint | Candidate Windows/Helius Devnet déclarée PASS par l'utilisateur pour `ASTRA-V1c-rpc-v1-fix` |
| Preuve détaillée de ce dernier PASS | Aucun nouveau rapport joint à ce tour ; ne pas confondre `diagnostic_input/` (ancien FAIL) avec le PASS déclaré |
| Baselines gelées | Hashes des 75 fichiers V1c et référence V1b contrôlés automatiquement |
| Décodeur métier natif SOL de premier niveau | Implémenté et testé localement ; qualification réelle V1d et Windows encore manquante |
| Journal dérivé et publication idempotente | Testé localement, arrêts brutaux et nouveau processus compris |
| Dataset local reconstruit depuis le brut | Testé localement, égalité des hashes et rejet de corruption/code divergent |
| Couverture métier | Partielle et mesurée ; inconnus/échecs/erreurs conservés ; pas de couverture complète SPL/DEX/CPI |
| Multi-provider et forks | Reste à faire ; V1c vérifie la cohérence parent/hash d'un feed finalisé, pas une réconciliation indépendante |
| Disponibilité physique, offsets consommés, horloge distribuée | Reste à qualifier ; le test V1b de régression d'horloge reste obligatoire et inchangé |
| Archive distante, rétention et restauration | Reste à faire ; SQLite local seul validé |
| Quotas/coûts, alertes, backpressure, soak 72 h | Reste à faire |
| V1 complète | NON VALIDÉE |

Ordre de reprise : qualifier V1d réel/Windows ; ensuite enrichir la provenance
et le manifest de couverture/disponibilité avant de construire une vue as-of
ou d'élargir les décodeurs métier. Ne pas brancher ces projections à une stratégie.
