# Reprise exacte — ASTRA-V1-paper

Partir de cette version sans remplacer ASTRA-V1-observatory. Le retour Windows
255 tests PASS avec FAIL V1e live_provenance est stocké séparément comme déclaration
utilisateur. Le FAIL combiné ne prouve pas à lui seul que seul le hasard des transferts
est en cause ; ne pas supprimer l'exigence ni demander des essais aléatoires.

Réalisé : décodage transactionnel PumpSwap routé avec preuve de profondeur CPI ;
identifiants/provenance/replay ; durées notification-traitement et HTTP p95/p99 ;
contrat de quote archivée ; ledger PAPER conditionnel BUY/REJECT/SELL, cash/positions/
PnL, délais+TTL/frais/décote configurés, Risk réévalué, chaînes de hashes, idempotence
et audit hors réseau ; gate permanente étendue.

Première dépendance concrète : provider Mainnet et capture réelle qualifiée via
validate-all.cmd (ASTRA_OBSERVER_* distinct de SOLANA_RPC_URL Devnet). Aucun endpoint
ni credential n'était disponible ici. Inspecter les preuves de la recherche bornée
et adapter uniquement les formes réellement observées, sans inventer leur support.

Premier travail de code après capture : fournisseur de preuves quotes/autorités/
liquidité/sortie et santé, issu de raw archivé, puis intégration du ledger PAPER au
flux. Le module quote est un import indicatif Jupiter v1, non un client live actuel.
Choisir un contrat provider maintenu et épinglé avant le branchement réel.

Les scénarios PAPER positifs sont synthétiques, les états de risques autres que la
quote restent des entrées de confiance. Ne pas les déléguer à une stratégie/LLM.
Le flux réel observatory reste PARTIAL/NO_TRADE. Pas de fill réel ou fictivement
qualifié. Implémenter ensuite launch/bonding/migration, réconciliation finalisée,
modèle de frais exécutables et liaison portfolio/outcomes. Aucun ordre LIVE.

Tests ciblés : execution_tests. Non-régression finale : validate-all.cmd. État exact
PASS/FAIL dans CHECKLIST.json, rapports et PAPER_SPRINT.md. Les handoffs antérieurs
et NEXT_SESSION.md racine sont historiques.
