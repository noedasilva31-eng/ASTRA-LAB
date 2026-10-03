# Point exact de reprise

1. Partir de `ASTRA-V1d-memory.zip` dans un nouveau dossier. Garder
   `ASTRA-V1c-rpc-v1-fix` et `ASTRA-V1b-windows-fix` intacts.
2. En environnement Windows disposant déjà de `SOLANA_RPC_URL`, exécuter
   `validate-memory-windows.cmd`. Tout contrôle et toute comparaison sont automatiques.
3. Lire le **nouveau** `memory-validation-*/report.json`. Exiger : 31 tests V1d,
   35 tests blocs, 38 tests dépôt, 8 tests runner V1b, scénarios simulés,
   contrôles Devnet réels, dataset/replay hors réseau et non-régression PASS.
   Aucun de ces contrôles réels n'a pu être exécuté dans la présente session.
4. Si `live_memory` échoue, utiliser les compteurs/code du rapport. Les erreurs
   réelles restent FAIL. Une plage sans transfert natif pris en charge ne valide
   pas le décodeur réel ; une nouvelle exécution emploie une nouvelle petite plage.
   Les autres programmes restent explicitement unsupported, jamais décodés par supposition.
5. Après qualification réelle, ajouter une provenance versionnée des tentatives,
   publications V1c et couverture des slots dans le manifest dérivé, avec tests
   empêchant une interprétation de la projection comme disponibilité historique.
   Ensuite seulement préparer la vue as-of/offsets ou élargir les programmes.
6. Conserver les gates V1b/V1c/V1d obligatoires. La checklist `V1_STATUS.md`
   énumère les dépendances restantes (multi-provider, archive distante,
   horloges, quotas/alertes et soak 72 h).

Aucune lecture manuelle de compteurs n'est nécessaire. Les seuls prérequis
externes à cette session sont l'exécution Windows et l'endpoint Devnet déjà
configuré ; ne jamais joindre sa valeur aux rapports. Aucun compte supplémentaire
ni transaction financière n'est nécessaire pour cette étape.
