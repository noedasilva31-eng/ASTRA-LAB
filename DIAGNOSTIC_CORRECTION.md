# Diagnostic et correctif RPC — 30 septembre 2026

## Ce que prouvent exactement les pièces jointes

Les sections JSON de `report.json` et `report.txt` sont identiques : il s’agit
du même résultat Windows. Elles sont conservées dans `diagnostic_input/`.

- V1b : **overall PASS**, 38 tests dépôt PASS, 14 critères PASS, RPC réel capturé.
- `test_clock_regression_fail_closed` : **PASS**, sans exception ni traceback.
- Collecteur : 12 tentatives sur 6 slots, toutes `rpc_-32015`, aucune publication.
- `rpc_-32603` figure **uniquement dans la fixture déterministe**, pas dans les
  phases RPC réelles de ces pièces jointes.
- FAIL final observé : `no_real_block_archived`. Les hashes et relations SQLite
  sont intacts ; les erreurs ont été correctement conservées et comptabilisées.

L’échec d’horloge mentionné dans le message n’est donc pas attesté par les
fichiers joints. Aucun défaut de plateforme Windows ne peut être déduit de ces
pièces. Le test utilise une horloge entière injectée (`Clock`), et non la précision
de l’horloge Windows. La fermeture SQLite corrigée dans V1b est toujours présente.
Il serait incorrect de changer le produit ou le test pour corriger un échec
absent de ces preuves.

Deux tests supplémentaires renforcent le contrôle : exécution du test original
20 fois avec l’horloge système figée à zéro, puis régression injectée avec
vérification de zéro publication, rollback terminé et reprise exactement une
fois après rétablissement de l’horloge. **Ni le test V1b ni son invariant ne
sont désactivés ou assouplis. Tous les fichiers V1b restent identiques.**

## Cause getBlock et paramètres

L’ancienne requête était :

```json
{"commitment":"finalized","encoding":"json","transactionDetails":"full","maxSupportedTransactionVersion":0,"rewards":false}
```

`-32015` signifie que la version d’une transaction dépasse celle acceptée par
le client. Une seule transaction de version supérieure suffit à faire échouer
la réponse complète : il ne s’agit ni d’un slot sauté ni d’un bloc vide.
La documentation Solana demande le nombre JSON **1** pour recevoir les formats
legacy, v0 et v1. Le plafond **0** du collecteur est donc insuffisant.

Le code envoie maintenant `maxSupportedTransactionVersion: 1`, toujours avec
`finalized`, `json`, `full`, et `rewards: false`. Les transactions et leur
`transactionConfig` sont préservées intégralement dans le brut et le document ;
ce composant archive du JSON, sans décodage métier ou signature de transaction.
Aucun SDK ancien ni décodage binaire limité à v0 n’est utilisé ici.

Les rapports joints ne contiennent pas le message brut qui annoncerait le numéro
exact demandé par le serveur : la présence effective de v1 dans chacun des six
blocs n’est donc pas une preuve extraite du rapport. Le diagnostic établi est
l’incompatibilité de version avec un client limité à 0. La réussite du correctif
avec le plafond 1 doit être confirmée par le nouveau contrôle Devnet réel.
Si le serveur exige davantage, l’erreur restera FAIL : aucune hausse aveugle.

## -32603 et retries

`-32603` est une erreur interne JSON-RPC. Le code seul n’en précise ni le composant
serveur ni le caractère forcément temporaire. Ici son occurrence vient du test
synthétique. Elle reste `error`, comprise dans le total non résolu.

- `-32603` et les erreurs de transport retentables : maximum trois passes dans
  le validator, pauses par slot de 0,25 / 0,5 / 1 seconde ; chaque réponse conservée.
- `-32015` : pas de répétition avec la même version ; retry seulement après hausse
  explicite de capacité, par exemple passage archivé de 0 à 1.
- Paramètres invalides et méthodes inexistantes : pas de boucle de retry inutile.
- La commande CLI `--retry-unresolved` fait une seule passe ; son exécution peut
  être répétée explicitement. Le validator impose son budget de trois passes.
- Aucun code RPC n’est reclassé en skipped. La preuve de parenté est inchangée.

Les rapports contiennent maintenant les paramètres non secrets réellement
archivés, le code RPC, sa catégorie et sa politique de retry. Pour `-32015`,
seul le numéro de version éventuellement extrait du message est exposé ; aucun
message arbitraire, URL ou secret n’est journalisé.

## Replays historiques et gate renforcé

La correction d’une constante aurait changé le calcul des hashes des anciennes
captures. Cette seconde cause a été corrigée : les nouvelles sessions archivent
et hashent leurs paramètres ; les anciennes sessions dépourvues de ce champ
restent interprétées avec les paramètres originaux exacts (maxVersion=0).
Aucune ligne historique n’est réécrite. Un test vérifie les empreintes anciennes,
leur replay et l’ajout d’une nouvelle tentative avec maxVersion=1.

Les anciennes phases first/resume/retry disaient PASS pour les invariants du
journal même avec zéro bloc ; le gate final était bien FAIL. Le nouveau rapport
marque également ces phases FAIL quand aucun bloc n’a été archivé, tout en
poursuivant l’analyse si le journal est cohérent. Après retry, une erreur RPC
encore présente empêche aussi le PASS final, même si d’autres blocs existent.
Les réponses temporairement indisponibles restent explicitement comptabilisées
selon le contrat de couverture initial, sans être assimilées à des blocs.

## Références officielles consultées

- https://solana.com/fr/docs/core/transactions/versioned-transactions — plafond 1,
  type entier, échec global getBlock avec -32015 en cas de version supérieure.
- https://solana.com/docs/rpc/json-structures — représentation JSON des transactions v1.
- https://www.jsonrpc.org/specification — définition de -32603.

Aucune affirmation d’activation universelle d’une version de transaction n’est
nécessaire au diagnostic ; la réponse du fournisseur réel reste la preuve finale.
