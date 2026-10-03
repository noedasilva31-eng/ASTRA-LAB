# Résultats V1e — session locale Linux

| Groupe | Résultat |
|---|---|
| Tests provenance V1e | 28/28 PASS |
| Tests mémoire V1d | 31/31 PASS |
| Tests blocs V1c | 35/35 PASS |
| Tests dépôt V1b | 38/38 PASS |
| Tests runner V1b | 8/8 PASS |
| Total tests | 140/140 PASS |
| Critères locaux V1b | 12/12 PASS |
| Référence V1d intacte | 98 fichiers identiques au ZIP validé |
| Contrôles réels V1e/V1d/V1c/V1b | FAIL : endpoint absent |
| Windows V1e | NON EXÉCUTÉ |
| Verdict global | FAIL : prérequis réels manquants |

PASS locaux : frontières de plage, provenance de chaque événement, saut avec
preuves hors sélection, slot non tenté explicite, erreur distincte du saut,
exclusion explicite, brut avant dérivation, reprise en nouveau processus,
arrêts brutaux avant/pendant/après publication, absence de double publication,
retry conservant l'erreur et l'ancienne version, reconstruction exacte hors
réseau, empreintes de code, corruption et fausse complétude rejetées.

Scénario déterministe sur 6 slots : avant retry, 3 archivés + 1 sauté +
1 unresolved + 1 error ; accounted_fraction=1 mais source_complete=false.
Après retry, 5 archivés + 1 sauté, source_complete=true ; 8 tentatives,
1 erreur historique conservée, 2 versions immuables, 5 événements uniques,
0 pending et 0 erreur de hash/replay/FK. Les exports reconstruits sont identiques.
Ce sont des métriques de fixture, pas de couverture mesurée du réseau Devnet.

Contrôles réels préparés : collecte finalisée sur 6 slots, interruption/reprise,
retry, replay hors réseau, dérivation avec provenance et reconstruction du
dataset. Les gates réels V1d/V1c et les deux critères RPC réels V1b sont également
obligatoires. Aucun prérequis absent n'est requalifié PASS.

Les preuves Windows V1d fournies par l'utilisateur sont conservées séparément
et restent PASS ; elles ne prouvent pas la nouvelle qualification V1e Windows.
Aucun FAIL fonctionnel local ne subsiste. V1 complète reste non qualifiée.
Voir report.json/report.txt pour chaque test et les preuves détaillées.
