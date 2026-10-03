# Sprint fonctionnel — état livré

Commande de validation unique : `validate-all.cmd` (Windows, Python 3.12).
`SOLANA_RPC_URL` reste exclusivement une variable d'environnement. Aucun envoi de
transaction ni trading LIVE n'est implémenté par ces ajouts.

## Correctif live_memory

Le FAIL Windows fourni provenait de l'absence d'un transfert natif compatible
dans la petite plage, et non d'une erreur démontrée du décodeur. L'adaptateur de
gate préserve le runner V1d de référence et tous ses contrôles. Il sélectionne
une capture compatible de la plage ; à défaut, recherche les 64 slots précédents
au maximum, avec 66 tentatives HTTP budgétées (contexte inclus), un budget de
recherche de 100 secondes et un processus limité à 120 secondes. Aucun événement
n'est fabriqué. La preuve sélectionnée est archivée puis reconstruite dans un
nouveau processus hors réseau. L'épuisement reste FAIL `sol_probe_exhausted`.

Les preuves et tentatives sont conservées dans `memory_validation/memory-report-*`.
Le JSON du rapport indique `proof_artifacts_directory`. La copie SQLite inclut
le WAL par l'API backup, même après timeout. Le replay doit produire au moins un
transfert réel. Les validateurs historiques isolés restent historiques : utiliser
la gate racine pour bénéficier de la sélection corrigée.

## PumpSwap : premier adaptateur DEX ciblé

`astra_dex` décode six instructions PumpSwap : `buy`, `buy_exact_quote_in`,
`sell`, `create_pool`, `deposit`, `withdraw`. Les cinq types d'événements associés
sont lus selon un sous-ensemble figé du schéma officiel :
https://github.com/pump-fun/pump-public-docs/blob/e0687ae9b7e064a0f54efc7297c65eecfbba3a8f/idl/pump_amm.json

Le schéma embarqué conserve le commit, la date de récupération et le SHA-256 du
fichier source complet. Le contenu du commit a été comparé au téléchargement.
Les métadonnées techniques de l'IDL sont utilisées pour les interfaces, aucun
SDK externe n'est requis. L'adaptateur est enregistré par identifiant de programme.

Périmètre exact : instruction **top-level**, transaction réussie, événement
self-CPI direct avec `stackHeight=2`, programme/autorité/comptes cohérents avec
l'instruction parente. Les appels routés CPI restent `unsupported`. Une absence
d'événement ou de preuve de profondeur reste `unresolved`. Un payload incohérent
ou un format incompatible est `error`. Les formats historiques ne sont pas
implicitement assimilés au schéma actuel. Tous restent archivés et comptabilisés.

Sortie : wallet, pool, mints, sens du swap, montants entiers bruts réellement
rapportés par l'événement, composantes de frais séparées, réserves signées,
slot/transaction/instructions, hash du décodeur et brut source. Aucun montant
`max_*` n'est présenté comme un montant exécuté ; les frais ne sont pas additionnés
sans preuve de leur sémantique. Les réserves ne constituent pas une cotation
exécutable et les unités brutes ne supposent pas de décimales connues.

`astra_pipeline run/poll/offline` exporte ces données sous `business/dex/` et
les inscrit dans la timeline. Les erreurs DEX font échouer le pipeline. Les
couvertures partielles restent explicites. Les tests DEX sont **synthétiques**,
issus des interfaces documentées ; ils ne qualifient pas le décodeur en réel.
`real_protocol_capture_qualified: false` est une limite de cette livraison,
pas une inférence sur l'origine du dataset analysé.

Replay ciblé d'un dataset archivé compatible :

```bat
python -m astra_dex --dataset DATASET.json --output DEX.json --require-event
```

`--require-event` refuse une archive sans événement pris en charge. Un PASS de
replay sans cette option ne prouve que la reconstruction, pas la présence DEX.

## Timeline : connaissances disponibles, pas chronologie réécrite

`astra_timeline` est branché automatiquement à la publication métier. Il stocke
le dataset complet vérifié, ses features, un reçu séquentiel, un timestamp local
et une chaîne de hashes, en SQLite append-only transactionnel. La réingestion
idempotente ne modifie jamais le reçu d'origine. Un crash avant commit ne publie
rien ; après commit, une reprise retrouve le reçu sans duplication.

Les premières features sont des **faits observés par slot** : compteurs de
transactions/transferts, changements de soldes exacts, événements DEX, provenance
et états de couverture. Elles ne sont pas des scores smart-money ni une estimation
des holders globaux. Les sources sociales sont `not_collected`, jamais "zéro".

Une requête à la séquence 1 ignore les données reçues à la séquence 2, même si
elles concernent des slots plus anciens. Un retry futur ne remplit donc pas les
trous des vues historiques. Les slots hors archives restent `not_observed`.
Les événements vérifiés antérieurs ne sont pas effacés par une vue moins complète.
Des blocs finalisés contradictoires provoquent un refus lors de la requête.

```bat
python -m astra_timeline query --db WORK\business\timeline.sqlite --start 100 --end 120 --sequence 1 --output ASOF.json
python -m astra_timeline snapshot --db WORK\business\timeline.sqlite --output KNOWLEDGE.json
python -m astra_timeline restore --db NEW\timeline.sqlite --input KNOWLEDGE.json
```

Le cutoff séquentiel représente exactement les reçus engagés. Le timestamp local
`recorded_ns` représente l'ingestion ; il ne prouve pas la disponibilité physique
historique du bloc, la synchronisation de l'horloge, ni l'instant exact du commit.
`--as-of-ns` filtre ces timestamps avec cette limite explicitement déclarée. Une
régression de l'horloge entre nouveaux reçus est refusée. Une restauration fidèle
requiert le journal de reçus : reconstruire seulement les blocs ne permet pas
 d'inventer les anciens instants de connaissance. Les empreintes de code imposent
le replay avec la version de calcul correspondante.

Cette première implémentation vérifie/reconstruit les snapshots complets : elle
appartient au **Research/Memory Path**, pas à un Hot Path basse latence qualifié.

## Alertes persistantes

Les commandes `run/poll` alimentent un journal local d'ouvertures/résolutions,
dédupliqué et reconstructible, avec hashes. Un état incomplet ne résout aucune
alerte active. Les codes sont limités à une liste autorisée ; les messages externes
arbitraires et secrets ne sont pas stockés. Aucune notification externe n'est envoyée.

## Ce qui manque à V1

Les tests locaux ne suffisent pas à annoncer V1 terminée. Restent notamment :
qualification réelle du format PumpSwap retenu et extensions guidées par les
captures ; résolution des routes CPI et versions historiques ; Hot Path incrémental
séparé ; prix/liquidité et hypothèses d'exécution vérifiés ; features temporelles
agrégées ; moteur paper + Risk + journal décisionnel ; wallets/holders/graphes et
bundles avec couverture prouvée ; interfaces sociales alimentées ; coûts/débits
fournisseurs ; indépendance multi-provider ; archive distante restaurée ; horloges
et disponibilité qualifiées ; harness et exécution de qualification 72 h. Les agents
R&D, promotions de candidats et LIVE ne sont pas implémentés par cette livraison.
