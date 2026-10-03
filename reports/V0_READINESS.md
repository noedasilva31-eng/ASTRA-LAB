# ASTRA — V0 Readiness Report

Date : 29 septembre 2026. Verdict : **V0 prêt pour démarrer V1 ; V1a offline construit et testé. V1 connecté non qualifié.**

Cahier des charges fourni lu intégralement et conservé sans modification dans docs/REQUIREMENTS.md. Aucune connexion wallet, aucun ordre, aucune stratégie rentable revendiquée.

## État réel

| Statut | Livré / périmètre |
|---|---|
| DESIGNED | Architecture Brain/Engine, Market Memory logique, enveloppe temporelle, contrats des neuf rôles, registries et protocole scientifique, gates promotion/rollback, exploitation cible, huit ADR |
| IMPLEMENTED | Journal local SQLite : octets bruts, réception, validation, normalisation, publication, quarantaine, déduplication, révisions/rétractions, vue as-of, snapshots hashés, reprise, integrity checks et backup ; CLI et interfaces provider |
| TESTED | 32 tests automatisés PASS ; quatre contrats JSON vérifiés structurellement ; fixture et huit ADR vérifiés ; smoke test CLI ingestion/health/as-of/snapshot/recover/backup PASS avec snapshot restauré identique |
| RUNNING | Aucun service persistant. Seules les commandes et tests ponctuels ont été exécutés. Aucun agent de recherche actif |
| VALIDATED | Aucune stratégie ni performance de marché. Les preuves locales portent uniquement sur les invariants couverts par les tests synthétiques |

Preuves brutes : reports/tests.txt, reports/spec-checks.txt, reports/smoke.json. Tests exécutés sous Python 3.12.14. Aucun test réseau/provider, PostgreSQL, Rust, power-loss ou soak 24/7 exécuté. Le test d'interruption ferme et rouvre la base entre étapes durables ; il ne simule pas une panne électrique.

## Décisions ADR

001 : journal temporel et corrections append-only.
002 : référence SQLite locale, cible PostgreSQL + objet en production.
003 : Brain/Engine séparés et bundle de stratégie contrôlé.
004 : abstraction streaming multi-provider, Yellowstone candidat.
005 : préenregistrement, OOS, coût réel et gate de preuves.
006 : LLM par capacités, aucun modèle supposé accessible.
007 : transport idempotent/outbox, bus différé.
008 : graphe temporel sourcé, pas de fusion arbitraire d'acteurs.

Les choix fournisseurs sont des candidats documentés, pas des abonnements ni des capacités de compte vérifiées. Références officielles et critères de benchmark dans docs/SOURCES_AND_PROVIDERS.md.

## Risques ouverts

1. **Disponibilité exacte à T** : V1a horodate avant commit. L'ordre logique et les corrections sont testés, pas la microseconde exacte d'accès inter-processus. Bloquant avant live : reçus côté Engine avec offsets/IDs consommés et qualification des délais de publication. Ne pas présenter le prototype comme garantissant déjà toute reconstruction physique à T.
2. **Immutabilité** : triggers et hashes locaux, sans WORM ni ancrage externe ; un administrateur peut modifier fichiers/triggers/hashes. Archive objet protégée à construire.
3. **Données réelles** : aucune collecte Solana, decoding de DEX, résolution de forks, mesure de couverture ou confrontation de providers. Le payload est opaque ; aucune validité financière déduite.
4. **Montée en charge / 24 h sur 24** : ni réplication, supervision, alerting, backpressure distribué, test disque plein ni restauration distante qualifiés. Health est un audit O(n).
5. **Recherche** : agents et registries opérationnels à construire. Les documents et JSON Schemas ne font pas appliquer seuls les gates, budgets, autorisations ni corrections de tests multiples.
6. **Coûts / social** : accès, rétention, droits de conservation, budget, latence et historique à vérifier sur les comptes choisis. Un dataset rétrocollecté ne démontre pas ce qu'ASTRA aurait réellement su.
7. **Engine** : Rust candidat non benchmarké ; aucun signer ou ledger de trading construit. Les objectifs de latence et reprise sont des cibles non mesurées.

## Dépendances et actions

| Statut demandé | Étape | Suite |
|---|---|---|
| AUTONOME — effectué | V0, code V1a, tests, documentation, package | Livré |
| À CONSTRUIRE | Collecteur Solana, adaptation du brut RPC/Geyser, manifests distribués, décodeurs, finalité et qualité | Prochaine tranche V1b, après accès à un environnement utilisable |
| NÉCESSITE MON ACTION | Environnement persistant autorisant RPC/gRPC Solana et endpoint fournisseur en lecture seule | Mettre cet environnement à disposition ; injecter l'identifiant via son gestionnaire de secrets, pas dans le chat |
| NÉCESSITE MON ACTION, plus tard | Compte/droits/budget social | Seulement avant collecte sociale V2 |
| À CONSTRUIRE | Agents, paper/shadow, backtesting, Engine et wallet integration | Dans l'ordre V2–V6 et sous leurs gates |

Aucun compte, paiement, hébergement ou accès externe n'a été engagé. L'environnement présent ne fournit pas de service Solana persistant connecté ni d'accès réseau général pour le collecteur. Aucune action wallet nécessaire.

## Critères de passage

V0 : dix critères documentaires remplis dans docs/TESTING_ACCEPTANCE.md ; V1a a donc été commencé sans demander de micro-autorisation.

V1a : invariants locaux couverts par tests PASS. V1 global reste ouvert, sans saut vers des agents censés travailler sur des données inexistantes.

Prochaine acceptation V1b : feed réel avec captures, provenance et couverture mesurée ; décodeurs métier ; aucune perte silencieuse après ACK ; forks/corrections testés ; snapshots reproduits depuis le brut ; horloges et réception Engine qualifiées ; restauration distante ; quotas/coûts et alertes ; soak 72 h. Ensuite seulement qualification pour V2. Aucune durée de disponibilité de cette conversation ne vaut hébergement 24/7.
