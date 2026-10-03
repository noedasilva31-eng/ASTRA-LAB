# État fonctionnel V1 — intégration

| Objectif | État |
|---|---|
| Socles V1b–V1f | Baseline Windows fournie PASS ; non-régression locale PASS |
| Quotas reliés au RPC | Implémenté ; tentative durable avant chaque appel ; tests locaux PASS |
| Plages successives | Poll borné avec reçus, reprise et budget partagé ; tests locaux PASS |
| Dataset métier | SOL, SPL TransferChecked classique, soldes token pré/post, frais/statuts ; partiel et explicite |
| Brut/provenance/couverture | Conservés et reconstructibles ; tests locaux PASS |
| Index et exports | SQLite idempotent, JSON autonome, événements/transactions JSONL ; tests locaux PASS |
| Comparaison de sources | Outil d'archives sans arbitrage ; indépendance réelle NON QUALIFIÉE |
| Alertes | Diagnostics locaux dans les rapports ; pas encore d'escalade externe |
| Intégration Windows/Devnet actuelle | NON EXÉCUTÉE ici |
| Gate globale courante | FAIL : endpoint absent ; local_overall PASS |
| V1 complète | NON TERMINÉE |

189/189 tests locaux : 159 de la baseline et 30 nouveaux tests pipeline.
Les scénarios couvrent token/entiers/valeurs manquantes, quotas partagés,
interruption/reprise, source ayant avancé pendant une interruption, atomicité,
corruption, exports et reconstruction, conflits entre observations, reprise
du curseur des plages et attente de finalité.

L'exemple inclus est SYNTHÉTIQUE : deux blocs, deux transactions, deux
instructions SPL TransferChecked et quatre variations de solde token, quatre
réservations RPC simulées. Il ne prouve aucune couverture réseau réelle.

Manques précis avant V1 complète : décodeurs des programmes DEX/pools réellement
ciblés, supervision continue et qualification de charge/backpressure, politique
de facturation/débit fournisseur, alertes persistantes et escaladées,
réconciliation de fournisseurs indépendants réels, archive distante avec
rétention/restauration exercée, disponibilité physique/offsets/horloges,
soak 72 h et seuils de couverture/lag fixés avant qualification.

La commande validate-all.cmd est le jalon groupé d'intégration. Aucun nouveau
contrôle manuel n'est demandé pour chaque sous-composant. Les rapports courants
et NEXT_SESSION.md de ce dossier font foi pour la reprise ; les anciens rapports
et documents restent conservés comme historique.
