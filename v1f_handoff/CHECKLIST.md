# Validation V1f

| Suite locale Linux | Résultat |
|---|---|
| Dépôt V1b | 38/38 PASS |
| Runner V1b | 8/8 PASS |
| V1c | 35/35 PASS |
| V1d | 31/31 PASS |
| V1e | 28/28 PASS |
| Encodage Windows et lanceur | 7/7 PASS |
| Quotas locaux isolés | 12/12 PASS |
| Total | 159/159 PASS |
| Critères locaux V1b | 12/12 PASS |
| Contrôles réels | FAIL : endpoint absent ici |
| Exécution Windows de cette version | NON EXÉCUTÉE |
| Verdict global | FAIL ; local_overall PASS |

Le rapport Windows V1e reçu est conservé dans windows_v1e_failure/. Il contient
un FAIL UnicodeDecodeError ciblé. Les rapports actuels ne le requalifient pas en
PASS Windows : le correctif est testé localement avec simulation CP1252.

Les 98 fichiers de référence V1d sont inchangés. Parmi les 117 fichiers V1e,
seul provenance_validation/run.py change : encodage explicite et localisation
d'erreur. Les données métier, règles de finalité, provenance, hashes et code de
reconstruction ne changent pas. CHANGESET.json donne les empreintes avant/après.

Les quotas sont une nouvelle primitive locale, non branchée au RPC : plafonds
persistants, réservation atomique, refus après dépassement, doublon sans nouvelle
autorisation, règlement idempotent, consommation inconnue conservée après crash,
corruption bloquante, snapshots reconstruits. Aucun contrôle effectif des coûts
ou du trafic du fournisseur n'est affirmé avant intégration et qualification.

Tous les FAIL actuels sont identifiés dans validation-summary.json avec contrôle,
code et cause. Aucun secret ou corps d'exception n'y est recopié. Le ZIP contient
les rapports détaillés et le NEXT_SESSION courant. V1 complète reste non validée.
