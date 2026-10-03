# ASTRA V1e — provenance et couverture des datasets

Nouvelle version séparée de V1d. Aucun des 98 fichiers livrés dans le ZIP V1d
n'est modifié. Leurs hashes sont contrôlés dans `V1D_REFERENCE.json` ; les gates
V1d/V1c/V1b sont exécutés sans modification. Les rapports Windows V1d reçus sont
conservés dans `baseline_windows_evidence/`, distincts des résultats locaux V1e.

## Validation Windows en une commande

```bat
validate-provenance-windows.cmd
```

Python 3 et `SOLANA_RPC_URL` déjà défini sont nécessaires pour les contrôles
réels. Le lanceur ne demande ni n'affiche l'endpoint. Bases et archives de test
sont temporaires ; aucune base utilisateur n'est utilisée. Il exécute les tests
V1e, le scénario déterministe et la collecte Devnet réelle, puis appelle
`validate-memory-windows.cmd` inchangé, qui appelle les gates V1c et V1b.
Rapports : nouveau dossier `provenance-validation-*/report.json` et `report.txt`.
Code retour 0 seulement si tous les contrôles passent. Sans endpoint, les
contrôles réels restent FAIL. `--self-test` ne les transforme pas en PASS.
Linux : `python3 -B validate_provenance_all.py`.

Le contrôle réel emploie six slots finalisés, une interruption au milieu,
reprise, retries bornés, puis traitement hors réseau dans un nouveau processus.
Il exige une plage résolue, au moins un événement métier pris en charge et zéro
erreur de décodage. Une plage sans transfert SOL pris en charge reste FAIL,
sans création de transaction ni supposition. Les instructions unsupported
restent explicitement mesurées ; elles ne prouvent pas une couverture métier totale.

## Archive et preuves

`astra_provenance/` est un module indépendant. Il prend un snapshot cohérent
par l'API backup SQLite avec connexion source en lecture seule. Le snapshot
conserve toutes les tables V1c : plage, checkpoint, sessions et paramètres RPC,
tentatives et bruts exacts en base64, résultats, états des slots et publications.
La capture de cette archive dans le journal V1e est commitée avant dérivation.

Le dataset comprend l'archive, les empreintes du décodeur/normaliseur/provenance,
les données métier, leurs liens aux preuves et le manifest de couverture. Le
hash racine couvre l'ensemble. Chaque événement référence slot, blockhash,
tentative, session, hash brut, hash de preuve et hash du bloc publié. Sa signature
et ses indices d'instruction restent ceux du décodeur V1d. Les dates de réception
et publication V1c sont conservées comme provenance, **sans promettre une
mesure de disponibilité physique ou une vue as-of**.

La reconstruction crée une base source temporaire à partir des tables archivées,
revérifie les relations, hashes, replays, publications et preuves de saut,
réexécute le décodeur V1d et recalcule le manifest. Les données dérivées fournies
ne sont pas crues sur leur seul hash : elles doivent correspondre exactement
à cette reconstruction. Aucun accès réseau n'est nécessaire.

## Couverture explicite

La plage demandée est inclusive `[start, end]` et doit être dans la plage de
l'archive. Chaque slot reçoit exactement un état :

| État | Signification |
|---|---|
| archived | Bloc accepté et publié, inclus dans la dérivation |
| skipped | Saut prouvé par deux blocs finalisés archivés, parent/hash cohérents |
| unresolved | Null, indisponibilité ou slot pas encore tenté ; jamais assimilé à un saut |
| error | Erreur RPC explicitement archivée, toujours non résolue |
| excluded | Bloc accepté délibérément exclu de cette sélection ; preuve du bloc conservée |

Une exclusion ne peut pas masquer un slot non résolu, en erreur ou sauté.
Une sélection ne supprime pas les témoins hors de ses frontières : les blocs
parent/enfant nécessaires à prouver un saut restent dans l'archive complète.
Une tentative brute encore sans résultat rend la source non admissible : il
faut la récupérer via V1c avant d'en publier un dataset V1e.

Invariant : `expected_slots = archived + skipped + unresolved + error + excluded`.
`accounting_ok` signifie qu'aucun slot n'est oublié, pas que la plage est complète.
`source_complete` concerne la plage sélectionnée et exige zéro unresolved/error.
`included_range_complete` exige aussi zéro excluded. `fully_decoded` exige en
plus la couverture métier V1d, sans instruction inconnue ou erreur de décodage.
Les métriques distinguent la plage de l'archive, la sélection, les tentatives,
les erreurs historiques et les erreurs de décodage. Le rapport expose les
versions avant/après retry plutôt que d'effacer l'état initial incomplet.

## Reprise et versions

Le journal SQLite V1e est append-only : captures, datasets et événements uniques.
Une même archive est dédupliquée ; une nouvelle archive après retry produit une
nouvelle version de dataset. L'ancien dataset reste inchangé. Les références de
provenance appartiennent à chaque version ; les événements déjà connus ne sont
pas republiés. Dataset et nouveaux événements sont commités atomiquement.
`recover` reconstruit depuis les captures durables ; une preuve corrompue reste
bloquante. Le journal n'invente pas une réparation ni une acceptation silencieuse.

## Commandes facultatives

```bat
py -3 -m astra_provenance import --source blocks.sqlite --db provenance-new.sqlite
py -3 -m astra_provenance recover --db provenance-new.sqlite
py -3 -m astra_provenance audit --db provenance-new.sqlite
py -3 -m astra_provenance export --db provenance-new.sqlite --id 1 --output dataset-new.json
py -3 -m astra_provenance reconstruct --source dataset-new.json --output rebuilt-new.json
```

`import` accepte `--start`, `--end` et `--exclude` (liste de slots archivés).
Les exports refusent un fichier existant. Les bases d'autres modules sont
refusées. Le validator réalise toutes les comparaisons automatiquement.

Limites : un seul journal source à la fois ; snapshots complets adaptés aux
petites plages ; aucune réconciliation multi-provider, aucun stockage WORM,
aucune preuve indépendante contre une réécriture coordonnée des données et
hashes par l'administrateur. Cette brique ne réalise ni la vue as-of ni V1 entière.
Les documents historiques restent inchangés ; le point de reprise courant est
`v1e_handoff/NEXT_SESSION.md`.
