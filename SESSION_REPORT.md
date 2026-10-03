# Résultat du correctif V1c — 30 septembre 2026

**Verdict de cette session : FAIL de prérequis live ; aucune régression locale.**
Cette session Linux ne dispose pas de SOLANA_RPC_URL et ne peut certifier Windows.

| Contrôle exécuté | Résultat |
|---|---|
| Référence V1b inchangée | PASS, hashes identiques |
| Tests V1c, dont 13 nouveaux | 35/35 PASS |
| Tests dépôt V1b | 38/38 PASS |
| Tests runner V1b | 8/8 PASS |
| Critères locaux V1b | 12/12 PASS |
| Quatre phases blocs réelles | FAIL prérequis endpoint absent |
| Deux critères V1b réels | FAIL prérequis endpoint absent |

Les rapports Windows reçus, antérieurs au correctif, prouvent le PASS V1b, y
compris son test d’horloge, et le FAIL de collecte getBlock dû à -32015. Ils ne
prouvent pas le PASS réel de cette nouvelle version. Voir `diagnostic_input/`.

Correctifs testés : plafond de version numérique 1, paramètres archivés/hashés,
compatibilité de replay avec les archives v0, retry borné des erreurs internes,
absence de retry aveugle des versions non supportées, aucun faux PASS avec zéro
bloc, diagnostics numériques sans messages/URLs sensibles, invariants d’horloge
réexécutés sans dépendre de l’horloge système.

Métriques synthétiques : 6 slots comptabilisés sur 6 ; avant retry 3 blocs,
1 slot sauté et 2 non résolus ; après retry 5 blocs + 1 slot sauté, 8 tentatives
conservées, zéro doublon, zéro erreur de hash. Les tests supplémentaires couvrent
les transactions legacy/v0/v1 et une panne interne persistante : 24 tentatives
maximum sur 6 slots (6 initiales + 3 passes de retry), avec FAIL conservé.

`validation_evidence/report.json` et `report.txt` sont les rapports de cette
exécution complète. `DIAGNOSTIC_CORRECTION.md` détaille les preuves et limites.
