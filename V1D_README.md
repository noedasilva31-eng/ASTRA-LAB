# ASTRA V1d — transferts SOL et dataset local reconstruisible

Cette version ajoute `astra_memory/`, `memory_tests/` et `memory_validation/`.
Les 75 fichiers de la candidate `ASTRA-V1c-rpc-v1-fix` sont conservés octet
pour octet et vérifiés par `V1C_REFERENCE.json`. Les tests V1b/V1c et leurs
lanceurs ne sont pas modifiés. Les anciens rapports restent des preuves
historiques ; consulter `memory_validation_evidence/` pour cette session.

## Une commande Windows

Avec Python 3 et `SOLANA_RPC_URL` déjà défini dans l'environnement :

```bat
validate-memory-windows.cmd
```

Exécute les tests V1d, la chaîne simulée, une plage réelle Devnet de six slots
finalisés avec interruption/reprise, l'import hors réseau, puis le lanceur
`validate-blocks-windows.cmd` inchangé, qui appelle `validate-windows.cmd`.
Tout utilise des bases temporaires dédiées. Aucune base utilisateur n'est
ouverte par le validator. Les rapports JSON/texte sont dans le nouveau dossier
`memory-validation-*`. Code retour 0 uniquement si tous les contrôles passent.
Aucune URL complète ni clé n'est affichée. Aucun portefeuille ni envoi de
transaction n'est requis. Les corps RPC reçus suivent le filtrage V1c existant.

Sans endpoint, les contrôles réels sont FAIL (`live_endpoint_not_used`), jamais
PASS. `--self-test` lance les contrôles locaux en laissant ces FAIL explicites.
Linux : `python3 -B validate_memory_all.py`. Un PASS Linux ne qualifie pas Windows.
Le contrôle de décodage réel exige au moins un transfert pris en charge dans
la plage ; sinon `no_supported_transfer_observed` reste FAIL. Les programmes
non pris en charge sont comptés, sans devenir des transferts artificiels.

## Périmètre et invariants

- Entrée : publications de blocs Devnet finalisés déjà vérifiées par V1c.
  Connexion source en lecture seule, snapshot SQLite cohérent temporaire, audit
  du snapshot avant import. Les slots non publiés restent gérés par V1c.
- Décodage : instruction **System Program Transfer native SOL de premier niveau**,
  opcode 2, comptes indexés, entier u64 en chaîne décimale. Transactions JSON
  legacy/0/1 ; adresses chargées des transactions v0 résolues depuis les métadonnées.
- Transaction échouée : aucun transfert émis. Statut d'exécution absent : erreur.
  Autres programmes/opcodes/versions : non pris en charge explicitement.
  Les CPI restent non pris en charge : le succès de la transaction ne suffit
  pas à prouver le succès individuel de chaque appel interne enregistré.
- Chaque transaction reçue a un résultat processed/failed/unsupported/error.
  Chaque instruction analysable a un résultat decoded/unsupported/error.
  La couverture des instructions n'est pas affirmée pour une transaction
  illisible, échouée ou de version inconnue. Les compteurs distinguent ces cas.
- Brut commité avant décodage ; métadonnées et documents hashés ; aucune mutation
  UPDATE/DELETE permise par l'API SQLite. La publication des événements et le
  document décodé sont commités atomiquement. Une même identité divergente est
  refusée ; le brut original reste intact. Ce refus ne remplace pas la quarantaine V1b.
- Reprise par réimport idempotent et traitement des entrées non publiées. Un
  événement conserve sa publication existante. Tests d'arrêt brutal dans un
  sous-processus, avant et après publication ; test de rollback transactionnel.
- Dataset : bruts exacts, contextes de finalité, hashes des décodages, événements,
  version et empreintes du code décodeur/normaliseur. Reconstruction hors réseau
  dans un nouveau fichier uniquement, refus si code ou hashes divergent.
  Une reconstruction invalide ne publie pas de base de destination.

## Utilisation locale facultative

Depuis ce dossier, avec des chemins dédiés :

```bat
py -3 -m astra_memory --db memory-new.sqlite import --blocks-db blocks.sqlite
py -3 -m astra_memory --db memory-new.sqlite recover
py -3 -m astra_memory --db memory-new.sqlite audit
py -3 -m astra_memory --db memory-new.sqlite export dataset-new.json
py -3 -m astra_memory --db memory-restored-new.sqlite rebuild dataset-new.json
```

L'export refuse un fichier existant ; la reconstruction refuse une base existante.
Le validator vérifie automatiquement compteurs, hashes, absence de doublons et
égalité du dataset reconstruit. Aucun comptage manuel n'est demandé.

## Limites explicites

Cette mémoire est une projection métier locale et partielle, pas l'ensemble
Market Memory normatif de `docs/DATA_CONTRACTS.md`. Son dataset indique
`accepted_blocks_only` et `reconstruction_only` : il ne contient pas le journal
complet des slots V1c ni les anciens instants physiques de disponibilité.
Les dates locales de réception/publication ne sont pas des dates historiques
utilisables pour un backtest. Aucun accès stratégie/as-of n'est exposé.
SPL, Token-2022, swaps, CPI, graphe temporel, multi-provider, archive distante,
quotas/alertes et qualification 72 h restent à réaliser. Les hashes ne protègent
pas contre une réécriture coordonnée du fichier et de ses empreintes par un administrateur.

Références de format : https://solana.com/docs/rpc/json-structures et
https://solana.com/docs/core/transactions ; conservation des paramètres RPC V1c.
